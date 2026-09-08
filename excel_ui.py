import html
from flask import flash, redirect, request

import production_entry as base

app = base.app
BUSINESSES = base.BUSINESSES
REGIONS = base.REGIONS
KINDS = base.KINDS
STAGES = base.STAGES
COUNT_STATUSES = base.COUNT_STATUSES

PERMISSION_LABELS = {
    "admin": "전체 관리",
    "domestic_all": "국내 전체",
    "dental_domestic": "국내 덴탈",
    "overseas_all": "해외 전체",
    "aesthetics_all": "에스테틱 전체",
}


def esc(value):
    return html.escape(str(value if value is not None else ""))


def money_m(value, blank="-"):
    if value is None:
        return blank
    try:
        n = float(value) / 1_000_000
    except Exception:
        return blank
    if abs(n) < 0.05:
        return "0"
    if abs(n - round(n)) < 0.05:
        return f"{int(round(n)):,}"
    return f"{n:,.1f}"


def pct(value, blank="-"):
    if value is None:
        return blank
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return blank


def can_manage(user):
    return bool(user and (user.get("role") == "admin" or user.get("permission_type") == "admin" or user.get("manage_all")))


def actual_value(data, year, month, business, region, kind):
    value = data.get("actuals", {}).get(base.actual_key(year, month, business, region, kind))
    return base.int_value(value) if value is not None else None


def snapshot(data, year, month, stage, business, region, kind):
    rows = base.matching_entries(data, year, month, stage, business, region, kind)
    if not rows:
        return {"has": False, "confirmed": None, "forecast": None, "carryover": 0}
    confirmed = sum(base.int_value(e.get("amount")) for e in rows if e.get("status") == "확정")
    forecast = sum(base.int_value(e.get("amount")) for e in rows if e.get("status") in COUNT_STATUSES)
    carryover = sum(base.int_value(e.get("amount")) for e in rows if e.get("status") == "이월")
    return {"has": True, "confirmed": confirmed, "forecast": forecast, "carryover": carryover}


def best_month(data, year, month, business, region, kind):
    actual = actual_value(data, year, month, business, region, kind)
    if actual is not None:
        return actual
    for stage in ["마감", "3차", "2차", "1차"]:
        snap = snapshot(data, year, month, stage, business, region, kind)
        if snap["has"]:
            return snap["forecast"] or 0
    return 0


def row_metrics(data, year, month, business, region, kind):
    hist = {m: actual_value(data, year, m, business, region, kind) or 0 for m in range(1, month)}
    ytd = sum(hist.values())
    avg = ytd / max(month - 1, 1)
    prev_ytd = sum(actual_value(data, year - 1, m, business, region, kind) or 0 for m in range(1, month))
    growth = ((ytd - prev_ytd) / prev_ytd) if prev_ytd else None
    current = {stage: snapshot(data, year, month, stage, business, region, kind) for stage in STAGES}
    prev_month, prev_year = ((12, year - 1) if month == 1 else (month - 1, year))
    next_month, next_year = ((1, year + 1) if month == 12 else (month + 1, year))
    prev_first = snapshot(data, prev_year, prev_month, "1차", business, region, kind)
    prev_preclose = snapshot(data, prev_year, prev_month, "3차", business, region, kind)
    prev_close = snapshot(data, prev_year, prev_month, "마감", business, region, kind)
    next_first = snapshot(data, next_year, next_month, "1차", business, region, kind)
    close_actual = actual_value(data, year, month, business, region, kind)
    close_snap = current["마감"]
    close = close_snap["forecast"] if close_snap["has"] else close_actual
    close_has = close_snap["has"] or close_actual is not None
    q = (month - 1) // 3 + 1
    qmonths = list(range((q - 1) * 3 + 1, q * 3 + 1))
    return {
        "business": business, "region": region, "kind": kind, "hist": hist,
        "ytd": ytd, "avg": avg, "prev_ytd": prev_ytd, "growth": growth,
        "prev_first": prev_first["forecast"] if prev_first["has"] else None,
        "prev_preclose": prev_preclose["forecast"] if prev_preclose["has"] else None,
        "prev_close": prev_close["forecast"] if prev_close["has"] else actual_value(data, prev_year, prev_month, business, region, kind),
        "first": current["1차"]["forecast"] if current["1차"]["has"] else None,
        "second": current["2차"]["forecast"] if current["2차"]["has"] else None,
        "third_confirmed": current["3차"]["confirmed"] if current["3차"]["has"] else None,
        "third_forecast": current["3차"]["forecast"] if current["3차"]["has"] else None,
        "close": close, "close_has": close_has,
        "next_first": next_first["forecast"] if next_first["has"] else None,
        "carryover": current["3차"]["carryover"] if current["3차"]["has"] else 0,
        "qproj": sum(best_month(data, year, m, business, region, kind) for m in qmonths),
        "october": best_month(data, year, 10, business, region, kind),
        "november": best_month(data, year, 11, business, region, kind),
        "december": best_month(data, year, 12, business, region, kind),
        "q4proj": sum(best_month(data, year, m, business, region, kind) for m in [10, 11, 12]),
        "second_half": sum(best_month(data, year, m, business, region, kind) for m in range(7, 13)),
    }


