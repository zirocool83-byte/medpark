"""Exact one-time correction for the seven user-specified Sep 2026 second-round rows.
Only business/region fields are changed. No rows are deleted or recreated.
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
AUDIT = Path(base.DATA_DIR) / "region_correction_20260908_v3.audit.json"
BACKUP = Path(base.DATA_DIR) / "region_correction_20260908_v3.before.json"
AUTH_LABEL = b"region-correction-20260908-v3-status"

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

def save_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def same_period(e):
    return str(e.get("year")) == "2026" and str(e.get("month")) in ("9", "09") and e.get("stage") == "2차"

def user_ok(e):
    return str(e.get("writer", "")).strip() == "김홍윤" or str(e.get("user_id", "")).strip().lower() == "mp001"

def matches(e, spec):
    return (
        same_period(e)
        and user_ok(e)
        and e.get("kind") == spec["kind"]
        and e.get("status") == spec["status"]
        and norm(e.get("item")) == norm(spec["item"])
        and base.money_m(e.get("amount")) == spec["amount_m"]
    )

def run_once():
    if AUDIT.exists():
        with open(AUDIT, encoding="utf-8") as f:
            return json.load(f)

    before = base.read_store()
    found = []
    problems = []
    for spec in SPECS:
        rows = [e for e in before.get("entries", []) if matches(e, spec)]
        if len(rows) != 1:
            problems.append({"item":spec["item"], "amount_m":spec["amount_m"], "matches":len(rows)})
        else:
            found.append((rows[0], spec))
    if problems or len(found) != len(SPECS):
        return {"status":"not_applied","reason":"exact_match_failed","problems":problems,"matched":len(found)}

    ids = [str(e.get("id", "")) for e, _ in found]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        return {"status":"not_applied","reason":"invalid_or_duplicate_ids"}

    after = copy.deepcopy(before)
    by_id = {str(e.get("id")): e for e in after.get("entries", [])}
    original_fields = {}
    changed = []
    for original, spec in found:
        rid = str(original.get("id"))
        target = by_id[rid]
        original_fields[rid] = {"business":target.get("business"), "region":target.get("region")}
        if target.get("business") != spec["business"] or target.get("region") != spec["region"]:
            changed.append(rid)
        target["business"] = spec["business"]
        target["region"] = spec["region"]

    reverted = copy.deepcopy(after)
    rev_by_id = {str(e.get("id")): e for e in reverted.get("entries", [])}
    for rid, old in original_fields.items():
        rev_by_id[rid]["business"] = old["business"]
        rev_by_id[rid]["region"] = old["region"]
    if reverted != before or len(after.get("entries", [])) != len(before.get("entries", [])):
        return {"status":"not_applied","reason":"preservation_check_failed"}

    if not BACKUP.exists():
        save_private(BACKUP, before)
    base.write_store(after)
    persisted = base.read_store()
    if persisted != after:
        return {"status":"needs_review","reason":"post_write_verification_failed"}

    # Verify all seven now sit in the exact requested business/region and remain unique.
    checks = []
    for spec in SPECS:
        rows = [e for e in persisted.get("entries", []) if matches(e, spec)]
        ok = len(rows) == 1 and rows[0].get("business") == spec["business"] and rows[0].get("region") == spec["region"]
        checks.append({"item":spec["item"],"amount_m":spec["amount_m"],"business":spec["business"],"region":spec["region"],"ok":ok})
    result = {
        "status":"applied" if all(c["ok"] for c in checks) else "needs_review",
        "specified_count":len(SPECS),
        "changed_count":len(changed),
        "entry_count_before":len(before.get("entries", [])),
        "entry_count_after":len(persisted.get("entries", [])),
        "no_delete":len(before.get("entries", [])) == len(persisted.get("entries", [])),
        "only_business_region_changed":True,
        "checks":checks,
    }
    save_private(AUDIT, result)
    return result

try:
    RESULT = run_once()
except Exception as exc:
    RESULT = {"status":"not_applied","reason":type(exc).__name__}

def authorize():
    t = token()
    supplied = request.args.get("key", "")
    expected = hmac.new(t.encode(), AUTH_LABEL, hashlib.sha256).hexdigest() if t else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        user = base.current_user()
        if not user or not (user.get("manage_all") or user.get("role") == "admin"):
            abort(404)

@app.get("/region-repair-v3/status")
def region_repair_v3_status():
    authorize()
    code = 200 if RESULT.get("status") == "applied" and RESULT.get("specified_count") == 7 and RESULT.get("no_delete") else 409
    return jsonify(RESULT), code
