"""회의 문안 생성기 페이지와 API.

값은 성과리포트가 이미 들고 있는 데이터에서 가져오고,
회의별 입력(변동 요인·계획·백업플랜)과 완성 문안은 회차별로 서버에 남긴다.

리포트는 "그 달의 가마감·마감"을 다음 달 행의 prev_* 필드로 들고 있다.
(8월 가마감 = 9월 리포트의 prev_preclose)
그래서 한 달치를 만들 때 당월과 익월 리포트를 함께 읽어 정규화한다.

회의 구성·입력 항목·권한 범위는 narrative_config.py에서만 고친다.
"""

import json
import re
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
    return out


def _current_user():
    try:
        return base.current_user()
    except Exception:
        return None


def _my_scope(user):
    return store_mod.scope_of(user, _config().get("scopes") or {})


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
    resp.headers["X-MedPark-Narrative"] = "narrative-6.0"
    return resp


@app.get("/narrative-users")
def narrative_users():
    user = _current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    scope = _my_scope(user)
    return jsonify({
        "me": {
            "user_id": user.get("user_id"),
            "display_name": user.get("display_name"),
            "permission_type": user.get("permission_type"),
        },
        "scope": scope,
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


@app.get("/narrative-rounds")
def narrative_rounds():
    if not _current_user():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"rounds": STORE.summaries()})


@app.get("/narrative-fields")
def narrative_fields():
    if not _current_user():
        return jsonify({"error": "unauthorized"}), 401
    try:
        year = int(request.args.get("year", 2026))
        month = int(request.args.get("month", 9))
    except Exception:
        year, month = 2026, 9
    report = _build(year, month)
    if report is None:
        return jsonify({"error": "report_build_failed"}), 500
    detail = None
    for row in report.get("rows", []) or []:
        if isinstance(row, dict) and not row.get("is_total"):
            detail = row
            break
    numeric = {}
    if detail:
        for key, value in detail.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric[key] = value
    return jsonify({
        "period": "%04d-%02d" % (year, month),
        "all_keys": sorted(detail.keys()) if detail else [],
        "numeric_fields": numeric,
    })


@app.get("/narrative-health")
def narrative_health():
    cfg = _config()
    sample = _period_rows(2026, 8)
    filled = {}
    for businesses in sample.values():
        for values in businesses.values():
            for field, value in values.items():
                if value is not None:
                    filled[field] = filled.get(field, 0) + 1
    user = _current_user()
    return jsonify({
        "template_exists": TEMPLATE.exists(),
        "template_bytes": TEMPLATE.stat().st_size if TEMPLATE.exists() else 0,
        "config_loaded": bool(cfg.get("meetings")),
        "meetings": cfg.get("order"),
        "store_path": str(STORE.path),
        "store_exists": STORE.path.exists(),
        "round_keys": STORE.list_keys(),
        "my_scope": _my_scope(user) if user else None,
        "sample_period": "2026-08",
        "filled_counts": filled,
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