def sum_rows(rows, label, business=None):
    def sum_nullable(key):
        values = [r.get(key) for r in rows if r.get(key) is not None]
        return sum(values) if values else None
    ytd = sum(r.get("ytd", 0) for r in rows)
    prev = sum(r.get("prev_ytd", 0) for r in rows)
    return {
        "is_total": True, "is_grand": label.endswith("전체"), "label": label,
        "business": business, "region": "[소계]", "kind": "",
        "hist": {m: sum(r.get("hist", {}).get(m, 0) for r in rows) for m in range(1, 13)},
        "ytd": ytd, "avg": sum(r.get("avg", 0) for r in rows), "prev_ytd": prev,
        "growth": ((ytd - prev) / prev) if prev else None,
        "prev_first": sum_nullable("prev_first"), "prev_preclose": sum_nullable("prev_preclose"),
        "prev_close": sum_nullable("prev_close"), "first": sum_nullable("first"),
        "second": sum_nullable("second"), "third_confirmed": sum_nullable("third_confirmed"),
        "third_forecast": sum_nullable("third_forecast"), "close": sum_nullable("close"),
        "close_has": all(r.get("close_has") for r in rows), "next_first": sum_nullable("next_first"),
        "carryover": sum(r.get("carryover", 0) for r in rows),
        "qproj": sum(r.get("qproj", 0) for r in rows), "october": sum(r.get("october", 0) for r in rows),
        "november": sum(r.get("november", 0) for r in rows), "december": sum(r.get("december", 0) for r in rows),
        "q4proj": sum(r.get("q4proj", 0) for r in rows), "second_half": sum(r.get("second_half", 0) for r in rows),
    }


def report_data(year, month):
    data = base.read_store()
    details, display = [], []
    for business in BUSINESSES:
        group = []
        for region in REGIONS:
            for kind in KINDS:
                row = row_metrics(data, year, month, business, region, kind)
                details.append(row); group.append(row); display.append(row)
        display.append(sum_rows(group, f"{business} 소계", business))
    grand = sum_rows(details, f"{year}년 전체")
    display.append(grand)
    comments = data.get("comments", {}).get(f"{year}-{month:02d}", {})
    if not isinstance(comments, dict):
        comments = {}
    comments.setdefault("top", ""); comments.setdefault("bottom", "")
    parts = []
    for business in BUSINESSES:
        for region in REGIONS:
            pr = [x for x in details if x["business"] == business and x["region"] == region]
            parts.append({"name": f"{business} {region}", "done": bool(pr) and all(x["close_has"] for x in pr)})
    close_done = sum(1 for p in parts if p["done"])
    third_total = grand.get("third_forecast")
    close_total = grand.get("close") if grand.get("close_has") else None
    diff = close_total - third_total if close_total is not None and third_total is not None else None
    error_rate = abs(diff) / third_total if diff is not None and third_total else None
    return {
        "year": year, "month": month, "rows": display, "comments": comments, "parts": parts,
        "close_done": close_done, "third_total": third_total, "diff": diff, "error_rate": error_rate,
        "prev_month": 12 if month == 1 else month - 1, "next_month": 1 if month == 12 else month + 1,
        "quarter": (month - 1) // 3 + 1,
    }


