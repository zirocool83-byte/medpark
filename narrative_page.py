"""회의 문안 생성기 페이지.

성과리포트 안에 /narrative 화면을 추가한다.
값은 성과리포트가 이미 들고 있는 데이터에서 그대로 가져온다.
국내는 SalesOps 연동값, 해외는 저장된 마감·FCST 값이 대상이며
지역·사업분야별로 나눠 채운다.

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
MAX_PERIODS = 6

# 리포트 행에서 실어 나르는 숫자 필드. narrative_config.py의 field_of가 여기서 고른다.
SEED_FIELDS = (
    "first", "second",
    "third_confirmed", "third_forecast",
    "close", "prev_close",
    "prev_first", "prev_second", "prev_third_forecast", "prev_provisional",
    "provisional", "provisional_close", "pre_close", "next_first",
)

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


def _period_rows(year, month):
    """해당 월의 지역·사업분야별 값. 신규·기존은 합친다."""
    try:
        report = live._build_report(year, month)
    except Exception:
        return {}
    out = {}
    for row in report.get("rows", []) or []:
        if not isinstance(row, dict) or row.get("is_total"):
            continue
        region, business = row.get("region"), row.get("business")
        if not region or not business:
            continue
        bucket = out.setdefault(region, {}).setdefault(business, {})
        for field in SEED_FIELDS:
            value = row.get(field)
            if value is None:
                continue
            try:
                value = int(round(float(value)))
            except Exception:
                continue
            bucket[field] = value if bucket.get(field) is None else bucket[field] + value
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
    resp.headers["X-MedPark-Narrative"] = "narrative-4.1"
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
    """리포트 행이 실제로 어떤 필드를 들고 있는지 확인용.

    가마감처럼 화면에는 있는데 필드명을 모르는 열을 매핑할 때 쓴다.
    """
    if not _require_user():
        return jsonify({"error": "unauthorized"}), 401
    try:
        year = int(request.args.get("year", 2026))
        month = int(request.args.get("month", 9))
    except Exception:
        year, month = 2026, 9
    try:
        report = live._build_report(year, month)
    except Exception as exc:
        return jsonify({"error": type(exc).__name__ + ": " + str(exc)[:200]}), 500
    detail = None
    for row in report.get("rows", []) or []:
        if isinstance(row, dict) and not row.get("is_total"):
            detail = row
            break
    numeric = {}
    if detail:
        for k, v in detail.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                numeric[k] = v
    return jsonify({
        "period": "%04d-%02d" % (year, month),
        "row_identity": {k: detail.get(k) for k in ("business", "region", "kind")} if detail else None,
        "all_keys": sorted(detail.keys()) if detail else [],
        "numeric_fields": numeric,
        "report_top_keys": sorted([k for k in report.keys() if k != "rows"]),
    })


@app.get("/narrative-health")
def narrative_health():
    sample = _period_rows(2026, 8)
    shape = {}
    for region, businesses in sample.items():
        shape[region] = sorted(businesses.keys())
    cfg = _config()
    return jsonify({
        "template_exists": TEMPLATE.exists(),
        "template_bytes": TEMPLATE.stat().st_size if TEMPLATE.exists() else 0,
        "config_source": "narrative_config.py" if cfg is not FALLBACK_CONFIG else "fallback",
        "meetings": cfg.get("order"),
        "field_of": cfg.get("field_of"),
        "sample_period": "2026-08",
        "sample_shape": shape,
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
