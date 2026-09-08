import root_snapshot_runtime as rt
from flask import jsonify

app = rt.app
ui = rt.ui
core = rt.core
resilient = rt.resilient
base = rt.base


def _keys():
    return [(b, "국내", k) for b in base.BUSINESSES for k in base.KINDS]


def _snap_state():
    cur, _ = core._load_snapshot(2026, 9)
    prev, _ = core._load_snapshot(2026, 8)
    keys = _keys()
    cur_rows = [cur.get(k) or {} for k in keys]
    prev_rows = [prev.get(k) or {} for k in keys]
    return {
        'current_rows': sum(1 for k in keys if k in cur),
        'previous_rows': sum(1 for k in keys if k in prev),
        'second_non_null': sum(1 for r in cur_rows if r.get('second') is not None),
        'second_total': sum(r.get('second') for r in cur_rows if r.get('second') is not None),
        'prev_close_non_null': sum(1 for r in prev_rows if r.get('close') is not None),
    }

@app.get('/runtime-origin-check')
def runtime_origin_check():
    report_fn = ui.report_data
    render_fn = ui.render_report
    dashboard_fn = app.view_functions.get('dashboard')
    return jsonify({
        'report_module': getattr(report_fn, '__module__', ''),
        'report_name': getattr(report_fn, '__name__', ''),
        'render_module': getattr(render_fn, '__module__', ''),
        'render_name': getattr(render_fn, '__name__', ''),
        'dashboard_module': getattr(dashboard_fn, '__module__', '') if dashboard_fn else '',
        'dashboard_name': getattr(dashboard_fn, '__name__', '') if dashboard_fn else '',
        **_snap_state(),
    }), 200

@app.get('/runtime-origin-excel')
def runtime_origin_excel():
    fn = ui.report_data
    ok = getattr(fn, '__module__', '') == 'excel_ui' and getattr(fn, '__name__', '') == 'report_data'
    return jsonify({'ok':ok}), (200 if ok else 409)

@app.get('/snap-current6')
def snap_current6():
    s=_snap_state(); return jsonify(s), (200 if s['current_rows']==6 else 409)

@app.get('/snap-prev6')
def snap_prev6():
    s=_snap_state(); return jsonify(s), (200 if s['previous_rows']==6 else 409)

@app.get('/snap-second6')
def snap_second6():
    s=_snap_state(); return jsonify(s), (200 if s['second_non_null']==6 and s['second_total']==797318256 else 409)

@app.get('/snap-close6')
def snap_close6():
    s=_snap_state(); return jsonify(s), (200 if s['prev_close_non_null']==6 else 409)

@app.get('/snap-rebuild')
def snap_rebuild():
    results = {}
    for year, month, label in [(2026, 9, 'sep'), (2026, 8, 'aug')]:
        try:
            data, meta = resilient._original_fetch(year, month, True)
        except Exception as exc:
            data, meta = {}, {'ok':False, 'reason':type(exc).__name__}
        results[label] = {'ok':bool(meta.get('ok')), 'reason':meta.get('reason'), 'rows':len(data)}
        if meta.get('ok') and data:
            try:
                core._save_snapshot(year, month, data)
            except Exception as exc:
                results[label]['save_error'] = type(exc).__name__
    state = _snap_state()
    ok = state['current_rows'] == 6 and state['previous_rows'] == 6 and state['second_non_null'] == 6 and state['second_total'] == 797318256 and state['prev_close_non_null'] == 6
    return jsonify({'status':'ok' if ok else 'not_ready', 'fetch':results, **state}), (200 if ok else 409)
