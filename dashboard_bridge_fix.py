import report_bridge_verify as active
from flask import make_response, request

app = active.app
sap = active.sap
base = sap.base

@base.login_required
def dashboard_bridge():
    try:
        year = int(request.args.get('year', 2026))
        month = int(request.args.get('month', 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9
    sap._CACHE.clear()
    report = sap.ui.report_data(year, month)
    html = sap.ui.render_report(report, base.current_user(), request.args.get('capture') == '1')
    resp = make_response(html)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

app.view_functions['dashboard'] = dashboard_bridge

@app.get('/dashboard-bridge-check')
def dashboard_bridge_check():
    sap._CACHE.clear()
    report = sap.ui.report_data(2026, 9)
    rows = [r for r in report.get('rows', []) if not r.get('is_total') and r.get('region') == '국내']
    first = sum(r.get('first') or 0 for r in rows)
    second = sum(r.get('second') or 0 for r in rows)
    return {
        'status': 'ok' if first == 732735136 and second == 797318256 else 'mismatch',
        'dashboard_bound': app.view_functions.get('dashboard').__name__ == 'dashboard_bridge',
        'domestic_rows': len(rows),
        'first_total': first,
        'second_total': second,
        'first_display': sap.ui.money_m(first),
        'second_display': sap.ui.money_m(second),
    }, 200
