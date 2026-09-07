from html import escape

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
def global_fcst_form_bridge():
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
    saved = ext.load_credentials()

    if action == "delete":
        ext.delete_credentials()
        base.flash("Global Maps 연결정보를 삭제했습니다.", "success")
        return base.redirect(back_url)

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
            count_text = " / 데이터 " + str(summary["row_count"]) + "건"
        base.flash(
            "Global Maps FCST 읽기 연결 성공"
            + count_text
            + ". Global Maps는 변경하지 않았습니다.",
            "success",
        )
        if base.request.form.get("save_global") == "1":
            ext.save_credentials(username, password)
            base.flash("연결정보를 공간4에 암호화 저장했습니다.", "success")
    except Exception as exc:
        base.flash("Global Maps FCST 연결 실패: " + str(exc), "error")

    return base.redirect(back_url)


def build_fcst_panel(year, month):
    saved = ext.load_credentials()
    saved_user = escape((saved or {}).get("username", ""))
    status = "연결정보 저장됨" if saved else "미연결"
    return """
<section id='global-fcst-panel' class='comment-card no-capture' style='border:2px solid #0f172a;margin:16px 0'>
  <div class='section-head'>
    <div>
      <p class='eyebrow'>GLOBAL MAPS LINK</p>
      <h2>해외 FCST 연결</h2>
      <p>Global Maps에는 로그인과 FCST 조회(GET)만 수행합니다. 입력·수정·삭제는 하지 않습니다.</p>
    </div>
    <span class='notice'>현재 상태: STATUS_TEXT</span>
  </div>
  <form method='post' action='/comments' class='comment-form'>
    <input type='hidden' name='mode' value='global_fcst'>
    <input type='hidden' name='year' value='YEAR_VALUE'>
    <input type='hidden' name='month' value='MONTH_VALUE'>
    <label>Global Maps 로그인 ID
      <input name='global_username' value='SAVED_USER' autocomplete='username' placeholder='Global Maps ID'>
    </label>
    <label>Global Maps 비밀번호
      <input type='password' name='global_password' autocomplete='current-password' placeholder='저장된 정보가 있으면 비워도 됩니다'>
    </label>
    <label style='display:flex;gap:8px;align-items:center;font-weight:500'>
      <input type='checkbox' name='save_global' value='1' style='width:auto'> 연결 성공 시 공간4에 암호화 저장
    </label>
    <div style='display:flex;gap:8px;flex-wrap:wrap'>
      <button class='btn primary' name='action' value='test' type='submit'>연결 테스트 / 저장</button>
      <button class='btn secondary' name='action' value='delete' type='submit'>저장정보 삭제</button>
    </div>
  </form>
</section>
""".replace("STATUS_TEXT", escape(status)).replace("YEAR_VALUE", str(year)).replace("MONTH_VALUE", str(month)).replace("SAVED_USER", saved_user)


_original_report_view = app.view_functions.get("report")


def report_with_global_fcst(*args, **kwargs):
    result = _original_report_view(*args, **kwargs)
    response = app.make_response(result)

    user = base.current_user()
    if not can_manage_fcst(user):
        return response

    content_type = response.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        return response

    html = response.get_data(as_text=True)
    if "id='global-fcst-panel'" not in html:
        try:
            year = int(base.request.args.get("year", 2026))
        except ValueError:
            year = 2026
        try:
            month = int(base.request.args.get("month", 8))
        except ValueError:
            month = 8
        if month < 1 or month > 12:
            month = 8

        panel = build_fcst_panel(year, month)
        marker = '<section class="report-card">'
        if marker in html:
            html = html.replace(marker, panel + marker, 1)
        else:
            marker = '<section class="comment-card no-capture" id="report-writer">'
            if marker in html:
                html = html.replace(marker, panel + marker, 1)

        nav_link = "<a href='#global-fcst-panel'>해외 FCST 연결</a>"
        if nav_link not in html and "</nav>" in html:
            html = html.replace("</nav>", nav_link + "</nav>", 1)

        response.set_data(html)

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


if _original_report_view is not None:
    app.view_functions["report"] = report_with_global_fcst


_original_health_view = app.view_functions.get("health")


def health_with_fcst_entry():
    response = _original_health_view()
    try:
        data = response.get_json(silent=True) or {}
        data["global_fcst_entry"] = True
        return base.jsonify(data)
    except Exception:
        return response


if _original_health_view is not None:
    app.view_functions["health"] = health_with_fcst_entry
