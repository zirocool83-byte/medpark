"""One-time guarded provisional close for 2026-08 overseas fields from the user-supplied August export.
Only overseas August actuals are set; no rows are added/deleted and September FCST is untouched.
"""
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path

import region_repair_v4 as active
from flask import abort, jsonify, request

app = active.app
base = active.base
DATA_DIR = Path(base.DATA_DIR)
AUDIT = DATA_DIR / "august_overseas_provisional_close_20260908.audit.json"
BACKUP = DATA_DIR / "august_overseas_provisional_close_20260908.before.json"
AUTH_LABEL = b"august-overseas-provisional-close-20260908-status"

# Exact KRW sums from overseas사업 8월마감매출 export, grouped by FIELD.
VALUES = {
    ("덴탈", "해외", "기존"): 390_072_489,
    ("덴탈", "해외", "신규"): 166_823_586,
    ("메디컬", "해외", "기존"): 60_971_390,
    ("메디컬", "해외", "신규"): 0,
    ("에스테틱", "해외", "기존"): 8_428_488,
    ("에스테틱", "해외", "신규"): 0,
}
EXPECTED_TOTAL = 626_295_953

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def run_once():
    if AUDIT.exists():
        return load_json(AUDIT)
    before = base.read_store()
    if sum(VALUES.values()) != EXPECTED_TOTAL:
        return {"status":"not_applied","reason":"source_total_mismatch"}
    if not BACKUP.exists():
        save_json(BACKUP, before)
    after = copy.deepcopy(before)
    actuals = after.setdefault("actuals", {})
    changed = []
    for (business, region, kind), amount in VALUES.items():
        key = base.actual_key(2026, 8, business, region, kind)
        old = actuals.get(key)
        actuals[key] = amount
        changed.append({"business":business,"region":region,"kind":kind,"old":old,"new":amount})
    meta = after.setdefault("meta", {})
    meta["2026-08_overseas_close_status"] = "잠정마감"
    meta["2026-08_overseas_close_source"] = "해외사업 8월마감매출_2026-09-08_19-49.xlsx"
    meta["2026-08_overseas_close_total"] = EXPECTED_TOTAL
    # Safety: entries must remain byte-for-byte identical.
    if after.get("entries", []) != before.get("entries", []):
        return {"status":"not_applied","reason":"entries_changed"}
    base.write_store(after)
    persisted = base.read_store()
    ok = all(persisted.get("actuals", {}).get(base.actual_key(2026,8,b,r,k)) == v for (b,r,k),v in VALUES.items())
    ok = ok and persisted.get("entries", []) == before.get("entries", [])
    result = {
        "status":"applied" if ok else "needs_review",
        "period":"2026-08",
        "region":"해외",
        "close_status":"잠정마감",
        "total":EXPECTED_TOTAL,
        "changed":changed,
        "entries_untouched":persisted.get("entries", []) == before.get("entries", []),
    }
    save_json(AUDIT, result)
    return result

try:
    RESULT = run_once()
except Exception as exc:
    RESULT = {"status":"not_applied","reason":type(exc).__name__}

def token():
    return os.environ.get("PERFORMANCE_READ_ONLY_TOKEN", "").strip()

def authorize():
    t = token(); supplied = request.args.get("key", "")
    expected = hmac.new(t.encode(), AUTH_LABEL, hashlib.sha256).hexdigest() if t else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        user = base.current_user()
        if not user or not (user.get("manage_all") or user.get("role") == "admin"):
            abort(404)

@app.get("/august-overseas-provisional-close/status")
def august_overseas_provisional_close_status():
    authorize()
    return jsonify(RESULT), (200 if RESULT.get("status") == "applied" else 409)