def css():
    return """
*{box-sizing:border-box}body{margin:0;background:#f2f5f9;color:#172235;font-family:Arial,'Malgun Gothic',sans-serif}a{color:#164a80}.topbar{min-height:64px;background:#10375f;color:#fff;display:flex;align-items:center;padding:0 22px;gap:22px}.brand{font-weight:800;font-size:17px;white-space:nowrap}.brand span{font-weight:500;font-size:14px;color:#d9e5f1;margin-left:10px}.nav{display:flex;align-items:center;gap:2px;flex:1}.nav a{color:#dce8f4;text-decoration:none;padding:21px 13px 18px;font-weight:700;border-bottom:3px solid transparent;white-space:nowrap}.nav a.active{color:#fff;border-bottom-color:#fff}.user{display:flex;align-items:center;gap:10px;font-size:13px;white-space:nowrap}.user b{font-size:15px}.user a{color:#dce8f4}.user form{margin:0}.user button{background:#fff;border:0;border-radius:6px;color:#173a61;padding:8px 11px;cursor:pointer}.page{padding:16px 12px 40px}.toolbar{background:#fff;border:1px solid #d7e1eb;border-radius:9px;padding:12px 13px;display:flex;justify-content:space-between;align-items:flex-end;gap:12px;margin-bottom:14px}.toolbar form{display:flex;gap:9px;align-items:flex-end}.toolbar label{font-size:11px;font-weight:800;color:#4b5d72}.toolbar select{display:block;margin-top:4px;padding:8px 10px;border:1px solid #cbd7e3;border-radius:7px;background:#fff;min-width:88px}.btn{display:inline-block;border:1px solid #c9d6e3;border-radius:7px;padding:8px 11px;background:#fff;color:#173e6b;text-decoration:none;font-weight:700;cursor:pointer}.btn.primary{background:#164a80;border-color:#164a80;color:#fff}.toolbar-links{display:flex;gap:7px;flex-wrap:wrap}.meeting .eyebrow{font-size:14px;margin:7px 0 13px}.meeting h1{font-size:31px;margin:0 0 17px;letter-spacing:-.02em}.meta{font-size:14px;margin-bottom:17px}.summary{font-size:13px;line-height:1.42;margin-bottom:6px}.chips{display:flex;gap:6px;flex-wrap:wrap;margin:7px 0 11px}.chip{border:1px solid #e0c6c3;background:#fff8f5;color:#8b5651;border-radius:999px;padding:4px 9px;font-size:10.5px}.chip.done{border-color:#b8d8c1;background:#f2faf4;color:#326d48}.note{background:#fff;border:1px solid #d9e3ed;border-left:4px solid #164a80;border-radius:5px;padding:9px 11px;margin:9px 0 11px;font-size:12px;line-height:1.5}.table-wrap{overflow:auto;border:1px solid #b8c8d8;background:#fff}.report{border-collapse:collapse;min-width:1680px;width:100%;font-size:10.4px;white-space:nowrap}.report th,.report td{border-right:1px solid #cbd6e1;border-bottom:1px solid #d8e1ea;padding:5.5px 6px;text-align:right;vertical-align:middle}.report th{text-align:center;font-weight:800}.report thead tr:first-child th{background:#184b81;color:#fff;border-color:#47709a}.report thead tr:nth-child(2) th{background:#dce8f3;color:#213b55}.report td:nth-child(1),.report td:nth-child(2),.report td:nth-child(3){text-align:center}.report tbody tr:nth-child(even):not(.subtotal):not(.grand){background:#fafbfd}.report .subtotal td{background:#eef3f8;font-weight:800;border-top:2px solid #a8bbce}.report .grand td{background:#dbe7f2;font-weight:900;border-top:2px solid #6d8eae}.c1{background:#eff9f7}.c2{background:#f7fbff}.c3c{background:#eef8f3}.c3f{background:#fff8df}.cc{background:#f3f3f3}.caption{font-size:10.5px;color:#415268;margin:7px 0 16px}.writer{margin-top:3px}.writer .eyebrow2{font-size:11px;color:#617285;margin:0 0 7px}.writer h2{font-size:24px;margin:0 0 7px}.writer p{font-size:12px;color:#667789}.writer-grid{display:grid;grid-template-columns:1fr 1fr;gap:11px}.writer label{font-size:12px;font-weight:800}.writer textarea{width:100%;min-height:105px;margin-top:5px;border:1px solid #ccd8e4;border-radius:7px;padding:9px;font-family:inherit}.flash{background:#eef5ff;border:1px solid #cfe0f3;border-radius:7px;padding:9px 11px;margin-bottom:9px}.capture .topbar,.capture .toolbar,.capture .writer{display:none}.capture .page{padding:4px;background:#fff}@media(max-width:900px){.topbar{height:auto;align-items:flex-start;flex-wrap:wrap;padding:11px 12px;gap:7px}.nav{order:3;width:100%;overflow:auto}.nav a{padding:9px 9px}.user{margin-left:auto}.toolbar{align-items:flex-start;flex-direction:column}.meeting h1{font-size:27px}.writer-grid{grid-template-columns:1fr}.page{padding:11px 7px}}
"""


