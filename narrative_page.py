"""회의 문안 생성기 페이지.

성과리포트 안에 /narrative 화면을 추가한다.
국내 1차·2차 예상과 잠정마감은 SalesOps 스냅샷에서 사업분야별로 채워 넣는다.
해외와 가마감·확정마감은 화면에서 직접 입력한다.
"""

import json
import re
from pathlib import Path

import browser_bridge as prev
import root_live_fetch as live
from flask import make_response, redirect, request

app = prev.app
base = live.base

TEMPLATE = Path(__file__).with_name("narrative.html")
SNAPSHOT_DIR = Path(base.DATA_DIR)
SNAPSHOT_RE = re.compile(r"salesops_root_live_(\d{4})_(\d{2})\.json$")
LINK_ID = "mp-narrative-link"
REPORT_PATHS = ("/", "/performance-report")
FIELDS = ("first", "second", "close")


def _domestic_by_business(index):
    """국내 행을 사업분야별로 합산한다. 신규·기존은 합친다."""
    out = {}
    for key, row in index.items():
        if not isinstance(row, dict) or len(key) != 3:
            continue
        business, region = key[0], key[1]
        if region != "국내":
            continue
        bucket = out.setdefault(business, {f: None for f in FIELDS})
        for field in FIELDS:
            value = row.get(field)
            if value is None:
                continue
            bucket[field] = value if bucket[field] is None else bucket[field] + value
    return out


def _seed():
    """스냅샷에 있는 모든 월의 국내 사업분야별 값을 만든다.

    형태: {"YYYY-MM": {"덴탈": {"first":..,"second":..,"close":..}, ...}}
    """
    seed = {}
    try:
        for path in SNAPSHOT_DIR.glob("salesops_root_live_*.json"):
            matched = SNAPSHOT_RE.search(path.name)
            if not matched:
                continue
            year, month = int(matched.group(1)), int(matched.group(2))
            index, _saved = live._load_snapshot(year, month)
            if not index:
                continue
            by_business = _domestic_by_business(index)
            if by_business:
                seed["%04d-%02d" % (year, month)] = by_business
    except Exception:
        pass
    return seed


@app.get("/narrative")
def narrative_page():
    try:
        user = base.current_user()
    except Exception:
        user = None
    if not user:
        return redirect("/")
    try:
        html = TEMPLATE.read_text(encoding="utf-8")
    except Exception as exc:
        return make_response("문안 생성기 화면을 불러오지 못했습니다 (" + type(exc).__name__ + ")", 500)
    html = html.replace("__SEED_JSON__", json.dumps(_seed(), ensure_ascii=False))
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    resp.headers["X-MedPark-Narrative"] = "narrative-2.0"
    return resp


@app.get("/narrative-health")
def narrative_health():
    seed = _seed()
    shape = {}
    for period, businesses in seed.items():
        shape[period] = sorted(businesses.keys())
    return {
        "template_exists": TEMPLATE.exists(),
        "template_bytes": TEMPLATE.stat().st_size if TEMPLATE.exists() else 0,
        "seed_months": sorted(seed.keys()),
        "seed_businesses": shape,
        "seed": seed,
    }


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
