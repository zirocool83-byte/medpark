import root_snapshot_runtime as rt
from flask import jsonify

app = rt.app
core = rt.core


def _keys():
    return [(b, "국내", k) for b in rt.base.BUSINESSES for k in rt.base.KINDS]


def _state():
    cur, _ = core._load_snapshot(2026, 9)
    prev, _ = core._load_snapshot(2026, 8)
    keys = _keys()
    cur_rows = [cur.get(k) or {} for k in keys]
    prev_rows = [prev.get(k) or {} for k in keys]
    return {
        "current_rows": sum(1 for k in keys if k in cur),
        "previous_rows": sum(1 for k in keys if k in prev),
        "second_non_null": sum(1 for r in cur_rows if r.get("second") is not None),
        "second_total": sum(r.get("second") for r in cur_rows if r.get("second") is not None),
        "prev_close_non_null": sum(1 for r in prev_rows if r.get("close") is not None),
    }


def _check(name, ok):
    return jsonify({"check": name, "ok": bool(ok), **_state()}), (200 if ok else 409)

@app.get('/snap-check-current-rows')
def snap_check_current_rows():
    s = _state(); return _check('current_rows', s['current_rows'] == 6)

@app.get('/snap-check-prev-rows')
def snap_check_prev_rows():
    s = _state(); return _check('previous_rows', s['previous_rows'] == 6)

@app.get('/snap-check-second')
def snap_check_second():
    s = _state(); return _check('second', s['second_non_null'] == 6 and s['second_total'] == 797318256)

@app.get('/snap-check-close')
def snap_check_close():
    s = _state(); return _check('close', s['prev_close_non_null'] == 6)

@app.get('/snap-prime')
def snap_prime():
    # Force live fetches; successful responses are persisted by clean_salesops_runtime.
    core._fetch(2026, 9, True)
    core._fetch(2026, 8, True)
    s = _state()
    ok = s['current_rows'] == 6 and s['previous_rows'] == 6 and s['second_non_null'] == 6 and s['second_total'] == 797318256 and s['prev_close_non_null'] == 6
    return jsonify({"status":"ok" if ok else "not_ready", **s}), (200 if ok else 409)
