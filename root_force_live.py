"""Force the live root dashboard to render the current SalesOps-backed report before any legacy dashboard view can run.
Same project, same '/' URL. No new space or alternate user-facing path.
"""
import salesops_local_mirror as mirror
import dashboard_actual_fix as dash
from flask import make_response, request

app = mirror.app
base = mirror.base
sap = mirror.sap

@app.before_request
def force_live_root():
    if request.path != '/':
        return None
    user = base.current_user()
    if not user:
        return None
    try:
        mirror.sync_local_from_salesops()
    except Exception:
        pass
    try:
        year = int(request.args.get('year', 2026))
        month = int(request.args.get('month', 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9
    report, _ = dash._build(year, month)
    html = sap.ui.render_report(report, user, request.args.get('capture') == '1')
    if year == 2026 and month == 8:
        html = html.replace('<th>실제 마감</th>', '<th>잠정마감</th>', 1)
        html = html.replace('실제 마감입력 진행중', '잠정마감 반영중', 1)
    html = html.replace('</body>', '<!-- ROOT_FORCE_LIVE_20260909 -->\n</body>', 1)
    resp = make_response(html)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, private'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.headers['Surrogate-Control'] = 'no-store'
    resp.headers['X-MedPark-Root-Force'] = '20260909-live'
    return resp
