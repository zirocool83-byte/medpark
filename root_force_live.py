"""Force the live '/' dashboard to render from the local persistent store after SalesOps mirror sync.
Same project and same root URL. No alternate space/path.
"""
import salesops_local_mirror as mirror
from flask import make_response, request

app = mirror.app
base = mirror.base
sap = mirror.sap


def _sum_nullable(rows, field):
    vals = [r.get(field) for r in rows if r.get(field) is not None]
    return sum(vals) if vals else None


def _recalc_totals(report):
    details = [r for r in report.get('rows', []) if not r.get('is_total')]
    sum_fields = (
        'ytd','prev_ytd','prev_same','compare_current','prev_first','prev_preclose','prev_close',
        'first','second','third_confirmed','third_forecast','close','next_first','carryover',
        'qproj','october','november','december','q4proj','second_half'
    )
    for total_row in [r for r in report.get('rows', []) if r.get('is_total')]:
        source = details if total_row.get('is_grand') else [r for r in details if r.get('business') == total_row.get('business')]
        for field in sum_fields:
            total_row[field] = _sum_nullable(source, field)
        total_row['hist'] = {m: sum((r.get('hist', {}).get(m, 0) or 0) for r in source) for m in range(1, 13)}
        total_row['avg'] = sum((r.get('avg', 0) or 0) for r in source)
        total_row['close_has'] = bool(source) and all(r.get('close_has') for r in source)


def _build_local(year, month):
    # Refresh local mirror first, but render only from the persistent local store after that.
    try:
        mirror.sync_local_from_salesops()
    except Exception:
        pass
    data = base.read_store()
    report = sap._original_report_data(year, month)
    details = [r for r in report.get('rows', []) if not r.get('is_total')]

    for row in details:
        if row.get('region') != '국내':
            continue
        business = row.get('business')
        kind = row.get('kind')

        # September dashboard: August provisional close is both previous-month close
        # and August monthly actual. September second FCST comes from local mirrored entries.
        if year == 2026 and month == 9:
            aug = data.get('actuals', {}).get(base.actual_key(2026, 8, business, '국내', kind))
            if aug is not None:
                aug = base.int_value(aug)
                row.setdefault('hist', {})[8] = aug
                row['prev_close'] = aug
                row['ytd'] = sum((row.get('hist', {}).get(m, 0) or 0) for m in range(1, 9))
                row['avg'] = row['ytd'] / 8
            second = base.stage_total(data, 2026, 9, '2차', business, '국내', kind)
            if second is not None:
                row['second'] = second

        # August page: show mirrored provisional close as close.
        if year == 2026 and month == 8:
            close = data.get('actuals', {}).get(base.actual_key(2026, 8, business, '국내', kind))
            if close is not None:
                close = base.int_value(close)
                row['close'] = close
                row['close_has'] = True

    _recalc_totals(report)
    return report


@app.before_request
def force_live_root():
    if request.path != '/':
        return None
    user = base.current_user()
    if not user:
        return None
    try:
        year = int(request.args.get('year', 2026))
        month = int(request.args.get('month', 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9

    report = _build_local(year, month)
    html = sap.ui.render_report(report, user, request.args.get('capture') == '1')
    if year == 2026 and month == 8:
        html = html.replace('<th>실제 마감</th>', '<th>잠정마감</th>', 1)
        html = html.replace('실제 마감입력 진행중', '잠정마감 반영중', 1)
    html = html.replace('</body>', '<!-- ROOT_LOCAL_STORE_V2_20260909 -->\n</body>', 1)
    resp = make_response(html)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, private'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.headers['Surrogate-Control'] = 'no-store'
    resp.headers['X-MedPark-Root-Force'] = 'local-store-v2'
    return resp
