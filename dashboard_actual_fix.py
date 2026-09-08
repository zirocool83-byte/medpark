"""Final dashboard display bridge.
- 2026-08 domestic: SalesOps provisional close -> close column.
- 2026-09 domestic: SalesOps first/second FCST -> first/second columns.
- Overseas/local stored values are preserved.
"""
import dashboard_bridge_fix as active
import salesops_xhr_fix as bridge
from flask import jsonify, make_response, request

app = active.app
sap = active.sap
base = sap.base


def _sum_nullable(rows, field):
    vals = [r.get(field) for r in rows if r.get(field) is not None]
    return sum(vals) if vals else None


def _overlay_domestic(report, year, month):
    index, meta = bridge._fetch_remote_xhr(year, month, True)
    report['salesops_api'] = meta
    if not meta.get('ok'):
        return report, meta

    details = [r for r in report.get('rows', []) if not r.get('is_total')]
    for row in details:
        if row.get('region') != '국내':
            continue
        key = (row.get('business'), '국내', row.get('kind'))
        remote = index.get(key)
        if not remote:
            continue

        # Preserve every overseas/local value; only domestic fields below are overwritten.
        if remote.get('first') is not None:
            row['first'] = remote.get('first')
        if remote.get('second') is not None:
            row['second'] = remote.get('second')

        if year == 2026 and month == 8 and remote.get('close') is not None:
            row['close'] = remote.get('close')
            row['close_has'] = True
        elif remote.get('close') is not None:
            row['close'] = remote.get('close')
            row['close_has'] = True

        if remote.get('third_confirmed') is not None:
            row['third_confirmed'] = remote.get('third_confirmed')
        if remote.get('third_forecast') is not None:
            row['third_forecast'] = remote.get('third_forecast')
        row['carryover'] = remote.get('carryover', row.get('carryover', 0))

    # Recalculate subtotal/grand rows from the visible detail rows after overlay.
    sum_fields = ('first','second','third_confirmed','third_forecast','close','next_first','carryover','qproj','october','november','december','q4proj','second_half')
    for total_row in [r for r in report.get('rows', []) if r.get('is_total')]:
        source = details if total_row.get('is_grand') else [r for r in details if r.get('business') == total_row.get('business')]
        for field in sum_fields:
            total_row[field] = _sum_nullable(source, field)
        total_row['close_has'] = bool(source) and all(r.get('close_has') for r in source)

    grand = next((r for r in report.get('rows', []) if r.get('is_grand')), None)
    if grand:
        report['third_total'] = grand.get('third_forecast')
        close_total = grand.get('close') if grand.get('close_has') else None
        report['diff'] = close_total - report['third_total'] if close_total is not None and report.get('third_total') is not None else None
        report['error_rate'] = abs(report['diff']) / report['third_total'] if report.get('diff') is not None and report.get('third_total') else None

    return report, meta


@base.login_required
def dashboard_actual():
    try:
        year = int(request.args.get('year', 2026))
        month = int(request.args.get('month', 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9

    sap._CACHE.clear()
    report = sap._original_report_data(year, month)
    report, _ = _overlay_domestic(report, year, month)
    html = sap.ui.render_report(report, base.current_user(), request.args.get('capture') == '1')

    # Clarify the August close column is a provisional close as of the current SalesOps data.
    if year == 2026 and month == 8:
        html = html.replace('<th>실제 마감</th>', '<th>잠정마감</th>', 1)
        html = html.replace('실제 마감입력 진행중', '잠정마감 반영중', 1)

    resp = make_response(html)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.headers['X-MedPark-Dashboard-Bridge'] = 'domestic-final-v1'
    return resp

app.view_functions['dashboard'] = dashboard_actual


@app.get('/dashboard-actual-check')
def dashboard_actual_check():
    result = {}
    for month in (8, 9):
        sap._CACHE.clear()
        report = sap._original_report_data(2026, month)
        report, meta = _overlay_domestic(report, 2026, month)
        domestic = [r for r in report.get('rows', []) if not r.get('is_total') and r.get('region') == '국내']
        result[str(month)] = {
            'meta': meta,
            'rows': len(domestic),
            'first': _sum_nullable(domestic, 'first'),
            'second': _sum_nullable(domestic, 'second'),
            'close': _sum_nullable(domestic, 'close'),
            'close_rows': sum(1 for r in domestic if r.get('close') is not None),
        }
    ok = (
        result['9']['first'] == 732735136
        and result['9']['second'] == 797318256
        and result['8']['close'] is not None
        and result['8']['close'] > 0
    )
    return jsonify({'status':'ok' if ok else 'mismatch','dashboard':app.view_functions['dashboard'].__name__,'data':result}), (200 if ok else 409)


@app.get('/dashboard-html-check')
def dashboard_html_check():
    # Server-side render verification without requiring a browser session.
    report9 = sap._original_report_data(2026, 9)
    report9, _ = _overlay_domestic(report9, 2026, 9)
    user = next((u for u in base.read_store().get('users', []) if u.get('role') == 'admin' or u.get('manage_all')), {'display_name':'관리자'})
    html9 = sap.ui.render_report(report9, user, False)

    report8 = sap._original_report_data(2026, 8)
    report8, _ = _overlay_domestic(report8, 2026, 8)
    html8 = sap.ui.render_report(report8, user, False)

    checks = {
        'sep_first_visible': sap.ui.money_m(732735136) in html9,
        'sep_second_visible': sap.ui.money_m(797318256) in html9,
        'aug_close_visible': any(sap.ui.money_m(r.get('close')) in html8 for r in report8.get('rows', []) if not r.get('is_total') and r.get('region') == '국내' and r.get('close') is not None),
    }
    return jsonify({'status':'ok' if all(checks.values()) else 'mismatch','checks':checks}), (200 if all(checks.values()) else 409)
