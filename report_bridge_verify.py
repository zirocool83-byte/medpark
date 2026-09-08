import salesops_xhr_fix as active
from flask import jsonify, request

app = active.app
sap = active.sap

@app.get('/report-bridge-check')
def report_bridge_check():
    try:
        year = int(request.args.get('year', 2026)); month = int(request.args.get('month', 9))
    except Exception:
        year, month = 2026, 9
    report = sap.ui.report_data(year, month)
    rows = [r for r in report.get('rows', []) if not r.get('is_total') and r.get('region') == '국내']
    totals = {}
    for field in ('first','second','third_confirmed','third_forecast','close'):
        vals = [r.get(field) for r in rows if r.get(field) is not None]
        totals[field] = sum(vals) if vals else None
    return jsonify({
        'year':year,
        'month':month,
        'domestic_rows':len(rows),
        'totals':totals,
        'close_present': totals.get('close') is not None and totals.get('close') > 0,
        'salesops_api':report.get('salesops_api', {}),
    }), 200
