import excel_ui as ui
from flask import request

app = ui.app
base = ui.base

SALESOPS_BASE = "https://medparkallo-medpark-salesops.mycafe24.ai"

_original_row_metrics = ui.row_metrics
_original_sum_rows = ui.sum_rows
_original_render_report = ui.render_report
_original_topbar = ui.topbar


def row_metrics(data, year, month, business, region, kind):
    row = _original_row_metrics(data, year, month, business, region, kind)
    prev_ytd = sum(ui.actual_value(data, year - 1, m, business, region, kind) or 0 for m in range(1, month))
    ytd = row.get("ytd", 0) or 0
    growth = ((ytd - prev_ytd) / prev_ytd) if prev_ytd else None
    row["prev_ytd"] = prev_ytd
    row["growth"] = growth
    return row


def sum_rows(rows, label, business=None):
    row = _original_sum_rows(rows, label, business)
    ytd = sum(r.get("ytd", 0) or 0 for r in rows)
    prev_ytd = sum(r.get("prev_ytd", 0) or 0 for r in rows)
    growth = ((ytd - prev_ytd) / prev_ytd) if prev_ytd else None
    row["prev_ytd"] = prev_ytd
    row["growth"] = growth
    return row


ui.row_metrics = row_metrics
ui.sum_rows = sum_rows


def topbar(user):
    html = _original_topbar(user)
    links = (
        "<a href='/performance-report'>실적보고서</a>"
        f"<a href='{SALESOPS_BASE}/fcst' target='_blank' rel='noopener'>SalesOps FCST</a>"
        f"<a href='{SALESOPS_BASE}/reports' target='_blank' rel='noopener'>SalesOps 실적보고서</a>"
    )
    return html.replace("</nav>", links + "</nav>", 1)


ui.topbar = topbar


def render_report(report, user, capture=False):
    for row in report.get("rows", []):
        row["prev_same"] = row.get("prev_ytd")
        row["yoy_rate"] = row.get("growth")
    html = _original_render_report(report, user, capture)
    html = html.replace("<th colspan='2'>전년 비교</th>", "<th colspan='2'>누계 비교</th>")
    html = html.replace(
        f"<th>{report['year'] - 1}년 {report['month']}월</th><th>전년 대비</th>",
        f"<th>{report['year'] - 1}년 누계</th><th>누계 증감률</th>",
    )
    toolbar_anchor = "<a class='btn' href='#report-writer'>실적자료 작성</a>"
    extra_links = (
        "<a class='btn' href='/performance-report'>실적보고서</a>"
        f"<a class='btn' target='_blank' rel='noopener' href='{SALESOPS_BASE}/fcst'>SalesOps FCST</a>"
        f"<a class='btn' target='_blank' rel='noopener' href='{SALESOPS_BASE}/reports'>SalesOps 실적보고서</a>"
    )
    html = html.replace(toolbar_anchor, toolbar_anchor + extra_links, 1)
    return html


ui.render_report = render_report


def _scope_stage(data, year, month, stage, business, region, kind):
    snap = ui.snapshot(data, year, month, stage, business, region, kind)
    if not snap.get("has"):
        return None, None, 0
    return snap.get("forecast"), snap.get("confirmed"), snap.get("carryover", 0)


def _previous_close(data, year, month, business, region, kind):
    if month == 1:
        py, pm = year - 1, 12
    else:
        py, pm = year, month - 1
    actual = ui.actual_value(data, py, pm, business, region, kind)
    if actual is not None:
        return actual
    return ui.best_month(data, py, pm, business, region, kind)


def _prior_year_same_month(data, year, month, business, region, kind):
    actual = ui.actual_value(data, year - 1, month, business, region, kind)
    if actual is not None:
        return actual
    return ui.same_month_last_year(data, year, month, business, region, kind)


def _quarter_current(data, year, month, stage, business, region, kind):
    q = (month - 1) // 3 + 1
    months = range((q - 1) * 3 + 1, q * 3 + 1)
    values = []
    for m in months:
        if m < month:
            value = ui.actual_value(data, year, m, business, region, kind)
            if value is None:
                value = ui.best_month(data, year, m, business, region, kind)
        elif m == month:
            value, _, _ = _scope_stage(data, year, month, stage, business, region, kind)
        else:
            value = ui.best_month(data, year, m, business, region, kind)
        if value is not None:
            values.append(value)
    return sum(values) if values else None


