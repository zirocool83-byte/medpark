import runpy

import fcst_entry as fcst

base = fcst.base
app = fcst.app

# 기존 2025 전년대비 기준값 보강은 있으면 사용하되, 실패해도 운영 앱을 종료시키지 않는다.
try:
    audit = runpy.run_path("gunicorn.conf.py")
    seed_func = audit.get("_seed_data")
    if seed_func:
        seed_func()
except Exception as exc:
    print("Data audit soft warning:", type(exc).__name__, str(exc)[:200])


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


_original_report_data = base.report_data


def _sum_rows(rows, field):
    values = [r.get(field) for r in rows if r.get(field) is not None]
    return sum(values) if values else None


def report_data_runtime(year, month):
    report = _original_report_data(year, month)
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

    # 화면 첫 단에서 바로 볼 회차/사업부 요약을 백엔드에서 계산한다.
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
            if grand.get("second") is not None and grand.get("first") is not None
            else None
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
            "delta_12": (
                second_total - first_total
                if second_total is not None and first_total is not None
                else None
            ),
        })
    report["business_cards"] = business_cards
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


# Global FCST POST는 fcst_entry의 before_request가 먼저 처리한다.
app.view_functions["save_comments"] = save_comments_runtime


_original_health = app.view_functions.get("health")


def health_production():
    try:
        data = base.read_store()
        return base.jsonify({
            "status": "ok",
            "initialized": bool(data.get("meta", {}).get("initialized")),
            "users": len(data.get("users", [])),
            "entries": len(data.get("entries", [])),
            "actuals": len(data.get("actuals", {})),
            "seed_version": data.get("meta", {}).get("seed_version", ""),
            "production_entry": "v2-dashboard",
            "global_fcst": fcst.load_fcst_status(),
        })
    except Exception:
        if _original_health:
            return _original_health()
        return base.jsonify({"status": "error"}), 500


app.view_functions["health"] = health_production

print("Production entry loaded: dashboard summaries, September default and Global FCST bridge active.")
