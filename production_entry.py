import copy
import json
import os

import fcst_entry as fcst

base = fcst.base
app = fcst.app


def can_manage_report(user):
    return bool(user and (user.get("role") == "admin" or user.get("manage_all")))


def money_m(value, blank="-"):
    if value is None:
        return blank
    number = float(value) / 1_000_000
    rounded = round(number, 1)
    if abs(rounded - round(rounded)) < 1e-9:
        return f"{int(round(rounded)):,}"
    return f"{rounded:,.1f}"


app.jinja_env.filters["money_m"] = money_m

# patched_app의 과거 화면 주입 함수는 현재 report.html과 중복될 수 있어 제거한다.
try:
    funcs = app.after_request_funcs.get(None, [])
    app.after_request_funcs[None] = [
        fn for fn in funcs if getattr(fn, "__name__", "") != "inject_global_fcst_panel"
    ]
except Exception:
    pass


def _sum_rows(rows, field):
    values = [r.get(field) for r in rows if r.get(field) is not None]
    return sum(values) if values else None


def _extract_global_rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("rows", "data", "items", "results", "fcst", "forecasts"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _normalize_global_row(raw):
    if not isinstance(raw, dict):
        return None
    try:
        year = int(raw.get("year"))
        month = int(raw.get("month"))
    except (TypeError, ValueError):
        return None
    stage = str(raw.get("stage") or "").strip()
    business = str(raw.get("business") or "").strip()
    region = str(raw.get("region") or "").strip()
    kind = str(raw.get("kind") or "기존").strip()
    status = str(raw.get("status") or ("확정" if stage == "마감" else "예상")).strip()
    if stage not in base.STAGES:
        return None
    if business not in base.BUSINESSES:
        return None
    if region != "해외":
        return None
    if kind not in base.KINDS:
        kind = "기존"
    if status not in base.STATUSES:
        status = "예상"
    try:
        amount = float(raw.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    return {
        "id": str(raw.get("id") or f"global-{year}-{month}-{stage}-{business}-{kind}-{len(str(raw))}"),
        "year": year,
        "month": month,
        "stage": stage,
        "business": business,
        "region": "해외",
        "kind": kind,
        "status": "확정" if stage == "마감" else status,
        "item": str(raw.get("item") or raw.get("product") or raw.get("customer") or "Global Maps FCST"),
        "amount": amount,
        "note": str(raw.get("note") or "Global Maps 연동"),
        "writer": str(raw.get("writer") or "Global Maps"),
        "user_id": str(raw.get("user_id") or "global_maps"),
        "updated_at": str(raw.get("updated_at") or ""),
        "seeded": False,
        "external_source": "global_maps",
    }


def _load_global_overlay():
    try:
        with open(fcst.CACHE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return []
    rows = []
    for raw in _extract_global_rows(payload):
        row = _normalize_global_row(raw)
        if row:
            rows.append(row)
    return rows


def _merged_store():
    data = copy.deepcopy(base.read_store())
    global_rows = _load_global_overlay()
    if not global_rows:
        return data, []

    replace_keys = {
        (r["year"], r["month"], r["stage"], r["business"], r["region"], r["kind"])
        for r in global_rows
    }
    kept = []
    for entry in data.get("entries", []):
        key = (
            entry.get("year"), entry.get("month"), entry.get("stage"),
            entry.get("business"), entry.get("region"), entry.get("kind"),
        )
        if key in replace_keys and entry.get("region") == "해외":
            continue
        kept.append(entry)
    data["entries"] = kept + global_rows
    return data, global_rows


def _report_from_data(year, month, data):
    details, display = [], []
    for business in base.BUSINESSES:
        group = []
        for region in base.REGIONS:
            for kind in base.KINDS:
                row = base.row_metrics(data, year, month, business, region, kind)
                details.append(row)
                group.append(row)
                display.append(row)
        display.append(base.sum_rows(group, f"{business} 소계", business))
    grand = base.sum_rows(details, f"{year}년 전체")
    display.append(grand)

    parts = []
    for business in base.BUSINESSES:
        for region in base.REGIONS:
            part_rows = [x for x in details if x["business"] == business and x["region"] == region]
            parts.append({"name": f"{business} {region}", "done": all(x["close_has"] for x in part_rows)})
    close_done = sum(1 for p in parts if p["done"])
    third_total = grand["third_forecast"]
    close_total = grand["close"] if grand["close_has"] else None
    diff = close_total - third_total if close_total is not None and third_total is not None else None
    error_rate = abs(diff) / third_total if diff is not None and third_total else None
    return {
        "year": year, "month": month, "rows": display, "details": details,
        "parts": parts, "close_done": close_done, "close_total": close_total,
        "third_total": third_total, "diff": diff, "error_rate": error_rate,
        "prev_month": 12 if month == 1 else month - 1,
        "next_month": 1 if month == 12 else month + 1,
        "quarter": (month - 1) // 3 + 1,
    }


def report_data_runtime(year, month):
    merged, global_rows = _merged_store()
    report = _report_from_data(year, month, merged)

    local_data = base.read_store()
    key = f"{year}-{month:02d}"
    comments = local_data.get("comments", {}).get(key, {}) or {}
    comments.setdefault("top", "")
    comments.setdefault("bottom", "")
    comments.setdefault("parts", {})
    report["comments"] = comments

    user = base.current_user()
    manage_all = can_manage_report(user)
    editable_pairs = set(base.ALL_PAIRS if manage_all else base.scope_pairs(user))
    part_notes = []
    any_part_notes = False
    for business in base.BUSINESSES:
        for region in base.REGIONS:
            note_key = f"{business}|{region}"
            saved = comments.get("parts", {}).get(note_key, {}) or {}
            summary = str(saved.get("summary", "") or "").strip()
            risk = str(saved.get("risk", "") or "").strip()
            action = str(saved.get("action", "") or "").strip()
            has_note = bool(summary or risk or action)
            any_part_notes = any_part_notes or has_note
            part_notes.append({
                "key": note_key,
                "business": business,
                "region": region,
                "name": f"{business} {region}",
                "summary": summary,
                "risk": risk,
                "action": action,
                "updated_by": saved.get("updated_by", ""),
                "updated_at": saved.get("updated_at", ""),
                "has": has_note,
                "can_edit": (business, region) in editable_pairs,
            })
    report["part_notes"] = part_notes
    report["has_part_notes"] = any_part_notes
    report["can_manage_report"] = manage_all

    grand = next((r for r in report.get("rows", []) if r.get("is_grand")), {})
    report["dashboard"] = {
        "prev_close": grand.get("prev_close"),
        "first": grand.get("first"),
        "second": grand.get("second"),
        "third_confirmed": grand.get("third_confirmed"),
        "third_forecast": grand.get("third_forecast"),
        "close": grand.get("close"),
        "next_first": grand.get("next_first"),
        "delta_12": (
            grand.get("second") - grand.get("first")
            if grand.get("second") is not None and grand.get("first") is not None else None
        ),
    }

    business_cards = []
    details = report.get("details", [])
    for business in base.BUSINESSES:
        business_rows = [r for r in details if r.get("business") == business]
        domestic_rows = [r for r in business_rows if r.get("region") == "국내"]
        overseas_rows = [r for r in business_rows if r.get("region") == "해외"]
        first_total = _sum_rows(business_rows, "first")
        second_total = _sum_rows(business_rows, "second")
        business_cards.append({
            "name": business,
            "first": first_total,
            "second": second_total,
            "third": _sum_rows(business_rows, "third_forecast"),
            "domestic_second": _sum_rows(domestic_rows, "second"),
            "overseas_second": _sum_rows(overseas_rows, "second"),
            "domestic_first": _sum_rows(domestic_rows, "first"),
            "overseas_first": _sum_rows(overseas_rows, "first"),
            "delta_12": second_total - first_total if second_total is not None and first_total is not None else None,
        })
    report["business_cards"] = business_cards

    current_global = [
        r for r in global_rows
        if r["year"] == year and r["month"] == month and r["stage"] == "2차"
    ]
    counted_global = [r for r in current_global if r.get("status") in base.COUNT_STATUSES]
    report["global_overlay"] = {
        "applied_rows": len(global_rows),
        "current_stage_rows": len(current_global),
        "current_stage_amount": sum(r.get("amount", 0) for r in counted_global),
        "businesses": sorted({r.get("business") for r in current_global if r.get("business")}),
        "active": bool(global_rows),
    }
    return report


base.report_data = report_data_runtime


def save_comments_runtime():
    user = base.current_user()
    if not user:
        return base.redirect(base.url_for("login", next=base.request.full_path))
    try:
        year = int(base.request.form.get("year", 2026))
        month = int(base.request.form.get("month", 9))
    except ValueError:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9

    data = base.read_store()
    key = f"{year}-{month:02d}"
    bucket = data.setdefault("comments", {}).setdefault(key, {})
    bucket.setdefault("top", "")
    bucket.setdefault("bottom", "")
    bucket.setdefault("parts", {})
    mode = base.request.form.get("mode", "overall")

    if mode == "part":
        raw_scope = base.request.form.get("scope", "")
        if "|" not in raw_scope:
            base.flash("담당 파트를 확인하세요.", "error")
            return base.redirect(base.url_for("report", year=year, month=month) + "#report-writer")
        business, region = raw_scope.split("|", 1)
        pair = (business, region)
        allowed = pair in base.ALL_PAIRS and (can_manage_report(user) or pair in base.scope_pairs(user))
        if not allowed:
            base.flash("해당 파트의 실적자료 작성 권한이 없습니다.", "error")
            return base.redirect(base.url_for("report", year=year, month=month) + "#report-writer")
        bucket["parts"][raw_scope] = {
            "summary": base.request.form.get("summary", "").strip(),
            "risk": base.request.form.get("risk", "").strip(),
            "action": base.request.form.get("action", "").strip(),
            "updated_by": user.get("display_name", ""),
            "updated_at": base.now_text(),
        }
        base.flash(f"{business} {region} 실적자료를 저장했습니다.", "success")
    else:
        if not can_manage_report(user):
            base.flash("전체 실적자료는 전체관리 권한자만 수정할 수 있습니다.", "error")
            return base.redirect(base.url_for("report", year=year, month=month) + "#report-writer")
        bucket["top"] = base.request.form.get("top", "").strip()
        bucket["bottom"] = base.request.form.get("bottom", "").strip()
        bucket["updated_by"] = user.get("display_name", "")
        bucket["updated_at"] = base.now_text()
        base.flash("전체 실적자료를 저장했습니다.", "success")

    base.write_store(data)
    return base.redirect(base.url_for("report", year=year, month=month) + "#report-writer")


app.view_functions["save_comments"] = save_comments_runtime


def health_production():
    try:
        data = base.read_store()
        overlay = _load_global_overlay()
        sep2 = [r for r in overlay if r.get("year") == 2026 and r.get("month") == 9 and r.get("stage") == "2차"]
        return base.jsonify({
            "status": "ok",
            "initialized": bool(data.get("meta", {}).get("initialized")),
            "users": len(data.get("users", [])),
            "entries": len(data.get("entries", [])),
            "actuals": len(data.get("actuals", {})),
            "seed_version": data.get("meta", {}).get("seed_version", ""),
            "production_entry": "v3-global-overlay",
            "global_fcst": fcst.load_fcst_status(),
            "global_overlay_rows": len(overlay),
            "global_sep2_rows": len(sep2),
        })
    except Exception:
        return base.jsonify({"status": "error"}), 500


app.view_functions["health"] = health_production

print("Production entry loaded: read-only Global Maps overlay + September dashboard active.")
