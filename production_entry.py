import json
import os

import app as base

app = base.app
_ORIGINAL_REPORT_DATA = base.report_data
STATUS_FILE = os.path.join(base.DATA_DIR, ".global_fcst_status.json")


def money_m(value, blank="-"):
    if value is None:
        return blank
    number = float(value) / 1_000_000
    rounded = round(number, 1)
    if abs(rounded - round(rounded)) < 1e-9:
        return f"{int(round(rounded)):,}"
    return f"{rounded:,.1f}"


app.jinja_env.filters["money_m"] = money_m


def can_manage_report(user):
    return bool(user and (user.get("role") == "admin" or user.get("manage_all")))


def _sum_nullable(rows, key):
    values = [row.get(key) for row in rows if row.get(key) is not None]
    return sum(values) if values else None


def _load_fcst_status():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {
        "connected": False,
        "saved": False,
        "row_count": None,
        "checked_at": "",
        "message": "FCST 연결은 앱 안정화 후 다시 확인",
    }


@app.context_processor
def stable_context():
    return {"global_fcst_status": _load_fcst_status()}


def report_data_stable(year, month):
    report = _ORIGINAL_REPORT_DATA(year, month)
    data = base.read_store()
    key = f"{year}-{month:02d}"
    comments = data.get("comments", {}).get(key, {}) or {}
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

    grand = next((row for row in report.get("rows", []) if row.get("is_grand")), {})
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
            if grand.get("second") is not None and grand.get("first") is not None
            else None
        ),
    }

    cards = []
    details = report.get("details", [])
    for business in base.BUSINESSES:
        business_rows = [row for row in details if row.get("business") == business]
        domestic = [row for row in business_rows if row.get("region") == "국내"]
        overseas = [row for row in business_rows if row.get("region") == "해외"]
        first_total = _sum_nullable(business_rows, "first")
        second_total = _sum_nullable(business_rows, "second")
        cards.append({
            "name": business,
            "first": first_total,
            "second": second_total,
            "third": _sum_nullable(business_rows, "third_forecast"),
            "domestic_first": _sum_nullable(domestic, "first"),
            "domestic_second": _sum_nullable(domestic, "second"),
            "overseas_first": _sum_nullable(overseas, "first"),
            "overseas_second": _sum_nullable(overseas, "second"),
            "delta_12": (
                second_total - first_total
                if second_total is not None and first_total is not None
                else None
            ),
        })
    report["business_cards"] = cards
    return report


base.report_data = report_data_stable


@app.before_request
def september_default():
    if (
        base.request.method == "GET"
        and base.request.path == "/"
        and "month" not in base.request.args
        and base.current_user()
    ):
        return base.redirect(base.url_for("report", year=2026, month=9))
    return None


def save_comments_stable():
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

    mode = base.request.form.get("mode", "overall")
    if mode == "global_fcst":
        base.flash("Global Maps 연동은 앱 안정화 후 다시 연결합니다.", "error")
        return base.redirect(base.url_for("report", year=year, month=month) + "#global-fcst-panel")

    data = base.read_store()
    key = f"{year}-{month:02d}"
    bucket = data.setdefault("comments", {}).setdefault(key, {})
    bucket.setdefault("top", "")
    bucket.setdefault("bottom", "")
    bucket.setdefault("parts", {})

    if mode == "part":
        raw_scope = base.request.form.get("scope", "")
        if "|" not in raw_scope:
            base.flash("담당 파트를 확인하세요.", "error")
            return base.redirect(base.url_for("report", year=year, month=month) + "#report-writer")
        business, region = raw_scope.split("|", 1)
        pair = (business, region)
        allowed = pair in base.ALL_PAIRS and (
            can_manage_report(user) or pair in base.scope_pairs(user)
        )
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
            base.flash("전체 실적자료 수정 권한이 없습니다.", "error")
            return base.redirect(base.url_for("report", year=year, month=month) + "#report-writer")
        bucket["top"] = base.request.form.get("top", "").strip()
        bucket["bottom"] = base.request.form.get("bottom", "").strip()
        bucket["updated_by"] = user.get("display_name", "")
        bucket["updated_at"] = base.now_text()
        base.flash("전체 실적자료를 저장했습니다.", "success")

    base.write_store(data)
    return base.redirect(base.url_for("report", year=year, month=month) + "#report-writer")


app.view_functions["save_comments"] = save_comments_stable


def health_stable():
    data = base.read_store()
    return base.jsonify({
        "status": "ok",
        "runtime": "stable-v1",
        "initialized": bool(data.get("meta", {}).get("initialized")),
        "users": len(data.get("users", [])),
        "entries": len(data.get("entries", [])),
        "actuals": len(data.get("actuals", {})),
    })


app.view_functions["health"] = health_stable
