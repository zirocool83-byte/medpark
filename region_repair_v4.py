"""Restore the state immediately before the overly-broad v2 correction, then apply only the seven user-specified reclassifications.
No rows are added/deleted. Only business/region of the seven exact rows may differ from the v2-before snapshot.
"""
import copy
import hashlib
import hmac
import json
import os
import re
from pathlib import Path

import salesops_api_patch as active
from flask import abort, jsonify, request

app = active.app
base = active.base
DATA_DIR = Path(base.DATA_DIR)
V2_BEFORE = DATA_DIR / "region_correction_20260908_v2.before.json"
WRONG_STATE_BACKUP = DATA_DIR / "region_correction_20260908_v4.wrong_state_before_restore.json"
AUDIT = DATA_DIR / "region_correction_20260908_v4.audit.json"
AUTH_LABEL = b"region-correction-20260908-v4-status"

SPECS = [
    {"kind":"기존","status":"확정","item":"11개 거래처","amount_m":"423","business":"덴탈","region":"해외"},
    {"kind":"기존","status":"예상","item":"5개 거래처","amount_m":"209.2","business":"덴탈","region":"해외"},
    {"kind":"기존","status":"추진","item":"18개 거래처","amount_m":"698.1","business":"덴탈","region":"해외"},
    {"kind":"기존","status":"확정","item":"지라프(말레이시아)","amount_m":"12.7","business":"메디컬","region":"해외"},
    {"kind":"신규","status":"확정","item":"태국 현장판매외","amount_m":"4.4","business":"에스테틱","region":"해외"},
    {"kind":"신규","status":"예상","item":"포에버18, 메디케어","amount_m":"43.3","business":"에스테틱","region":"해외"},
    {"kind":"신규","status":"추진","item":"미얀마 스타케이","amount_m":"14.1","business":"에스테틱","region":"해외"},
]

def norm(v):
    return re.sub(r"[^0-9a-z가-힣]+", "", str(v or "").strip().lower())

def token():
    return os.environ.get("PERFORMANCE_READ_ONLY_TOKEN", "").strip()

def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def same_period(e):
    return str(e.get("year")) == "2026" and str(e.get("month")) in ("9", "09") and e.get("stage") == "2차"

def user_ok(e):
    return str(e.get("writer", "")).strip() == "김홍윤" or str(e.get("user_id", "")).strip().lower() == "mp001"

def matches(e, spec):
    return same_period(e) and user_ok(e) and e.get("kind") == spec["kind"] and e.get("status") == spec["status"] and norm(e.get("item")) == norm(spec["item"]) and base.money_m(e.get("amount")) == spec["amount_m"]

def run_once():
    if AUDIT.exists():
        return load_json(AUDIT)
    if not V2_BEFORE.exists():
        return {"status":"not_applied","reason":"v2_before_backup_missing"}

    baseline = load_json(V2_BEFORE)
    current_wrong = base.read_store()
    if not WRONG_STATE_BACKUP.exists():
        save_json(WRONG_STATE_BACKUP, current_wrong)

    found = []
    problems = []
    for spec in SPECS:
        rows = [e for e in baseline.get("entries", []) if matches(e, spec)]
        if len(rows) != 1:
            problems.append({"item":spec["item"],"amount_m":spec["amount_m"],"matches":len(rows)})
        else:
            found.append((rows[0], spec))
    if problems or len(found) != 7:
        return {"status":"not_applied","reason":"exact_match_failed","matched":len(found),"problems":problems}

    result_store = copy.deepcopy(baseline)
    by_id = {str(e.get("id")):e for e in result_store.get("entries", [])}
    ids = []
    for original, spec in found:
        rid = str(original.get("id", ""))
        if not rid or rid not in by_id:
            return {"status":"not_applied","reason":"target_id_missing"}
        ids.append(rid)
        by_id[rid]["business"] = spec["business"]
        by_id[rid]["region"] = spec["region"]
    if len(set(ids)) != 7:
        return {"status":"not_applied","reason":"duplicate_target_ids"}

    # Strong preservation test: reverse only the seven business/region fields and require exact baseline equality.
    reverted = copy.deepcopy(result_store)
    rev = {str(e.get("id")):e for e in reverted.get("entries", [])}
    base_by_id = {str(e.get("id")):e for e in baseline.get("entries", [])}
    for rid in ids:
        rev[rid]["business"] = base_by_id[rid].get("business")
        rev[rid]["region"] = base_by_id[rid].get("region")
    if reverted != baseline:
        return {"status":"not_applied","reason":"preservation_check_failed"}
    if len(result_store.get("entries", [])) != len(baseline.get("entries", [])):
        return {"status":"not_applied","reason":"row_count_changed"}

    base.write_store(result_store)
    persisted = base.read_store()
    if persisted != result_store:
        return {"status":"needs_review","reason":"post_write_verification_failed"}

    checks = []
    for spec in SPECS:
        rows = [e for e in persisted.get("entries", []) if matches(e, spec)]
        ok = len(rows) == 1 and rows[0].get("business") == spec["business"] and rows[0].get("region") == spec["region"]
        checks.append({"item":spec["item"],"amount_m":spec["amount_m"],"business":spec["business"],"region":spec["region"],"ok":ok})

    # Overseas dental-new must remain exactly as in the v2-before baseline (the requested seven contain no dental-new row).
    def dental_new_ids(store):
        return sorted(str(e.get("id")) for e in store.get("entries", []) if same_period(e) and e.get("business") == "덴탈" and e.get("region") == "해외" and e.get("kind") == "신규")
    overseas_dental_new_preserved = dental_new_ids(persisted) == dental_new_ids(baseline)

    result = {
        "status":"applied" if all(c["ok"] for c in checks) and overseas_dental_new_preserved else "needs_review",
        "restored_from":"v2_before_backup",
        "specified_count":7,
        "entry_count_before":len(baseline.get("entries", [])),
        "entry_count_after":len(persisted.get("entries", [])),
        "no_rows_added_or_deleted":len(baseline.get("entries", [])) == len(persisted.get("entries", [])),
        "only_seven_business_region_fields_changed":True,
        "overseas_dental_new_preserved_from_baseline":overseas_dental_new_preserved,
        "checks":checks,
    }
    save_json(AUDIT, result)
    return result

try:
    RESULT = run_once()
except Exception as exc:
    RESULT = {"status":"not_applied","reason":type(exc).__name__}

def authorize():
    t = token(); supplied = request.args.get("key", "")
    expected = hmac.new(t.encode(), AUTH_LABEL, hashlib.sha256).hexdigest() if t else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        user = base.current_user()
        if not user or not (user.get("manage_all") or user.get("role") == "admin"):
            abort(404)

@app.get("/region-repair-v4/status")
def status():
    authorize()
    ok = RESULT.get("status") == "applied" and RESULT.get("specified_count") == 7 and RESULT.get("no_rows_added_or_deleted") and RESULT.get("overseas_dental_new_preserved_from_baseline")
    return jsonify(RESULT), (200 if ok else 409)
