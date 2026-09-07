import runpy

# 기존 데이터 보강(on_starting)은 그대로 사용하되, 운영 데이터가 늘었다는 이유로
# 워커를 종료시키던 하드코딩 assert 검증은 사용하지 않는다.
_legacy = runpy.run_path("gunicorn.conf.py")
on_starting = _legacy["on_starting"]


def post_worker_init(worker):
    import app as base
    from flask import flash, has_request_context, jsonify, redirect, request, url_for

    def scope_pairs(user):
        if not user:
            return []
        p = user.get("permission_type", "")
        if p == "admin":
            return base.ALL_PAIRS
        if p == "domestic_all":
            return [(b, "국내") for b in base.BUSINESSES]
        if p == "dental_domestic":
            return [("덴탈", "국내")]
        if p == "overseas_all":
            return [(b, "해외") for b in base.BUSINESSES]
        if p == "aesthetics_all":
            return [("에스테틱", "국내"), ("에스테틱", "해외")]
        custom = []
        for item in user.get("scopes", []):
            if isinstance(item, list) and len(item) == 2 and tuple(item) in base.ALL_PAIRS:
                custom.append(tuple(item))
        return custom

    def can_edit_entry(user, entry):
        if not user:
            return False
        if user.get("role") == "admin" or user.get("manage_all"):
            return True
        return (
            entry.get("user_id") == user.get("user_id")
            and (entry.get("business"), entry.get("region")) in scope_pairs(user)
        )

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

    def setup_redirect():
        return redirect(url_for("login"))

    original_report_data = base.report_data

    def report_data_with_notes(year, month):
        report = original_report_data(year, month)
        data = base.read_store()
        key = f"{year}-{month:02d}"
        comments = data.get("comments", {}).get(key, {})
        comments.setdefault("top", "")
        comments.setdefault("bottom", "")
        comments.setdefault("parts", {})
        report["comments"] = comments

        user = base.current_user() if has_request_context() else None
        manage_all = can_manage_report(user)
        editable_pairs = set(base.ALL_PAIRS if manage_all else scope_pairs(user))
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
        return report

    def save_comments_runtime():
        user = base.current_user()
        if not user:
            return redirect(url_for("login", next=request.full_path))

        try:
            year = int(request.form.get("year", 2026))
            month = int(request.form.get("month", 9))
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
        mode = request.form.get("mode", "overall")

        if mode == "part":
            raw_scope = request.form.get("scope", "")
            if "|" not in raw_scope:
                flash("담당 파트를 확인하세요.", "error")
                return redirect(url_for("report", year=year, month=month) + "#report-writer")
            business, region = raw_scope.split("|", 1)
            pair = (business, region)
            allowed = pair in base.ALL_PAIRS and (can_manage_report(user) or pair in scope_pairs(user))
            if not allowed:
                flash("해당 파트의 실적자료 작성 권한이 없습니다.", "error")
                return redirect(url_for("report", year=year, month=month) + "#report-writer")
            bucket["parts"][raw_scope] = {
                "summary": request.form.get("summary", "").strip(),
                "risk": request.form.get("risk", "").strip(),
                "action": request.form.get("action", "").strip(),
                "updated_by": user.get("display_name", ""),
                "updated_at": base.now_text(),
            }
            flash(f"{business} {region} 실적자료를 저장했습니다.", "success")
        else:
            if not can_manage_report(user):
                flash("전체 실적자료는 전체관리 권한자만 수정할 수 있습니다.", "error")
                return redirect(url_for("report", year=year, month=month) + "#report-writer")
            bucket["top"] = request.form.get("top", "").strip()
            bucket["bottom"] = request.form.get("bottom", "").strip()
            bucket["updated_by"] = user.get("display_name", "")
            bucket["updated_at"] = base.now_text()
            flash("전체 실적자료를 저장했습니다.", "success")

        base.write_store(data)
        return redirect(url_for("report", year=year, month=month) + "#report-writer")

    def health_runtime():
        data = base.read_store()
        return jsonify({
            "status": "ok",
            "initialized": bool(data.get("meta", {}).get("initialized")),
            "users": len(data.get("users", [])),
            "entries": len(data.get("entries", [])),
            "actuals": len(data.get("actuals", {})),
            "seed_version": data.get("meta", {}).get("seed_version", ""),
            "data_audit_version": data.get("meta", {}).get("data_audit_version", ""),
            "display_unit": "KRW_million",
            "report_writer": True,
            "runtime_patch": "safe-v1",
        })

    base.scope_pairs = scope_pairs
    base.can_edit_entry = can_edit_entry
    base.report_data = report_data_with_notes
    base.app.jinja_env.filters["money_m"] = money_m
    base.app.view_functions["setup"] = setup_redirect
    base.app.view_functions["health"] = health_runtime
    base.app.view_functions["save_comments"] = save_comments_runtime

    # 운영 워커를 죽이지 않는 소프트 검증. 문제는 로그로만 남긴다.
    try:
        data = base.read_store()
        client = base.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = "mp001"
        response = client.get("/?year=2026&month=8")
        html = response.get_data(as_text=True)
        ok = response.status_code == 200 and "실적자료 작성" in html and "단위: 백만원" in html
        print(
            "Safe runtime check:",
            "OK" if ok else "WARN",
            f"users={len(data.get('users', []))}",
            f"actuals={len(data.get('actuals', {}))}",
            f"entries={len(data.get('entries', []))}",
        )
    except Exception as exc:
        print("Safe runtime check WARN:", type(exc).__name__, str(exc)[:200])
