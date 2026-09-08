"""Final dashboard display bridge.
- 2026-08 domestic provisional close comes from SalesOps and is shown as close.
- On 2026-09 dashboard, the previous-month close column is populated from 2026-08 SalesOps provisional close.
- 2026-09 domestic FCST comes directly from SalesOps.
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


def _fetch(year, month):
    return bridge._fetch_remote_xhr(year, month, True)


def _overlay_domestic(report, year, month):
    index, meta = _fetch(year, month)
    report['salesops_api'] = meta
    details = [r for r in report.get('rows', []) if not r.get('is_total')]

    if meta.get('ok'):
        for row in details:
            if row.get('region') != '국내':
                continue
            remote = index.get((row.get('business'), '국내', row.get('kind')))
            if not remote:
                continue
            for field in ('first','second','third_confirmed','third_forecast','close'):
                if remote.get(field) is not None:
                    row[field] = remote.get(field)
            if remote.get('close') is not None:
                row['close_has'] = True
            row['carryover'] = remote.get('carryover', row.get('carryover', 0))

    # Critical: on September page, "8월 마감" is prev_close, not current close.
    # Populate domestic prev_close directly from August SalesOps provisional close.
    prev_meta = None
    if year == 2026 and month == 9:
        prev_index, prev_meta = _fetch(2026, 8)
        if prev_meta.get('ok'):
            for row in details:
                if row.get('region') != '국내':
                    continue
                remote_prev = prev_index.get((row.get('business'), '국내', row.get('kind')))
                if remote_prev and remote_prev.get('close') is not None:
                    row['prev_close'] = remote_prev.get('close')

    # Recalculate subtotal/grand-total fields after overlays.
    sum_fields = (
        'prev_close','first','second','third_confirmed','third_forecast','close',
        'next_first','carryover','qproj','october','november','december','q4proj','second_half'
    )
    for total_row in [r for r in report.get('rows', []) if r.get('is_total')]:
        source = details if total_row.get('is_grand') else [r for r in details if r.get('business') == total_row.get('business')]
        for field in sum_fields:
            total_row[field] = _sum_nullable(source, field)
        total_row['close_has'] = bool(source) and all(r.get('close_has') for r in source)

    if prev_meta is not None:
        report['salesops_prev_close_api'] = prev_meta
    return report, meta


def _build(year, month):
    sap._CACHE.clear()
    report = sap._original_report_data(year, month)
    return _overlay_domestic(report, year, month)


@base.login_required
def dashboard_actual():
    try:
        year = int(request.args.get('year', 2026)); month = int(request.args.get('month', 9))
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
    resp.headers['Pragma'] = 'no-cache'; resp.headers['Expires'] = '0'
    resp.headers['X-MedPark-Dashboard-Bridge'] = 'domestic-final-v4'
    return resp

app.view_functions['dashboard'] = dashboard_actual


def _diag(month):
    report, meta = _build(2026, month)
    rows = [r for r in report.get('rows', []) if not r.get('is_total') and r.get('region') == '국내']
    return {
        'month':month,
        'meta':meta,
        'rows':len(rows),
        'first':_sum_nullable(rows,'first'),
        'second':_sum_nullable(rows,'second'),
        'prev_close':_sum_nullable(rows,'prev_close'),
        'close':_sum_nullable(rows,'close'),
        'close_rows':sum(1 for r in rows if r.get('close') is not None),
        'detail':[{
            'business':r.get('business'),'kind':r.get('kind'),
            'first':r.get('first'),'second':r.get('second'),'prev_close':r.get('prev_close'),'close':r.get('close')
        } for r in rows]
    }

@app.get('/dashboard-diag-8')
def dashboard_diag_8():
    return jsonify(_diag(8)), 200

@app.get('/dashboard-diag-9')
def dashboard_diag_9():
    return jsonify(_diag(9)), 200

@app.get('/dashboard-row-status')
def dashboard_row_status():
    cur, cm = _fetch(2026, 9)
    prv, pm = _fetch(2026, 8)
    keys = [(b, '국내', k) for b in sap.base.BUSINESSES for k in sap.base.KINDS]
    second_values = [cur.get(key, {}).get('second') for key in keys]
    prev_values = [prv.get(key, {}).get('close') for key in keys]
    return jsonify({
        'current_ok':bool(cm.get('ok')),
        'previous_ok':bool(pm.get('ok')),
        'second_non_null':sum(v is not None for v in second_values),
        'prev_close_non_null':sum(v is not None for v in prev_values),
        'second_total':sum(v for v in second_values if v is not None) if any(v is not None for v in second_values) else None,
        'prev_close_total':sum(v for v in prev_values if v is not None) if any(v is not None for v in prev_values) else None,
    }), 200

@app.get('/dashboard-html-diag')
def dashboard_html_diag():
    user = next((u for u in base.read_store().get('users', []) if u.get('role') == 'admin' or u.get('manage_all')), {'display_name':'관리자'})
    r9,_ = _build(2026,9); h9=sap.ui.render_report(r9,user,False)
    r8,_ = _build(2026,8); h8=sap.ui.render_report(r8,user,False)
    d8=[r for r in r8.get('rows',[]) if not r.get('is_total') and r.get('region')=='국내']
    d9=[r for r in r9.get('rows',[]) if not r.get('is_total') and r.get('region')=='국내']
    return jsonify({
      'sep_second_total_in_html':sap.ui.money_m(_sum_nullable(d9,'second')) in h9 if _sum_nullable(d9,'second') is not None else False,
      'aug_prev_close_total_in_sep_html':sap.ui.money_m(_sum_nullable(d9,'prev_close')) in h9 if _sum_nullable(d9,'prev_close') is not None else False,
      'aug_any_close':any(sap.ui.money_m(r.get('close')) in h8 for r in d8 if r.get('close') is not None),
      'dashboard_func':app.view_functions['dashboard'].__name__
    }),200
