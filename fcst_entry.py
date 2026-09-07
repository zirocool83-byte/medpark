import json

import patched_app as ext

base = ext.base
app = ext.app


def can_manage_fcst(user):
    return bool(
        user
        and (
            user.get("role") == "admin"
            or user.get("permission_type") == "admin"
            or user.get("manage_all")
        )
    )


@app.before_request
def global_fcst_comments_bridge():
    if base.request.method != "POST":
        return None
    if base.request.path != "/comments":
        return None
    if base.request.form.get("mode", "") != "global_fcst":
        return None

    user = base.current_user()
    if not user:
        return base.redirect(base.url_for("login", next=base.request.full_path))

    try:
        year = int(base.request.form.get("year", 2026))
        month = int(base.request.form.get("month", 8))
    except ValueError:
        year, month = 2026, 8
    if month < 1 or month > 12:
        month = 8

    back_url = base.url_for("report", year=year, month=month) + "#global-fcst-panel"

    if not can_manage_fcst(user):
        base.flash("해외 FCST 연결은 전체 관리 권한자만 사용할 수 있습니다.", "error")
        return base.redirect(back_url)

    action = base.request.form.get("action", "test")
    if action == "delete":
        ext.delete_credentials()
        base.flash("Global Maps 연결정보를 삭제했습니다.", "success")
        return base.redirect(back_url)

    saved = ext.load_credentials()
    username = base.request.form.get("global_username", "").strip()
    password = base.request.form.get("global_password", "")
    if not username and saved:
        username = saved.get("username", "")
    if not password and saved:
        password = saved.get("password", "")

    try:
        payload = ext.fetch_global_fcst(username, password)
        summary = ext.payload_summary(payload)
        count_text = ""
        if summary.get("row_count") is not None:
            count_text = " / 데이터 " + str(summary.get("row_count")) + "건"
        base.flash(
            "Global Maps FCST 읽기 연결 성공" + count_text + ". Global Maps는 변경하지 않았습니다.",
            "success",
        )
        if base.request.form.get("save_global") == "1":
            ext.save_credentials(username, password)
            base.flash("연결정보를 공간4에 암호화 저장했습니다.", "success")
    except Exception as exc:
        base.flash("Global Maps FCST 연결 실패: " + str(exc), "error")

    return base.redirect(back_url)


@app.route("/fcst-connect", methods=["GET"])
def fcst_connect_fallback():
    user = base.current_user()
    if not user:
        return base.redirect(base.url_for("login", next="/"))
    if not can_manage_fcst(user):
        return base.redirect(base.url_for("report"))
    return base.redirect(base.url_for("report") + "#global-fcst-panel")


_original_health = app.view_functions.get("health")


def health_fcst_entry_v5():
    response = _original_health()
    try:
        data = response.get_json(silent=True) or {}
        data["global_fcst_entry_v5"] = True
        data["global_fcst_mode"] = "main_page_comments_bridge"
        return base.jsonify(data)
    except Exception:
        return response


if _original_health is not None:
    app.view_functions["health"] = health_fcst_entry_v5
