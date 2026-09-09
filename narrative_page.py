"""회의 문안 생성기 페이지와 API.

값은 성과리포트가 이미 들고 있는 데이터에서 가져오고,
회의별 입력과 완성 문안은 회차별로 서버에 남긴다.

두 가지 보정이 들어간다.

1) 가마감
   리포트는 "그 달의 가마감·마감"을 다음 달 행의 prev_* 로 들고 있다.
   (8월 가마감 = 9월 리포트의 prev_preclose)
   그래서 한 달치를 만들 때 당월과 익월 리포트를 함께 읽어 정규화한다.

2) 잠정마감 보존
   SalesOps는 잠정과 확정을 한 칸(final_close_amount)에 담는다.
   10일경 확정으로 잠기면 잠정 값이 덮여 사라지므로,
   마감값을 처음 본 시점에 한 번만 별도 파일에 기록해 둔다. 이후 덮어쓰지 않는다.
   그래야 2차 실적회의에서 잠정 ↔ 확정 비교가 남는다.

국내는 SalesOps가 유일한 입력 창구다.
이 화면에서는 config의 editable_regions 밖 지역을 아무도 편집할 수 없다.
"""

import json
import os
import re
import time
from pathlib import Path

import browser_bridge as prev
import root_live_fetch as live
import narrative_store as store_mod
from flask import jsonify, make_response, redirect, request

app = prev.app
base = live.base

TEMPLATE = Path(__file__).with_name("narrative.html")
LINK_ID = "mp-narrative-link"
REPORT_PATHS = ("/", "/performance-report")
PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")
KEY_RE = re.compile(r"^(\d{4})-(\d{2}):([a-z0-9_]{1,16})$")
MAX_PERIODS = 4

OWN_FIELDS = ("first", "second", "third_confirmed", "third_forecast", "close", "carryover")
PREV_MAP = {"prev_first": "first", "prev_preclose": "preclose", "prev_close": "close"}

STORE = store_mod.RoundStore(base.DATA_DIR)
PROV_PATH = Path(base.DATA_DIR) / "narrative_provisional_close.json"


def _config():
    try:
        import narrative_config
        cfg = getattr(narrative_config, "CONFIG", None)
        if isinstance(cfg, dict) and cfg.get("meetings"):
            return cfg
    except Exception:
        pass
    return {}


def _to_int(value):
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except Exception:
        return None


# ---------- 잠정마감 보존 ----------

