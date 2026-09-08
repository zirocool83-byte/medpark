"""Mirror domestic SalesOps read-only API values into the local performance store so the legacy dashboard also displays them.
- 2026-08 domestic close -> actuals (provisional close mirror)
- 2026-09 domestic second FCST -> one synthetic balancing entry per business/kind
Manual entries are preserved; the synthetic row stores only the difference required to match the API total.
Overseas data is untouched.
"""
import copy
import json
import os
from pathlib import Path

import dashboard_actual_fix as active
import salesops_xhr_fix as bridge
from flask import jsonify

app = active.app
sap = active.sap
base = sap.base
DATA_DIR = Path(base.DATA_DIR)
BACKUP = DATA_DIR / "salesops_domestic_local_mirror_20260908.before.json"
SYNC_PREFIX = "salesops-api-sync|2026-09|2차|"
SYNC_NOTE = "SalesOps READ ONLY API 자동동기화"


def _save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def _manual_second_sum(data, business, kind):
    total = 0
    for e in data.get("entries", []):
        if e.get("year") != 2026 or e.get("month") != 9 or e.get("stage") != "2차":
            continue
        if e.get("business") != business or e.get("region") != "국내" or e.get("kind") != kind:
            continue
        if str(e.get("id", "")).startswith(SYNC_PREFIX):
            continue
        if e.get("status") in base.COUNT_STATUSES:
            total += base.int_value(e.get("amount"))
    return total


def sync_local_from_salesops():
    idx8, meta8 = bridge._fetch_remote_xhr(2026, 8, True)
    idx9, meta9 = bridge._fetch_remote_xhr(2026, 9, True)
    if not (meta8.get("ok") and meta9.get("ok")):
        return {"status":"not_applied","aug":meta8,"sep":meta9}

    data = base.read_store()
    if not BACKUP.exists():
        _save_json(BACKUP, copy.deepcopy(data))

    actuals = data.setdefault("actuals", {})
    entries = data.setdefault("entries", [])
    aug_rows = 0
    sep_rows = 0

    for business in base.BUSINESSES:
        for kind in base.KINDS:
            key = (business, "국내", kind)
            r8 = idx8.get(key) or {}
            r9 = idx9.get(key) or {}

            close = r8.get("close")
            if close is not None:
                actuals[base.actual_key(2026, 8, business, "국내", kind)] = int(close)
                aug_rows += 1

            second = r9.get("second")
            if second is None:
                continue
            manual = _manual_second_sum(data, business, kind)
            balance = int(second) - int(manual)
            if balance < 0:
                balance = 0
            sync_id = SYNC_PREFIX + business + "|" + kind
            row = next((e for e in entries if e.get("id") == sync_id), None)
            payload = {
                "id": sync_id,
                "year": 2026,
                "month": 9,
                "stage": "2차",
                "business": business,
                "region": "국내",
                "kind": kind,
                "status": "예상",
                "item": "SalesOps API 동기화",
                "amount": balance,
                "note": SYNC_NOTE,
                "writer": "SalesOps API",
                "user_id": "system",
                "updated_at": base.now_text(),
                "seeded": True,
            }
            if row is None:
                entries.append(payload)
            else:
                row.update(payload)
            sep_rows += 1

    meta = data.setdefault("meta", {})
    meta["salesops_domestic_mirror"] = {
        "updated_at": base.now_text(),
        "august_status": "잠정마감",
        "august_rows": aug_rows,
        "september_stage": "2차",
        "september_rows": sep_rows,
    }
    base.write_store(data)

    persisted = base.read_store()
    second_total = base.stage_total(persisted, 2026, 9, "2차", region="국내")
    close_values = []
    for business in base.BUSINESSES:
        for kind in base.KINDS:
            v = persisted.get("actuals", {}).get(base.actual_key(2026, 8, business, "국내", kind))
            if v is not None:
                close_values.append(base.int_value(v))
    close_total = sum(close_values) if close_values else None
    return {
        "status":"applied" if second_total == 797318256 and len(close_values) == 6 else "needs_review",
        "second_total":second_total,
        "august_close_rows":len(close_values),
        "august_close_total":close_total,
        "august_api":meta8,
        "september_api":meta9,
    }


try:
    SYNC_RESULT = sync_local_from_salesops()
except Exception as exc:
    SYNC_RESULT = {"status":"error","reason":type(exc).__name__}

# Keep data fresh whenever the real dashboard is opened.
_current_dashboard = app.view_functions.get("dashboard")
@base.login_required
def dashboard_with_local_mirror():
    try:
        sync_local_from_salesops()
    except Exception:
        pass
    # call the already-patched dashboard body without changing any other routes
    return active.dashboard_actual.__wrapped__()

app.view_functions["dashboard"] = dashboard_with_local_mirror

@app.get("/local-sync-check")
def local_sync_check():
    try:
        result = sync_local_from_salesops()
    except Exception as exc:
        result = {"status":"error","reason":type(exc).__name__}
    return jsonify(result), 200
