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


# 기존에 정상 동작하는 /comments POST를 이용한다.
# 별도 메뉴/라우트 접근 실패에 의존하지 않는다.
@app.before_request
def global_fcst_comments_bridge():
    if base.request.method != "POST":
        return None
    if base.request.path != "/comments":
        return None
    if base.request.form.get("mode", "") != "global_fcst":
        return None

    user = base.current_user()
    try:
        year = int(base.request.form.get("year", 2026))
        month = int(base.request.form.get("month", 8))
    except ValueError:
        year, month = 2026, 8
    if month < 1 or month > 12:
        month = 8
    back_url = base.url_for("report", year=year, month=month) + "#global-fcst-panel"

    if not user:
        return base.redirect(base.url_for("login", next=back_url))
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
<section id='global-fcst-panel' class='comment-card no-capture' style='border:2px solid #0f3a66;margin:18px 0'>
  <div class='section-head'>
    <div>
      <p class='eyebrow'>GLOBAL MAPS LINK</p>
      <h2>해외 FCST 연결</h2>
      <p>Global Maps 로그인 후 기존 FCST를 읽기만 합니다. Global Maps 데이터·코드·DB는 수정하지 않습니다.</p>
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
    <div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:12px'>
      <button class='btn primary' name='action' value='test' type='submit'>연결 테스트 / 저장</button>
      <button class='btn secondary' name='action' value='delete' type='submit'>저장정보 삭제</button>
    </div>
  </form>
</section>
""".replace("STATUS_TEXT", escape(status)).replace("YEAR_VALUE", str(year)).replace("MONTH_VALUE", str(month)).replace("SAVED_USER", saved_user)


# app.py의 report()가 호출하는 render_template 자체를 감싼다.
# 응답 후처리/별도 Gunicorn hook이 아니라 실제 템플릿 렌더링 결과에 직접 넣는다.
_original_render_template = base.render_template


def render_template_with_fcst(template_name, *args, **kwargs):
    rendered = _original_render_template(template_name, *args, **kwargs)
    if template_name != "report.html":
        return rendered

    user = base.current_user()
    if not can_manage_fcst(user):
        return rendered
    if base.request.args.get("capture") == "1":
        return rendered

    report = kwargs.get("report")
    year = getattr(report, "year", None) if report is not None else None
    month = getattr(report, "month", None) if report is not None else None
    if isinstance(report, dict):
        year = report.get("year", year)
        month = report.get("month", month)
    try:
        year = int(year or base.request.args.get("year", 2026))
    except (TypeError, ValueError):
        year = 2026
    try:
        month = int(month or base.request.args.get("month", 8))
    except (TypeError, ValueError):
        month = 8
    if month < 1 or month > 12:
        month = 8

    panel = build_fcst_panel(year, month)
    marker = '<section class="comment-card no-capture" id="report-writer">'
    if marker in rendered and "id='global-fcst-panel'" not in rendered:
        rendered = rendered.replace(marker, panel + marker, 1)

    nav_link = "<a href='#global-fcst-panel'>해외 FCST 연결</a>"
    if nav_link not in rendered and "</nav>" in rendered:
        rendered = rendered.replace("</nav>", nav_link + "</nav>", 1)

    toolbar_marker = '<a class="btn secondary" href="#report-writer">실적자료 작성</a>'
    toolbar_link = "<a class='btn secondary' href='#global-fcst-panel'>해외 FCST 연결</a>"
    if toolbar_marker in rendered and toolbar_link not in rendered:
        rendered = rendered.replace(toolbar_marker, toolbar_marker + toolbar_link, 1)

    return rendered


base.render_template = render_template_with_fcst


# 상태 확인용. 새 실행 진입점이 로드되지 않으면 이 값이 나오지 않는다.
_original_health = app.view_functions.get("health")


def health_fcst_entry_v4():
    response = _original_health()
    try:
        data = response.get_json(silent=True) or {}
        data["global_fcst_entry_v4"] = True
        data["global_fcst_main_inline"] = True
        return base.jsonify(data)
    except Exception:
        return response


if _original_health is not None:
    app.view_functions["health"] = health_fcst_entry_v4


# 앱 시작 시 mp001 실제 세션으로 메인 HTML을 렌더링해 메뉴/박스가 없으면 배포 자체를 실패시킨다.
try:
    _client = app.test_client()
    with _client.session_transaction() as _sess:
        _sess["user_id"] = "mp001"
    _resp = _client.get("/?year=2026&month=8&fcstcheck=1")
    _html = _resp.get_data(as_text=True)
    assert _resp.status_code == 200
    assert "해외 FCST 연결" in _html
    assert "id='global-fcst-panel'" in _html
    assert "name='mode' value='global_fcst'" in _html
    print("GLOBAL_FCST_MAIN_INLINE_V4_OK")
except Exception as _exc:
    raise RuntimeError("GLOBAL_FCST_MAIN_INLINE_V4_FAILED: " + str(_exc))