def topbar(user):
    name = esc(user.get("display_name") or user.get("user_id"))
    perm = esc(PERMISSION_LABELS.get(user.get("permission_type", ""), "전체 관리" if can_manage(user) else "-"))
    extra = "<a href='/users'>사용자</a>" if can_manage(user) else ""
    return f"""<header class='topbar'><div class='brand'>MEDPARK <span>실적회의 통합관리</span></div><nav class='nav'><a class='active' href='/'>취합본</a><a href='/input'>실적입력</a><a href='/#report-writer'>실적자료 작성</a></nav><div class='user'><span><b>{name}</b> · {perm}</span>{extra}<a href='/password'>비밀번호</a><form method='post' action='/logout'><button>로그아웃</button></form></div></header>"""


def render_report(report, user, capture=False):
    y, m = report["year"], report["month"]
    pm, nm, q = report["prev_month"], report["next_month"], report["quarter"]
    year_opts = "".join(f"<option value='{v}' {'selected' if v==y else ''}>{v}</option>" for v in [2025,2026,2027])
    month_opts = "".join(f"<option value='{v}' {'selected' if v==m else ''}>{v}월</option>" for v in range(1,13))
    toolbar = f"""<section class='toolbar'><form method='get'><label>년도<select name='year'>{year_opts}</select></label><label>기준월<select name='month'>{month_opts}</select></label><button class='btn'>조회</button></form><div class='toolbar-links'><a class='btn primary' href='/input?year={y}&month={m}&stage=2%EC%B0%A8'>실적 입력</a><a class='btn' href='#report-writer'>실적자료 작성</a><a class='btn' target='_blank' href='/?year={y}&month={m}&capture=1'>PPT 캡처 화면</a></div></section>"""
    chips = "".join(f"<span class='chip {'done' if p['done'] else ''}'>{esc(p['name'])} · {'마감완료' if p['done'] else '마감미입력'}</span>" for p in report["parts"])
    comments = report["comments"]
    topnote = f"<div class='note'><b>전체 핵심 요약</b><br>{esc(comments.get('top')).replace(chr(10),'<br>')}</div>" if comments.get("top") else ""
    hist_headers = "".join(f"<th>{mm}월</th>" for mm in range(1,m))
    body_rows = []
    for r in report["rows"]:
        cls = "grand" if r.get("is_grand") else ("subtotal" if r.get("is_total") else "")
        prefix = f"<td colspan='3'>{esc(r.get('label'))}</td>" if r.get("is_total") else f"<td>{esc(r.get('business'))}</td><td>{esc(r.get('region'))}</td><td>{esc(r.get('kind'))}</td>"
        hist = "".join(f"<td>{money_m(r.get('hist',{}).get(mm,0))}</td>" for mm in range(1,m))
        vals = f"<td>{money_m(r.get('ytd'))}</td><td>{money_m(r.get('avg'))}</td><td>{money_m(r.get('prev_ytd'))}</td><td>{pct(r.get('growth'))}</td>{hist}<td>{money_m(r.get('prev_first'))}</td><td>{money_m(r.get('prev_preclose'))}</td><td>{money_m(r.get('prev_close'))}</td><td class='c1'>{money_m(r.get('first'))}</td><td class='c2'>{money_m(r.get('second'))}</td><td class='c3c'>{money_m(r.get('third_confirmed'))}</td><td class='c3f'>{money_m(r.get('third_forecast'))}</td><td class='cc'>{money_m(r.get('close'))}</td><td>{money_m(r.get('next_first'))}</td><td>{money_m(r.get('qproj'))}</td><td>{money_m(r.get('october'))}</td><td>{money_m(r.get('november'))}</td><td>{money_m(r.get('december'))}</td><td>{money_m(r.get('q4proj'))}</td><td>{money_m(r.get('second_half'))}</td>"
        body_rows.append(f"<tr class='{cls}'>{prefix}{vals}</tr>")
    writer = ""
    if can_manage(user):
        writer = f"""<section class='writer' id='report-writer'><p class='eyebrow2'>PERFORMANCE REPORT WRITER</p><h2>실적자료 작성</h2><p>숫자는 자동 취합됩니다. 글만 입력하면 취합본과 PPT 캡처 화면에 바로 반영됩니다.</p><form method='post' action='/comments'><input type='hidden' name='year' value='{y}'><input type='hidden' name='month' value='{m}'><div class='writer-grid'><label>전체 핵심 요약<textarea name='top'>{esc(comments.get('top'))}</textarea></label><label>전체 이월 · 리스크 · 후속조치<textarea name='bottom'>{esc(comments.get('bottom'))}</textarea></label></div><p><button class='btn primary'>실적자료 저장</button></p></form></section>"""
    bottomnote = f"<div class='note'><b>전체 이월 · 리스크 · 후속조치</b><br>{esc(comments.get('bottom')).replace(chr(10),'<br>')}</div>" if comments.get("bottom") else ""
    top = "" if capture else topbar(user)
    tbar = "" if capture else toolbar
    cls = "capture" if capture else ""
    return f"""<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{y}년 {m}월 실적회의 · MEDPARK</title><style>{css()}</style></head><body class='{cls}'>{top}<main class='page'>{tbar}<section class='meeting'><p class='eyebrow'>SALES PERFORMANCE MEETING</p><h1>{y}년 {m}월 실적회의</h1><p class='meta'><b>단위: 백만원</b> · 저장 원데이터는 원 단위 · 1차 → 2차 → 3차 가마감 → 실제 마감 이력 보존</p><div class='summary'><b>MEDPARK</b><br>3차 가마감 예상 <b>{money_m(report.get('third_total'))}</b><br>실제 마감입력 진행중 <b>{report['close_done']}</b> / 6 파트 완료<br>가마감 대비 차이 <b>{money_m(report.get('diff')) if report.get('diff') is not None else '-'}</b><br>오차율 <b>{pct(report.get('error_rate'))}</b></div><div class='chips'>{chips}</div>{topnote}</section><div class='table-wrap'><table class='report'><thead><tr><th rowspan='2'>사업부</th><th rowspan='2'>구분</th><th rowspan='2'>기존/신규</th><th colspan='2'>누계</th><th rowspan='2'>전년 누계</th><th rowspan='2'>증감율</th><th colspan='{max(m-1,0)}'>월 실적</th><th colspan='3'>전월 비교</th><th colspan='5'>{m}월</th><th rowspan='2'>{nm}월 1차</th><th rowspan='2'>{q}Q 전망</th><th rowspan='2'>10월</th><th rowspan='2'>11월</th><th rowspan='2'>12월</th><th rowspan='2'>4Q 전망</th><th rowspan='2'>하반기 전망</th></tr><tr><th>합계</th><th>평균</th>{hist_headers}<th>{pm}월 1차</th><th>{pm}월 가마감</th><th>{pm}월 마감</th><th>1차 예상</th><th>2차 예상</th><th>3차 확정</th><th>3차 예상</th><th>실제 마감</th></tr></thead><tbody>{''.join(body_rows)}</tbody></table></div><div class='caption'>PERFORMANCE REPORT WRITER</div>{bottomnote}{writer}</main></body></html>"""


