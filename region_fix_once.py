from production_entry import app, read_store, write_store, now_text

FIX_KEY = "region_fix_20260908_sep_second_overseas"

data = read_store()
meta = data.setdefault("meta", {})
result = meta.get(FIX_KEY)

if not result:
    overseas_users = {
        str(u.get("user_id", "")).strip()
        for u in data.get("users", [])
        if u.get("permission_type") == "overseas_all" and u.get("active", True)
    }
    moved = []
    for entry in data.get("entries", []):
        if entry.get("year") != 2026 or entry.get("month") != 9 or entry.get("stage") != "2차":
            continue
        if entry.get("region") != "국내":
            continue
        if entry.get("seeded") is True:
            continue
        if str(entry.get("user_id", "")).strip() not in overseas_users:
            continue
        if not str(entry.get("updated_at", "")).startswith("2026-09-08"):
            continue
        entry["region"] = "해외"
        entry["region_fix_from"] = "국내"
        entry["region_fix_at"] = now_text()
        moved.append({
            "id": entry.get("id"),
            "user_id": entry.get("user_id"),
            "business": entry.get("business"),
            "kind": entry.get("kind"),
            "amount": entry.get("amount"),
        })
    result = {
        "applied_at": now_text(),
        "moved_count": len(moved),
        "moved": moved,
        "rule": "2026-09 2차 / 국내 / 수기 / 2026-09-08 / overseas_all user -> 해외",
    }
    meta[FIX_KEY] = result
    write_store(data)

@app.get("/region-fix-status")
def region_fix_status():
    current = read_store().get("meta", {}).get(FIX_KEY, {})
    moved = current.get("moved", []) if isinstance(current, dict) else []
    return {
        "status": "ok",
        "applied_at": current.get("applied_at") if isinstance(current, dict) else None,
        "moved_count": current.get("moved_count", 0) if isinstance(current, dict) else 0,
        "businesses": sorted({str(x.get("business")) for x in moved if x.get("business")}),
        "kinds": sorted({str(x.get("kind")) for x in moved if x.get("kind")}),
    }
