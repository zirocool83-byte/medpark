import threading

import root_boot_cache_stable as stable
from flask import jsonify

app = stable.app
cache = stable.cache
live = cache.live
base = cache.base

# Use the SalesOps in-process bridge. Do not block application startup.
live.SALESOPS_API = live.SALESOPS_BASE + "/api/performance-direct"
cache._CACHE.clear()
cache._META.clear()

# Warm every instance in the background after the app is available.
threading.Thread(target=stable._warmer, daemon=True).start()


@app.get('/root-direct-check')
def root_direct_check():
    cur, cm = cache._get(2026, 9)
    prev, pm = cache._get(2026, 8)
    keys = [(b, '국내', k) for b in base.BUSINESSES for k in base.KINDS]
    cr = [cur.get(k) or {} for k in keys]
    pr = [prev.get(k) or {} for k in keys]
    current_rows = sum(1 for k in keys if k in cur)
    previous_rows = sum(1 for k in keys if k in prev)
    second_non_null = sum(1 for r in cr if r.get('second') is not None)
    second_total = sum(r.get('second') for r in cr if r.get('second') is not None)
    close_non_null = sum(1 for r in pr if r.get('close') is not None)
    ok = cm.get('ok') and pm.get('ok') and current_rows == 6 and previous_rows == 6 and second_non_null == 6 and second_total == 797318256 and close_non_null == 6
    return jsonify({
        'status':'ok' if ok else 'not_ready',
        'current_source':cm.get('source'),
        'previous_source':pm.get('source'),
        'current_rows':current_rows,
        'previous_rows':previous_rows,
        'second_non_null':second_non_null,
        'second_total':second_total,
        'prev_close_non_null':close_non_null,
        'api_path':'/api/performance-direct',
    }), (200 if ok else 409)
