"""회의 문안 생성기 페이지.

성과리포트 안에 /narrative 화면을 추가한다.
값은 성과리포트가 이미 들고 있는 데이터에서 그대로 가져온다.
국내는 SalesOps 연동값, 해외는 저장된 마감·FCST 값이 대상이며
지역·사업분야별로 나눠 채운다.
"""

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
SEED_FIELDS = ("first", "second", "third_forecast", "third_confirmed", "close", "prev_close")
MAX_PERIODS = 6


def _period_rows(year, month):
    """해당 월의 지역·사업분야별 값을 만든다.

    형태: {"국내": {"덴탈": {"first":..,"second":..,"close":..}, ...}, "해외": {...}}
    신규·기존은 합친다.
    """
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
        bucket = out.setdefault(region, {}).setdefault(business, {f: None for f in SEED_FIELDS})
        for field in SEED_FIELDS:
            value = row.get(field)
            if value is None:
                continue
            try:
                value = int(round(float(value)))
            except Exception:
                continue
            bucket[field] = value if bucket[field] is None else bucket[field] + value
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
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    resp.headers["X-MedPark-Narrative"] = "narrative-3.0"
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


@app.get("/narrative-health")
def narrative_health():
    sample = _period_rows(2026, 8)
    shape = {}
    for region, businesses in sample.items():
        shape[region] = sorted(businesses.keys())
    return jsonify({
        "template_exists": TEMPLATE.exists(),
        "template_bytes": TEMPLATE.stat().st_size if TEMPLATE.exists() else 0,
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