def _read_prov():
    try:
        with open(PROV_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def _write_prov(payload):
    PROV_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(PROV_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PROV_PATH)


def _apply_provisional(period, rows):
    """마감값을 처음 본 시점에 잠정으로 기록하고, 기록된 값을 provisional로 실어 준다."""
    payload = _read_prov()
    record = dict(payload.get(period) or {})
    changed = False
    for region, businesses in rows.items():
        for business, values in businesses.items():
            key = region + "|" + business
            close = values.get("close")
            if key not in record and close is not None:
                record[key] = {"amount": close, "captured_at": time.strftime("%Y-%m-%d %H:%M:%S")}
                changed = True
            if key in record:
                values["provisional"] = record[key].get("amount")
    if changed:
        payload[period] = record
        try:
            _write_prov(payload)
        except Exception:
            pass
    return rows


# ---------- 리포트 읽기 ----------

def _merge(out, report, mapping):
    if not report:
        return
    collected = {}
    for row in report.get("rows", []) or []:
        if not isinstance(row, dict) or row.get("is_total"):
            continue
        region, business = row.get("region"), row.get("business")
        if not region or not business:
            continue
        bucket = collected.setdefault((region, business), {})
        for src, dst in mapping.items():
            value = _to_int(row.get(src))
            if value is None:
                continue
            bucket[dst] = value if bucket.get(dst) is None else bucket[dst] + value
    for (region, business), values in collected.items():
        out.setdefault(region, {}).setdefault(business, {}).update(values)


def _build(year, month):
    try:
        return live._build_report(year, month)
    except Exception:
        return None


def _period_rows(year, month):
    out = {}
    _merge(out, _build(year, month), {f: f for f in OWN_FIELDS})
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    _merge(out, _build(ny, nm), PREV_MAP)
    return _apply_provisional("%04d-%02d" % (year, month), out)


# ---------- 사용자·권한 ----------

def _current_user():
    try:
        return base.current_user()
    except Exception:
        return None


def _my_scope(user):
    cfg = _config()
    scope = store_mod.scope_of(user, cfg.get("scopes") or {})
    allowed = cfg.get("editable_regions")
    if allowed:
        regions = [r for r in (scope.get("regions") or []) if r in allowed]
        scope["regions"] = regions
        scope["readonly"] = not (regions and scope.get("businesses"))
        scope["label"] = ("/".join(regions) + " " + "·".join(scope.get("businesses") or [])).strip() or "조회 전용"
        scope["locked_regions"] = [r for r in (cfg.get("regions") or []) if r not in allowed]
    return scope


def _active_users():
    try:
        users = base.read_store().get("users") or []
    except Exception:
        return []
    out = []
    for u in users:
        if not isinstance(u, dict) or not u.get("active", True):
            continue
        out.append({
            "user_id": u.get("user_id"),
            "display_name": u.get("display_name"),
            "permission_type": u.get("permission_type"),
        })
    out.sort(key=lambda x: str(x.get("display_name") or ""))
    return out


# ---------- 화면 ----------

@app.get("/narrative")
def narrative_page():
    if not _current_user():
        return redirect("/")
    try:
        html = TEMPLATE.read_text(encoding="utf-8")
    except Exception as exc:
        return make_response("문안 생성기 화면을 불러오지 못했습니다 (" + type(exc).__name__ + ")", 500)
    html = html.replace("__CONFIG_JSON__", json.dumps(_config(), ensure_ascii=False))
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    resp.headers["X-MedPark-Narrative"] = "narrative-7.0"
    return resp


@app.get("/narrative-users")
def narrative_users():
    user = _current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({
        "me": {
            "user_id": user.get("user_id"),
            "display_name": user.get("display_name"),
            "permission_type": user.get("permission_type"),
        },
        "scope": _my_scope(user),
        "users": _active_users(),
    })


@app.get("/narrative-data")
def narrative_data():
    if not _current_user():
        return jsonify({"error": "unauthorized"}), 401
    requested = (request.args.get("periods") or "").split(",")
    data, bad = {}, []
    for raw in requested[:MAX_PERIODS]:
        period = raw.strip()
        matched = PERIOD_RE.match(period)
        if not matched:
            if period:
                bad.append(period)
            continue
        year, month = int(matched.group(1)), int(matched.group(2))
        if month < 1 or month > 12 or year < 2000 or year > 2100:
            bad.append(period)
            continue
        data[period] = _period_rows(year, month)
    return jsonify({"data": data, "invalid": bad})


@app.get("/narrative-round")
def narrative_round_get():
    user = _current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    key = (request.args.get("key") or "").strip()
    if not KEY_RE.match(key):
        return jsonify({"error": "bad_key"}), 400
    return jsonify({"key": key, "record": STORE.get(key), "scope": _my_scope(user)})


@app.post("/narrative-round")
def narrative_round_save():
    user = _current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    scope = _my_scope(user)
    if scope.get("readonly"):
        return jsonify({"error": "readonly", "scope": scope}), 403
    payload = request.get_json(silent=True) or {}
    key = (payload.get("key") or "").strip()
    if not KEY_RE.match(key):
        return jsonify({"error": "bad_key"}), 400
    patch = {}
    for field in ("numbers", "factors", "lists", "narratives", "meta"):
        if field in payload:
            patch[field] = payload[field]
    if not patch:
        return jsonify({"error": "empty_patch"}), 400
    try:
        record = STORE.save(key, patch, user, note=str(payload.get("note") or "")[:200])
    except Exception as exc:
        return jsonify({"error": type(exc).__name__ + ": " + str(exc)[:200]}), 500
    return jsonify({"ok": True, "key": key, "record": record})


@app.get("/narrative-round-delete")
def narrative_round_delete():
    user = _current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    if _my_scope(user).get("readonly"):
        return jsonify({"error": "readonly"}), 403
    key = (request.args.get("key") or "").strip()
    if not KEY_RE.match(key):
        return jsonify({"error": "bad_key", "keys": STORE.list_keys()}), 400
    payload = STORE._read()
    rounds = payload.get("rounds") or {}
    record = rounds.get(key)
    if record is None:
        return jsonify({"deleted": False, "reason": "not_found", "key": key, "keys": sorted(rounds.keys())}), 404
    if request.args.get("confirm") != "yes":
        return jsonify({
            "deleted": False, "reason": "confirm_required", "key": key,
            "updated_at": record.get("updated_at"),
            "hint": "주소 끝에 &confirm=yes 를 붙이면 지웁니다.",
        }), 409
    rounds.pop(key, None)
    try:
        STORE._write(payload)
    except Exception as exc:
        return jsonify({"error": type(exc).__name__ + ": " + str(exc)[:200]}), 500
    return jsonify({"deleted": True, "key": key, "remaining": sorted(rounds.keys())})


@app.get("/narrative-rounds")
def narrative_rounds():
    if not _current_user():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"rounds": STORE.summaries(), "keys": STORE.list_keys()})


@app.get("/narrative-provisional")
def narrative_provisional():
    """보존된 잠정마감 기록. 잘못 잡혔을 때 확인용."""
    if not _current_user():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"path": str(PROV_PATH), "exists": PROV_PATH.exists(), "data": _read_prov()})


@app.get("/narrative-health")
def narrative_health():
    cfg = _config()
    user = _current_user()
    return jsonify({
        "template_exists": TEMPLATE.exists(),
        "config_loaded": bool(cfg.get("meetings")),
        "editable_regions": cfg.get("editable_regions"),
        "meetings": cfg.get("order"),
        "round_keys": STORE.list_keys(),
        "provisional_periods": sorted(_read_prov().keys()),
        "my_scope": _my_scope(user) if user else None,
    })


@app.after_request
def narrative_link(resp):
    try:
        if request.path not in REPORT_PATHS:
            return resp
        if request.args.get("capture") == "1":
            return resp
        if resp.direct_passthrough or resp.status_code != 200:
            return resp
        ctype = str(resp.headers.get("Content-Type") or "")
        if "text/html" not in ctype.lower():
            return resp
        body = resp.get_data(as_text=True)
        if LINK_ID in body or "</body>" not in body:
            return resp
        link = (
            "<a id='" + LINK_ID + "' href='/narrative' style=\""
            "position:fixed;right:14px;top:14px;z-index:99998;background:#16202B;color:#fff;"
            "padding:10px 15px;border-radius:6px;font-size:15px;font-weight:700;"
            "text-decoration:none;font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
            "box-shadow:0 2px 8px rgba(0,0,0,.2)\">회의 문안 생성기</a>"
        )
        resp.set_data(body.replace("</body>", link + "</body>", 1))
    except Exception:
        pass
    return resp
