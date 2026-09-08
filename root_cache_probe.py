import root_boot_cache as cache
from flask import jsonify

app = cache.app
base = cache.base

@app.get('/root-cache-probe')
def root_cache_probe():
    cur, cm = cache._get(2026, 9)
    prev, pm = cache._get(2026, 8)
    keys = [(b, '국내', k) for b in base.BUSINESSES for k in base.KINDS]
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
