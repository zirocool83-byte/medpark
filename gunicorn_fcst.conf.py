import runpy
from html import escape

_base_config = runpy.run_path("gunicorn.conf.py")
on_starting = _base_config["on_starting"]
_original_post_worker_init = _base_config["post_worker_init"]


def post_worker_init(worker):
    _original_post_worker_init(worker)

    import app as base
    import patched_app as ext
    from flask import flash, redirect, request, url_for

    def can_manage_fcst(user):
        return bool(
            user
            and (
                user.get("role") == "admin"
                or user.get("permission_type") == "admin"
                or user.get("manage_all")
            )
        )

    existing_save_comments = base.app.view_functions.get("save_comments")

    def save_comments_fcst_runtime():
        if request.form.get("mode", "") != "global_fcst":
            return existing_save_comments()

        user = base.current_user()
        if not user:
            return redirect(url_for("login", next=request.full_path))

        try:
            year = int(request.form.get("year", 2026))
            month = int(request.form.get("month", 8))
        except ValueError:
            year, month = 2026, 8
        if month < 1 or month > 12:
            month = 8

        back_url = url_for("report", year=year, month=month) + "#global-fcst-panel"
        if not can_manage_fcst(user):
            flash("해외 FCST 연결은 전체 관리 권한자만 사용할 수 있습니다.", "error")
            return redirect(back_url)

        action = request.form.get("action", "test")
        saved = ext.load_credentials()

        if action == "delete":
            ext.delete_credentials()
            flash("Global Maps 연결정보를 삭제했습니다.", "success")
            return redirect(back_url)

        username = request.form.get("global_username", "").strip()
        password = request.form.get("global_password", "")
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
            flash(
                "Global Maps FCST 읽기 연결 성공"
                + count_text
                + ". Global Maps는 변경하지 않았습니다.",
                "success",
            )
            if request.form.get("save_global") == "1":
                ext.save_credentials(username, password)
                flash("연결정보를 공간4에 암호화 저장했습니다.", "success")
        except Exception as exc:
            flash("Global Maps FCST 연결 실패: " + str(exc), "error")

        return redirect(back_url)

    if existing_save_comments is not None:
        base.app.view_functions["save_comments"] = save_comments_fcst_runtime

    def inject_manager_fcst_panel(response):
        try:
            if request.endpoint != "report":
                return response
            user = base.current_user()
            if not can_manage_fcst(user):
                return response
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return response

            html = response.get_data(as_text=True)
            marker = '<section class="comment-card no-capture" id="report-writer">'
            if marker not in html or "id='global-fcst-panel'" in html:
                return response

            saved = ext.load_credentials()
            saved_user = escape((saved or {}).get("username", ""))
            status = "연결정보 저장됨" if saved else "미연결"
            try:
                year = int(request.args.get("year", 2026))
            except ValueError:
                year = 2026
            try:
                month = int(request.args.get("month", 8))
            except ValueError:
                month = 8

            panel = """
<section id='global-fcst-panel' class='comment-card no-capture' style='border:2px solid #0f172a'>
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
"""
            panel = panel.replace("STATUS_TEXT", escape(status))
            panel = panel.replace("YEAR_VALUE", str(year))
            panel = panel.replace("MONTH_VALUE", str(month))
            panel = panel.replace("SAVED_USER", saved_user)
            html = html.replace(marker, panel + marker, 1)
            response.set_data(html)
            response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            return response
        return response

    base.app.after_request_funcs.setdefault(None, []).append(inject_manager_fcst_panel)

    existing_health = base.app.view_functions.get("health")

    def health_fcst_runtime():
        response = existing_health()
        try:
            data = response.get_json(silent=True) or {}
            data["global_fcst_bridge"] = True
            return base.jsonify(data)
        except Exception:
            return response

    if existing_health is not None:
        base.app.view_functions["health"] = health_fcst_runtime

    client = base.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = "mp001"
    response = client.get("/?year=2026&month=8")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "해외 FCST 연결" in html
    assert "name='mode' value='global_fcst'" in html
    print("Global FCST bridge passed: mp001 manage_all panel visible and handler active.")
