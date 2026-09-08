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

        if remote.get('first') is not None:
            row['first'] = remote.get('first')
        if remote.get('second') is not None:
            row['second'] = remote.get('second')
        if remote.get('close') is not None:
            row['close'] = remote.get('close')
            row['close_has'] = True
        if remote.get('third_confirmed') is not None:
            row['third_confirmed'] = remote.get('third_confirmed')
        if remote.get('third_forecast') is not None:
            row['third_forecast'] = remote.get('third_forecast')
        row['carryover'] = remote.get('carryover', row.get('carryover', 0))

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


def _build(year, month):
    sap._CACHE.clear()
    report = sap._original_report_data(year, month)
    return _overlay_domestic(report, year, month)


@base.login_required
def dashboard_actual():
    try:
        year = int(request.args.get('year', 2026))
        month = int(request.args.get('month', 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9

    report, _ = _build(year, month)
    html = sap.ui.render_report(report, base.current_user(), request.args.get('capture') == '1')

    if year == 2026 and month == 8:
        html = html.replace('<th>실제 마감</th>', '<th>잠정마감</th>', 1)
        html = html.replace('실제 마감입력 진행중', '잠정마감 반영중', 1)

    resp = make_response(html)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.headers['X-MedPark-Dashboard-Bridge'] = 'domestic-final-v2'
    return resp

app.view_functions['dashboard'] = dashboard_actual


def _domestic_values(month):
    report, meta = _build(2026, month)
    domestic = [r for r in report.get('rows', []) if not r.get('is_total') and r.get('region') == '국내']
    return report, domestic, meta


@app.get('/dashboard-check-sep-first')
def check_sep_first():
    _, rows, meta = _domestic_values(9)
    value = _sum_nullable(rows, 'first')
    ok = meta.get('ok') and value == 732735136
    return jsonify({'ok':ok,'value':value,'display':sap.ui.money_m(value),'meta':meta}), (200 if ok else 409)

@app.get('/dashboard-check-sep-second')
def check_sep_second():
    _, rows, meta = _domestic_values(9)
    value = _sum_nullable(rows, 'second')
    ok = meta.get('ok') and value == 797318256
    return jsonify({'ok':ok,'value':value,'display':sap.ui.money_m(value),'meta':meta}), (200 if ok else 409)

@app.get('/dashboard-check-aug-close')
def check_aug_close():
    _, rows, meta = _domestic_values(8)
    value = _sum_nullable(rows, 'close')
    close_rows = sum(1 for r in rows if r.get('close') is not None)
    ok = meta.get('ok') and value is not None and value > 0
    return jsonify({'ok':ok,'value':value,'display':sap.ui.money_m(value),'close_rows':close_rows,'meta':meta}), (200 if ok else 409)

@app.get('/dashboard-check-html-sep')
def check_html_sep():
    report, _, _ = _domestic_values(9)
    user = next((u for u in base.read_store().get('users', []) if u.get('role') == 'admin' or u.get('manage_all')), {'display_name':'관리자'})
    html = sap.ui.render_report(report, user, False)
    first = sap.ui.money_m(732735136)
    second = sap.ui.money_m(797318256)
    ok = first in html and second in html
    return jsonify({'ok':ok,'first':first,'second':second,'first_in_html':first in html,'second_in_html':second in html}), (200 if ok else 409)

@app.get('/dashboard-check-html-aug')
def check_html_aug():
    report, rows, _ = _domestic_values(8)
    user = next((u for u in base.read_store().get('users', []) if u.get('role') == 'admin' or u.get('manage_all')), {'display_name':'관리자'})
    html = sap.ui.render_report(report, user, False)
    values = [sap.ui.money_m(r.get('close')) for r in rows if r.get('close') is not None]
    ok = bool(values) and any(v in html for v in values)
    return jsonify({'ok':ok,'values':values,'visible':[v for v in values if v in html]}), (200 if ok else 409)