def _quarter_prior(data, year, month, business, region, kind):
    q = (month - 1) // 3 + 1
    months = range((q - 1) * 3 + 1, q * 3 + 1)
    values = [ui.actual_value(data, year - 1, m, business, region, kind) for m in months]
    real = [v for v in values if v is not None]
    return sum(real) if real else None


def _sum_nullable(rows, key):
    vals = [r.get(key) for r in rows if r.get(key) is not None]
    return sum(vals) if vals else None


def _rate(current, base_value):
    if current is None or base_value in (None, 0):
        return None
    return (current - base_value) / base_value


@base.login_required
def performance_report_page():
    user = base.current_user()
    try:
        year = int(request.args.get("year", 2026))
        month = int(request.args.get("month", 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9
    stage = request.args.get("stage", "2차")
    if stage not in ui.STAGES:
        stage = "2차"

    data = base.read_store()
    rows = []
    for business in ui.BUSINESSES:
        for region in ui.REGIONS:
            for kind in ui.KINDS:
                current, confirmed, carryover = _scope_stage(data, year, month, stage, business, region, kind)
                prev_close = _previous_close(data, year, month, business, region, kind)
                last_year = _prior_year_same_month(data, year, month, business, region, kind)
                quarter_now = _quarter_current(data, year, month, stage, business, region, kind)
                quarter_prev = _quarter_prior(data, year, month, business, region, kind)
                rows.append({
                    "business": business,
                    "region": region,
                    "kind": kind,
                    "prev_close": prev_close,
                    "current": current,
                    "delta": current - prev_close if current is not None and prev_close is not None else None,
                    "delta_rate": _rate(current, prev_close),
                    "last_year": last_year,
                    "yoy_rate": _rate(current, last_year),
                    "quarter_now": quarter_now,
                    "quarter_prev": quarter_prev,
                    "quarter_yoy": _rate(quarter_now, quarter_prev),
                    "confirmed": confirmed,
                    "carryover": carryover,
                })

    total = {
        "business": "MEDPARK 전체", "region": "", "kind": "",
        "prev_close": _sum_nullable(rows, "prev_close"),
        "current": _sum_nullable(rows, "current"),
        "last_year": _sum_nullable(rows, "last_year"),
        "quarter_now": _sum_nullable(rows, "quarter_now"),
        "quarter_prev": _sum_nullable(rows, "quarter_prev"),
        "confirmed": _sum_nullable(rows, "confirmed"),
        "carryover": sum(r.get("carryover") or 0 for r in rows),
    }
    total["delta"] = total["current"] - total["prev_close"] if total["current"] is not None and total["prev_close"] is not None else None
    total["delta_rate"] = _rate(total["current"], total["prev_close"])
    total["yoy_rate"] = _rate(total["current"], total["last_year"])
    total["quarter_yoy"] = _rate(total["quarter_now"], total["quarter_prev"])

    prev_month = 12 if month == 1 else month - 1
    q = (month - 1) // 3 + 1
    comments = data.get("comments", {}).get(f"{year}-{month:02d}", {})
    if not isinstance(comments, dict):
        comments = {}

    stage_opts = "".join(f"<option value='{s}' {'selected' if s == stage else ''}>{s}</option>" for s in ui.STAGES)
    year_opts = "".join(f"<option value='{y}' {'selected' if y == year else ''}>{y}</option>" for y in [2025, 2026, 2027])
    month_opts = "".join(f"<option value='{m}' {'selected' if m == month else ''}>{m}월</option>" for m in range(1, 13))

    def cell_money(v):
        return ui.money_m(v)

    def cell_rate(v):
        return ui.pct_delta(v)

    body_rows = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td>{ui.esc(r['business'])}</td><td>{ui.esc(r['region'])}</td><td>{ui.esc(r['kind'])}</td>"
            f"<td>{cell_money(r['prev_close'])}</td><td class='c2'>{cell_money(r['current'])}</td>"
            f"<td>{cell_money(r['delta'])}</td><td>{cell_rate(r['delta_rate'])}</td>"
            f"<td>{cell_money(r['last_year'])}</td><td>{cell_rate(r['yoy_rate'])}</td>"
            f"<td>{cell_money(r['quarter_now'])}</td><td>{cell_money(r['quarter_prev'])}</td><td>{cell_rate(r['quarter_yoy'])}</td>"
            f"<td>{cell_money(r['confirmed'])}</td><td>{cell_money(r['carryover'])}</td>"
            "</tr>"
        )
    body_rows.append(
        "<tr class='grand'>"
        f"<td colspan='3'>MEDPARK 전체</td><td>{cell_money(total['prev_close'])}</td><td class='c2'>{cell_money(total['current'])}</td>"
        f"<td>{cell_money(total['delta'])}</td><td>{cell_rate(total['delta_rate'])}</td>"
        f"<td>{cell_money(total['last_year'])}</td><td>{cell_rate(total['yoy_rate'])}</td>"
        f"<td>{cell_money(total['quarter_now'])}</td><td>{cell_money(total['quarter_prev'])}</td><td>{cell_rate(total['quarter_yoy'])}</td>"
        f"<td>{cell_money(total['confirmed'])}</td><td>{cell_money(total['carryover'])}</td></tr>"
    )

    note_html = ""
    if comments.get("top") or comments.get("bottom"):
        note_html = "<section class='note'>"
        if comments.get("top"):
            note_html += f"<b>핵심 요약</b><br>{ui.esc(comments.get('top')).replace(chr(10), '<br>')}<br><br>"
        if comments.get("bottom"):
            note_html += f"<b>이월 · 리스크 · 후속조치</b><br>{ui.esc(comments.get('bottom')).replace(chr(10), '<br>')}"
        note_html += "</section>"

    html = f"""<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{year}년 {month}월 {stage} 실적보고서 · MEDPARK</title><style>{ui.css()}.report-detail-summary{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:12px 0}}.report-detail-summary>div{{background:#fff;border:1px solid #d7e1eb;border-radius:10px;padding:14px}}.report-detail-summary span{{display:block;color:#65768a;font-size:11px}}.report-detail-summary strong{{display:block;font-size:22px;margin-top:6px}}@media(max-width:900px){{.report-detail-summary{{grid-template-columns:1fr 1fr}}}}</style></head><body>{ui.topbar(user)}<main class='page'><section class='toolbar'><form method='get'><label>년도<select name='year'>{year_opts}</select></label><label>기준월<select name='month'>{month_opts}</select></label><label>회차<select name='stage'>{stage_opts}</select></label><button class='btn'>조회</button></form><div class='toolbar-links'><a class='btn' href='/'>전체현황</a><a class='btn' href='/#report-writer'>실적자료 작성</a></div></section><section class='meeting'><p class='eyebrow'>PERFORMANCE REPORT</p><h1>{year}년 {month}월 {stage} 실적보고서</h1><p class='meta'><b>기준:</b> {prev_month}월 확정마감 + {month}월 {stage} FCST · 전년동월 및 {q}Q 전년 동분기 비교</p></section><section class='report-detail-summary'><div><span>{prev_month}월 마감</span><strong>{cell_money(total['prev_close'])}</strong></div><div><span>{month}월 {stage} FCST</span><strong>{cell_money(total['current'])}</strong></div><div><span>전월 대비</span><strong>{cell_rate(total['delta_rate'])}</strong></div><div><span>{year-1}년 {month}월 대비</span><strong>{cell_rate(total['yoy_rate'])}</strong></div><div><span>{q}Q 전년 동분기 대비</span><strong>{cell_rate(total['quarter_yoy'])}</strong></div></section>{note_html}<div class='table-wrap'><table class='report'><thead><tr><th>사업부</th><th>구분</th><th>기존/신규</th><th>{prev_month}월 마감</th><th>{month}월 {stage}</th><th>증감액</th><th>전월 대비</th><th>{year-1}년 {month}월</th><th>전년동월 대비</th><th>{q}Q 전망</th><th>{year-1}년 {q}Q</th><th>전년 동분기 대비</th><th>확정</th><th>이월</th></tr></thead><tbody>{''.join(body_rows)}</tbody></table></div></main></body></html>"""
    return html


if "performance_report_page" not in app.view_functions:
    app.add_url_rule("/performance-report", endpoint="performance_report_page", view_func=performance_report_page, methods=["GET"])


def patched_health():
    data = base.read_store()
    return {
        "status": "ok",
        "runtime": "excel-layout-v4-report-salesops",
        "initialized": bool(data.get("meta", {}).get("initialized")),
        "users": len(data.get("users", [])),
        "entries": len(data.get("entries", [])),
        "actuals": len(data.get("actuals", {})),
        "salesops_fcst": SALESOPS_BASE + "/fcst",
        "salesops_reports": SALESOPS_BASE + "/reports",
        "salesops_mode": "read-navigation",
        "performance_report": "/performance-report",
    }


app.view_functions["health"] = patched_health
