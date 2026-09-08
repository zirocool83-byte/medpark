import excel_ui as ui

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
    sales_links = (
        f"<a class='btn' target='_blank' rel='noopener' href='{SALESOPS_BASE}/fcst'>SalesOps FCST</a>"
        f"<a class='btn' target='_blank' rel='noopener' href='{SALESOPS_BASE}/reports'>SalesOps 실적보고서</a>"
    )
    html = html.replace(toolbar_anchor, toolbar_anchor + sales_links, 1)
    return html


ui.render_report = render_report


def patched_health():
    data = base.read_store()
    return {
        "status": "ok",
        "runtime": "excel-layout-v3-ytd-salesops",
        "initialized": bool(data.get("meta", {}).get("initialized")),
        "users": len(data.get("users", [])),
        "entries": len(data.get("entries", [])),
        "actuals": len(data.get("actuals", {})),
        "salesops_fcst": SALESOPS_BASE + "/fcst",
        "salesops_reports": SALESOPS_BASE + "/reports",
        "salesops_mode": "read-navigation",
    }


app.view_functions["health"] = patched_health
