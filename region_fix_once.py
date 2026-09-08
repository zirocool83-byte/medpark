from production_entry import app, read_store, write_store, now_text

FIX_KEY = "region_fix_20260908_sep_second_overseas"
RECENT_FIX_KEY = "region_fix_20260908_sep_second_recent_manual"
CUTOFF = "2026-09-08 19:25:00"

data = read_store()
meta = data.setdefault("meta", {})

# First conservative rule: overseas-only users accidentally saved as domestic.
first_result = meta.get(FIX_KEY)
if not first_result:
    overseas_users = {
        str(u.get("user_id", "")).strip()
        for u in data.get("users", [])
        if u.get("permission_type") == "overseas_all" and u.get("active", True)
    }
    moved = []
    for entry in data.get("entries", []):
        if entry.get("year") != 2026 or entry.get("month") != 9 or entry.get("stage") != "2차":
            continue
        if entry.get("region") != "국내" or entry.get("seeded") is True:
            continue
        if str(entry.get("user_id", "")).strip() not in overseas_users:
            continue
        if not str(entry.get("updated_at", "")).startswith("2026-09-08"):
            continue
        entry["region"] = "해외"
        entry["region_fix_from"] = "국내"
        entry["region_fix_at"] = now_text()
        moved.append({"id":entry.get("id"),"user_id":entry.get("user_id"),"business":entry.get("business"),"kind":entry.get("kind"),"amount":entry.get("amount")})
    first_result = {"applied_at":now_text(),"moved_count":len(moved),"moved":moved,"rule":"overseas_all user -> 해외"}
    meta[FIX_KEY] = first_result
    write_store(data)

# User-directed correction: entries manually added after 19:25 for Sep 2nd were intended as overseas.
data = read_store()
meta = data.setdefault("meta", {})
recent_result = meta.get(RECENT_FIX_KEY)
if not recent_result:
    moved = []
    for entry in data.get("entries", []):
        if entry.get("year") != 2026 or entry.get("month") != 9 or entry.get("stage") != "2차":
            continue
        if entry.get("region") != "국내" or entry.get("seeded") is True:
            continue
        updated_at = str(entry.get("updated_at", ""))
        if not updated_at or updated_at < CUTOFF:
            continue
        entry["region"] = "해외"
        entry["region_fix_from"] = "국내"
        entry["region_fix_at"] = now_text()
        entry["region_fix_reason"] = "user-directed recent Sep 2nd overseas correction"
        moved.append({"id":entry.get("id"),"user_id":entry.get("user_id"),"business":entry.get("business"),"kind":entry.get("kind"),"amount":entry.get("amount"),"updated_at":updated_at})
    recent_result = {"applied_at":now_text(),"moved_count":len(moved),"moved":moved,"cutoff":CUTOFF,"rule":"2026-09 2차 / 국내 / 수기 / updated_at>=cutoff -> 해외"}
    meta[RECENT_FIX_KEY] = recent_result
    write_store(data)

@app.get("/region-fix-status")
def region_fix_status():
    current = read_store().get("meta", {})
    first = current.get(FIX_KEY, {}) if isinstance(current, dict) else {}
    recent = current.get(RECENT_FIX_KEY, {}) if isinstance(current, dict) else {}
    return {
        "status":"ok",
        "first_moved_count":first.get("moved_count",0) if isinstance(first,dict) else 0,
        "recent_moved_count":recent.get("moved_count",0) if isinstance(recent,dict) else 0,
        "cutoff":recent.get("cutoff") if isinstance(recent,dict) else None,
        "applied_at":recent.get("applied_at") if isinstance(recent,dict) else None,
    }
