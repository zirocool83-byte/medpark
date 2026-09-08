import root_live_fetch as live
from flask import jsonify

app = live.app

@app.get('/root-live-probe')
def root_live_probe():
    cur, cm = live._fetch(2026, 9)
    prev, pm = live._fetch(2026, 8)
    keys = [(b, '국내', k) for b in live.base.BUSINESSES for k in live.base.KINDS]
    cr = [cur.get(k) or {} for k in keys]
    pr = [prev.get(k) or {} for k in keys]
    return jsonify({
        'current_meta': cm,
        'previous_meta': pm,
        'current_rows': sum(1 for k in keys if k in cur),
        'previous_rows': sum(1 for k in keys if k in prev),
        'second_non_null': sum(1 for r in cr if r.get('second') is not None),
        'second_total': sum(r.get('second') for r in cr if r.get('second') is not None),
        'prev_close_non_null': sum(1 for r in pr if r.get('close') is not None),
    }), 200
