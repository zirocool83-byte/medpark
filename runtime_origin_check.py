import root_snapshot_runtime as rt
from flask import jsonify

app = rt.app
ui = rt.ui

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
    }), 200

@app.get('/runtime-origin-excel')
def runtime_origin_excel():
    fn = ui.report_data
    ok = getattr(fn, '__module__', '') == 'excel_ui' and getattr(fn, '__name__', '') == 'report_data'
    return jsonify({'ok':ok}), (200 if ok else 409)

@app.get('/runtime-origin-salesops')
def runtime_origin_salesops():
    fn = ui.report_data
    mod = getattr(fn, '__module__', '')
    name = getattr(fn, '__name__', '')
    ok = 'salesops' in mod.lower() or 'salesops' in name.lower()
    return jsonify({'ok':ok,'module':mod,'name':name}), (200 if ok else 409)
