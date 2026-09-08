"""One-time, guarded correction of the Sep second-round manual overseas batch."""
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
from datetime import datetime, timezone

import salesops_api_patch as active
from flask import abort, jsonify, request

app = active.app
base = active.base
KEY = "region_correction_20260908_v2"
AUDIT = Path(base.DATA_DIR) / (KEY + ".audit.json")
BACKUP = Path(base.DATA_DIR) / (KEY + ".before.json")
AUTH_LABEL = b"region-correction-20260908-v2-read-only"
GUARD = "1787039fdffe192caed7cf1e87b061a3073891246dccf2b753426f1752ceb78e"

def token():
    return os.environ.get("PERFORMANCE_READ_ONLY_TOKEN", "").strip()

def digest(x):
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def period(e):
    return str(e.get("year")) == "2026" and str(e.get("month")) in ("9", "09") and e.get("stage") == "2차"

def owners(data):
    return {"mp001"} | {str(u.get("user_id", "")).lower() for u in data.get("users", []) if u.get("permission_type") == "overseas_all"}

def in_batch(e):
    text = str(e.get("updated_at") or "").strip()
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=datetime.now().astimezone().tzinfo)
        stamp = stamp.astimezone(timezone.utc)
        return datetime(2026, 9, 8, 10, 25, tzinfo=timezone.utc) <= stamp <= datetime(2026, 9, 8, 11, 15, 47, tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False

def candidates(data):
    allowed = owners(data)
    return [e for e in data.get("entries", []) if period(e) and in_batch(e) and e.get("region") == "국내" and e.get("seeded") is False and str(e.get("user_id", "")).lower() in allowed and e.get("business") in base.BUSINESSES and e.get("kind") in base.KINDS]

def guard(rows):
    values = [base.money_m(sum(base.int_value(e.get("amount")) for e in rows if e.get("business") == "덴탈" and e.get("kind") == k and e.get("status") in base.COUNT_STATUSES)) for k in base.KINDS]
    return hmac.new(token().encode(), ("sep2-dental|" + "|".join(values)).encode(), hashlib.sha256).hexdigest()

def private_json(path, value):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

def known_missing(data):
    present = {str(e.get("id")) for e in data.get("entries", [])}
    missing = []
    for key in ("region_fix_20260908_sep_second_overseas", "region_fix_20260908_sep_second_recent_manual"):
        old = data.get("meta", {}).get(key, {})
        if isinstance(old, dict):
            missing.extend(str(e.get("id")) for e in old.get("moved", []) if e.get("id") and str(e.get("id")) not in present)
    return sorted(set(missing))

def prepare(data):
    rows = candidates(data)
    if not rows or not token() or not hmac.compare_digest(guard(rows), GUARD):
        return None, {"status": "not_applied", "reason": "source_values_not_verified", "candidate_count": len(rows)}
    ids = [str(e.get("id", "")) for e in rows]
    all_ids = [str(e.get("id", "")) for e in data.get("entries", [])]
    if any(not x for x in ids) or len(set(all_ids)) != len(all_ids):
        return None, {"status": "not_applied", "reason": "invalid_or_duplicate_ids"}
    selected = set(ids)
    after = copy.deepcopy(data)
    for e in after["entries"]:
        if str(e.get("id")) in selected:
            e["region"] = "해외"
    restored = copy.deepcopy(after)
    for e in restored["entries"]:
        if str(e.get("id")) in selected:
            e["region"] = "국내"
    if restored != data or len(after["entries"]) != len(data["entries"]):
        raise ValueError("preservation_check_failed")
    result = {"status": "applied", "applied_at": base.now_text(), "before_hash": digest(data), "after_hash": digest(after), "moved_count": len(ids), "moved_ids": ids, "before_count": len(data["entries"]), "after_count": len(after["entries"]), "known_prior_missing": known_missing(data), "backup_file": BACKUP.name, "only_region_changed": True}
    return after, result

def run_once():
    if AUDIT.exists():
        with AUDIT.open(encoding="utf-8") as f:
            return json.load(f)
    with open(base.DATA_FILE, encoding="utf-8") as f:
        before = json.load(f)
    after, result = prepare(before)
    if after is None:
        return result
    if not BACKUP.exists():
        private_json(BACKUP, before)
    else:
        with BACKUP.open(encoding="utf-8") as f:
            saved = json.load(f)
        if digest(saved) != digest(before):
            return {"status": "not_applied", "reason": "existing_backup_differs"}
    with open(base.DATA_FILE, encoding="utf-8") as f:
        latest = json.load(f)
    if digest(latest) != digest(before):
        return {"status": "not_applied", "reason": "concurrent_update"}
    base.write_store(after)
    with open(base.DATA_FILE, encoding="utf-8") as f:
        persisted = json.load(f)
    if persisted != after:
        return {"status": "needs_review", "reason": "post_write_verification_failed"}
    private_json(AUDIT, result)
    return result

try:
    RESULT = run_once()
except Exception as exc:
    RESULT = {"status": "not_applied", "reason": type(exc).__name__}

def authorize():
    t = token()
    supplied = request.args.get("key", "")
    expected = hmac.new(t.encode(), AUTH_LABEL, hashlib.sha256).hexdigest() if t else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        user = base.current_user()
        if not user or not (user.get("manage_all") or user.get("role") == "admin"):
            abort(404)

def checks():
    data = base.read_store()
    result = dict(RESULT)
    ok = result.get("status") == "applied" and bool(result.get("moved_count"))
    preserved = False
    visible = False
    coverage = {}
    if ok and BACKUP.exists():
        with BACKUP.open(encoding="utf-8") as f:
            before = json.load(f)
        reverted = copy.deepcopy(data)
        selected = set(result["moved_ids"])
        by_id = {str(e.get("id")): e for e in data["entries"]}
        locations_ok = all(i in by_id and by_id[i].get("region") == "해외" for i in selected)
        for e in reverted["entries"]:
            if str(e.get("id")) in selected:
                e["region"] = "국내"
        preserved = locations_ok and reverted == before
        report = active.ui.report_data(2026, 9)
        index = {(r.get("business"), r.get("region"), r.get("kind")): r for r in report["rows"] if not r.get("is_total")}
        visible = True
        for b in base.BUSINESSES:
            for k in base.KINDS:
                rows = [e for e in data["entries"] if period(e) and e.get("region") == "해외" and e.get("business") == b and e.get("kind") == k]
                coverage[b + "|" + k] = bool(rows)
                expected = sum(base.int_value(e.get("amount")) for e in rows if e.get("status") in base.COUNT_STATUSES) if rows else None
                if index.get((b, "해외", k), {}).get("second") != expected:
                    visible = False
        admin = next((u for u in data.get("users", []) if str(u.get("user_id", "")).lower() == "mp001"), None)
        with app.test_request_context("/?year=2026&month=9"):
            normal = active.ui.render_report(report, admin or {"display_name": "관리자"}, False)
        with app.test_request_context("/?year=2026&month=9&capture=1"):
            capture = active.ui.render_report(report, admin or {"display_name": "관리자"}, True)
        visible = visible and "<table" in normal and "<table" in capture
    result.update({"preserved": preserved, "display_verified": visible, "coverage": coverage})
    return result

@app.get("/region-repair-v2/status")
def region_repair_v2_status():
    authorize()
    try:
        result = checks()
    except Exception as exc:
        return jsonify(status="needs_review", reason=type(exc).__name__), 409
    check = request.args.get("check", "complete")
    if check == "applied":
        passed = result.get("status") == "applied"
    elif check == "preserved":
        passed = result.get("preserved", False)
    elif check == "display":
        passed = result.get("display_verified", False)
    elif check == "known_missing":
        passed = not result.get("known_prior_missing", [])
    elif check == "coverage":
        passed = all(result.get("coverage", {}).values()) and len(result.get("coverage", {})) == 6
    elif check == "count":
        try:
            passed = result.get("moved_count", 0) == int(request.args.get("expected", "-1"))
        except ValueError:
            passed = False
    else:
        passed = result.get("preserved", False) and result.get("display_verified", False) and not result.get("known_prior_missing", [])
    return jsonify(result), (200 if passed else 409)
