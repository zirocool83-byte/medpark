import time
from pathlib import Path

import clean_salesops_runtime as active

app = active.app

_original_fetch = active._fetch
_original_health = app.view_functions.get("health")


def _fetch_retry(year, month, force=False):
    attempts = 3 if force else 2
    last_data, last_meta = {}, {"ok": False, "reason": "request_failed", "rows": 0}
    for idx in range(attempts):
        data, meta = _original_fetch(year, month, True)
        last_data, last_meta = data, meta
        if meta.get("ok"):
            return data, meta
        if idx < attempts - 1:
            time.sleep(0.25 if idx == 0 else 0.75)

    cached, saved_at = active._load_snapshot(year, month)
    if cached:
        return cached, {
            "ok": True,
            "reason": "snapshot_fallback_after_retries",
            "warning": last_meta.get("reason"),
            "source": "snapshot",
            "saved_at": saved_at,
            "rows": len(cached),
        }
    return last_data, last_meta


active._fetch = _fetch_retry


def resilient_health():
    payload = _original_health() if _original_health else {"status": "ok"}
    if isinstance(payload, tuple):
        payload = payload[0]
    if not isinstance(payload, dict):
        payload = {"status": "ok"}
    payload = dict(payload)
    p8 = Path(active._snapshot_path(2026, 8))
    p9 = Path(active._snapshot_path(2026, 9))
    payload.update({
        "runtime": "clean-salesops-2.1-resilient",
        "snapshot_2026_08_exists": p8.exists(),
        "snapshot_2026_09_exists": p9.exists(),
        "snapshot_2026_08_size": p8.stat().st_size if p8.exists() else 0,
        "snapshot_2026_09_size": p9.stat().st_size if p9.exists() else 0,
    })
    return payload


app.view_functions["health"] = resilient_health
