import runtime_origin_check as diag
from flask import jsonify

app = diag.app
core = diag.core
resilient = diag.resilient

@app.get('/snapshot-save-probe')
def snapshot_save_probe():
    out = {}
    for year, month, label in [(2026,9,'sep'),(2026,8,'aug')]:
        try:
            data, meta = resilient._original_fetch(year, month, True)
        except Exception as exc:
            data, meta = {}, {'ok':False,'reason':type(exc).__name__}
        saved = False
        save_error = None
        if meta.get('ok') and data:
            try:
                core._save_snapshot(year, month, data)
                saved = True
            except Exception as exc:
                save_error = type(exc).__name__
        raw_count, raw_keys = diag._raw_rows(year, month)
        loaded, _ = core._load_snapshot(year, month)
        out[label] = {
            'fetch_ok': bool(meta.get('ok')),
            'fetch_reason': meta.get('reason'),
            'fetch_rows': len(data),
            'saved': saved,
            'save_error': save_error,
            'raw_count': raw_count,
            'loaded_count': len(loaded),
            'raw_keys': raw_keys,
        }
    return jsonify(out), 200
