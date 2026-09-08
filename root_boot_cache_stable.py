import threading
import time

import root_boot_cache as cache
from flask import jsonify

app = cache.app
base = cache.base

_original_get = cache._get


def _get_stable(year, month):
    key = (year, month)
    data = cache._CACHE.get(key) or {}
    if data:
        return data, cache._META.get(key, {"ok": True, "source": "memory"})

    last_meta = {"ok": False, "reason": "cache_empty", "source": "memory"}
    # A request that lands on a cold instance waits until that instance has a usable cache.
    for i in range(40):
        try:
            ok = cache._refresh_period(year, month)
        except Exception:
            ok = False
        data = cache._CACHE.get(key) or {}
        last_meta = cache._META.get(key, last_meta)
        if ok and data:
            return data, last_meta
        if i < 39:
            time.sleep(0.2)

    return _original_get(year, month)


cache._get = _get_stable


def _warmer():
    targets = [(2026, 9), (2026, 8)]
    for _ in range(240):
        all_ready = True
        for year, month in targets:
            if not (cache._CACHE.get((year, month)) or {}):
                all_ready = False
                try:
                    cache._refresh_period(year, month)
                except Exception:
                    pass
        if all_ready:
            return
        time.sleep(0.5)


threading.Thread(target=_warmer, daemon=True).start()


@app.get('/root-stable-check')
def root_stable_check():
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
        'status': 'ok' if ok else 'not_ready',
        'current_source': cm.get('source'),
        'previous_source': pm.get('source'),
        'current_rows': current_rows,
        'previous_rows': previous_rows,
        'second_non_null': second_non_null,
        'second_total': second_total,
        'prev_close_non_null': close_non_null,
    }), (200 if ok else 409)
