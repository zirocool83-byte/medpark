"""회의 문안 생성기 페이지.

성과리포트 안에 /narrative 화면을 추가한다.
값은 성과리포트가 이미 들고 있는 데이터에서 그대로 가져온다.

핵심: 리포트는 "그 달의 가마감·마감"을 다음 달 행의 prev_* 필드로 들고 있다.
      (8월 가마감은 9월 리포트의 prev_preclose)
      그래서 한 달치를 만들 때 당월 리포트와 익월 리포트를 함께 읽어
      그 달의 완전한 값으로 정규화한다.

회의 구성과 열 이름은 narrative_config.py에서만 고친다.
"""

import json
import re
from pathlib import Path

import browser_bridge as prev
import root_live_fetch as live
from flask import jsonify, make_response, redirect, request

app = prev.app
base = live.base

TEMPLATE = Path(__file__).with_name("narrative.html")
LINK_ID = "mp-narrative-link"
REPORT_PATHS = ("/", "/performance-report")
PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")
MAX_PERIODS = 4

# 당월 리포트에서 그대로 쓰는 필드
OWN_FIELDS = ("first", "second", "third_confirmed", "third_forecast", "close", "carryover")
# 익월 리포트의 prev_* → 이 달의 확정된 값. 가마감은 이 경로로만 얻는다.
PREV_MAP = {"prev_first": "first", "prev_preclose": "preclose", "prev_close": "close"}

FALLBACK_CONFIG = {
    "order": ["pre", "r1", "r2"],
    "default_meeting": "r1",
    "meetings": {
        "pre": {
            "label": "가마감 회의", "when": "25일경",
            "close": {"off": 0, "cols": ["3차 예상", "가마감"], "cur": 2, "word": "가마감"},
            "fcst": {"off": 1, "cols": ["사업계획", "1차 예상"], "cur": 2},
            "tol": False,
        },
        "r1": {
            "label": "1차 실적회의", "when": "5일경",
            "close": {"off": -1, "cols": ["가마감", "마감(잠정)"], "cur": 2, "word": "잠정마감"},
            "fcst": {"off": 0, "cols": ["1차 예상", "2차 예상"], "cur": 2},
            "tol": False,
        },
        "r2": {
            "label": "2차 실적회의", "when": "15일경",
            "close": {"off": -1, "cols": ["마감(잠정)", "마감(확정)"], "cur": 2, "word": "확정마감"},
            "fcst": {"off": 0, "cols": ["1차 예상", "2차 예상", "3차 예상"], "cur": 3},
            "tol": True,
        },
    },
    "field_of": {
        "1차 예상": "first",
        "2차 예상": "second",
        "3차 예상": "third_forecast",
        "3차 확정": "third_confirmed",
        "가마감": "preclose",
        "마감(잠정)": "close",
    },
}


def _config():
    try:
        import narrative_config
        cfg = getattr(narrative_config, "CONFIG", None)
        if isinstance(cfg, dict) and cfg.get("meetings"):
            return cfg
    except Exception:
        pass
    return FALLBACK_CONFIG


def _to_int(value):
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except Exception:
        return None


def _merge(out, report, mapping):
    """report의 detail 행을 지역·사업분야로 합산해 out에 넣는다.

    mapping: {리포트 필드명: 저장할 이름}. 나중에 부른 쪽이 앞의 값을 덮는다.
    """
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
        target = out.setdefault(region, {}).setdefault(business, {})
        target.update(values)


def _build(year, month):
    try:
        return live._build_report(year, month)
    except Exception:
        return None


def _period_rows(year, month):
    """해당 월을 자기완결적인 한 달치로 만든다."""
    out = {}
    _merge(out, _build(year, month), {f: f for f in OWN_FIELDS})
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    _merge(out, _build(next_year, next_month), PREV_MAP)
    return out


def _require_user():
    try:
        return base.current_user()
    except Exception:
        return None


@app.get("/narrative")
def narrative_page():
    if not _require_user():
        return redirect("/")
    try:
        html = TEMPLATE.read_text(encoding="utf-8")
    except Exception as exc:
        return make_response("문안 생성기 화면을 불러오지 못했습니다 (" + type(exc).__name__ + ")", 500)
    html = html.replace("__CONFIG_JSON__", json.dumps(_config(), ensure_ascii=False))
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    resp.headers["X-MedPark-Narrative"] = "narrative-5.0"
    return resp


@app.get("/narrative-data")
def narrative_data():
    if not _require_user():
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


@app.get("/narrative-fields")
def narrative_fields():
    """리포트 행이 실제로 들고 있는 필드를 확인한다."""
    if not _require_user():
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
        "row_identity": {k: detail.get(k) for k in ("business", "region", "kind")} if detail else None,
        "all_keys": sorted(detail.keys()) if detail else [],
        "numeric_fields": numeric,
    })


@app.get("/narrative-health")
def narrative_health():
    sample = _period_rows(2026, 8)
    cfg = _config()
    filled = {}
    for region, businesses in sample.items():
        for business, values in businesses.items():
            for field, value in values.items():
                if value is not None:
                    filled[field] = filled.get(field, 0) + 1
    return jsonify({
        "template_exists": TEMPLATE.exists(),
        "template_bytes": TEMPLATE.stat().st_size if TEMPLATE.exists() else 0,
        "config_source": "narrative_config.py" if cfg is not FALLBACK_CONFIG else "fallback",
        "meetings": cfg.get("order"),
        "field_of": cfg.get("field_of"),
        "sample_period": "2026-08",
        "filled_counts": filled,
        "sample": sample,
    })


@app.after_request
def narrative_link(resp):
    """성과리포트 화면 우상단에 문안 생성기 링크를 붙인다."""
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