@base.login_required
def excel_dashboard():
    try:
        year = int(request.args.get("year", 2026)); month = int(request.args.get("month", 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9
    return render_report(report_data(year, month), base.current_user(), request.args.get("capture") == "1")


app.view_functions["dashboard"] = excel_dashboard


@base.login_required
def comments_save():
    user = base.current_user()
    if not can_manage(user):
        return "forbidden", 403
    try:
        year = int(request.form.get("year", 2026)); month = int(request.form.get("month", 9))
    except Exception:
        year, month = 2026, 9
    data = base.read_store()
    root = data.setdefault("comments", {})
    bucket = root.setdefault(f"{year}-{month:02d}", {})
    if not isinstance(bucket, dict):
        bucket = {}; root[f"{year}-{month:02d}"] = bucket
    bucket["top"] = request.form.get("top", "").strip()
    bucket["bottom"] = request.form.get("bottom", "").strip()
    bucket["updated_by"] = user.get("display_name", "")
    bucket["updated_at"] = base.now_text()
    base.write_store(data)
    flash("실적자료를 저장했습니다.")
    return redirect(f"/?year={year}&month={month}#report-writer")


if "comments_save" not in app.view_functions:
    app.add_url_rule("/comments", endpoint="comments_save", view_func=comments_save, methods=["POST"])


def excel_health():
    data = base.read_store()
    return {
        "status": "ok", "runtime": "excel-layout-v1",
        "initialized": bool(data.get("meta", {}).get("initialized")),
        "users": len(data.get("users", [])), "entries": len(data.get("entries", [])),
        "actuals": len(data.get("actuals", {})), "seed_available": bool(base.os.environ.get("AUTO_SEED_GZ", "").strip()),
    }


app.view_functions["health"] = excel_health
