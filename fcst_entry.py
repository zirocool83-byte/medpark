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


def fcst_page(message="", summary=None):
    user = base.current_user()
    marker = "GLOBAL_FCST_CONNECT_V3"

    if not user:
        login_url = base.url_for("login", next="/fcst-connect")
        return """<!doctype html>
<html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>해외 FCST 연결</title>
<style>body{font-family:system-ui,-apple-system,sans-serif;max-width:720px;margin:40px auto;padding:0 18px;color:#1f2937}.card{border:1px solid #e5e7eb;border-radius:14px;padding:22px}.btn{display:inline-block;padding:11px 16px;border-radius:8px;background:#0f172a;color:#fff;text-decoration:none;font-weight:700}</style>
</head><body><div style='display:none'>""" + marker + """</div><div class='card'><h1>해외 FCST 연결</h1><p>공간4 로그인이 필요합니다.</p><a class='btn' href='""" + escape(login_url) + """'>로그인</a></div></body></html>"""

    if not can_manage_fcst(user):
        return """<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>해외 FCST 연결</title></head><body><div style='display:none'>""" + marker + """</div><h2>해외 FCST 연결</h2><p>전체 관리 권한이 필요합니다.</p><p><a href='/'>실적회의로 돌아가기</a></p></body></html>""", 403

    saved = ext.load_credentials()
    saved_user = escape((saved or {}).get("username", ""))
    status = "연결정보 저장됨" if saved else "미연결"
    summary_html = ""
    if summary is not None:
        import json
        summary_html = "<pre>" + escape(json.dumps(summary, ensure_ascii=False, indent=2)) + "</pre>"
    message_html = ""
    if message:
        message_html = "<div class='msg'>" + escape(message) + "</div>"

    return """<!doctype html>
<html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>해외 FCST 연결 · MEDPARK</title>
<style>
body{font-family:system-ui,-apple-system,sans-serif;max-width:760px;margin:32px auto;padding:0 18px;color:#172033;background:#f5f7fb}
.card{background:#fff;border:1px solid #dfe5ee;border-radius:14px;padding:22px;margin:16px 0;box-shadow:0 2px 8px rgba(15,23,42,.04)}
label{display:block;font-weight:700;margin:14px 0 6px}input[type=text],input[type=password]{width:100%;box-sizing:border-box;padding:12px;border:1px solid #cbd5e1;border-radius:8px;font-size:16px}
.btn{padding:11px 16px;border:0;border-radius:8px;background:#0f3a66;color:#fff;font-weight:700;font-size:15px}.secondary{background:#64748b}.danger{background:#b91c1c}.msg{padding:12px;border-radius:8px;background:#eef6ff;margin-top:12px;line-height:1.5}pre{background:#0f172a;color:#e2e8f0;padding:14px;border-radius:8px;overflow:auto;white-space:pre-wrap;font-size:13px}.note{color:#526174;line-height:1.6}.status{font-weight:800}
</style></head><body>
<div style='display:none'>""" + marker + """</div>
<h1>해외 FCST 연결</h1>
<p class='note'>Global Maps에는 로그인과 기존 FCST 조회(GET)만 수행합니다. Global Maps의 데이터·코드·DB는 수정하지 않습니다.</p>
<div class='card'><div class='status'>현재 상태: """ + escape(status) + """</div>""" + message_html + summary_html + """</div>
<div class='card'><form method='post' action='/fcst-connect'>
<label>Global Maps 로그인 ID</label>
<input type='text' name='global_username' autocomplete='username' value='""" + saved_user + """' placeholder='Global Maps ID'>
<label>Global Maps 비밀번호</label>
<input type='password' name='global_password' autocomplete='current-password' placeholder='저장된 정보가 있으면 비워도 됩니다'>
<label style='font-weight:500'><input type='checkbox' name='save_global' value='1'> 연결 성공 시 공간4에 암호화 저장</label>
<div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:14px'>
<button class='btn' name='action' value='test' type='submit'>연결 테스트 / 저장</button>
<button class='btn danger' name='action' value='delete' type='submit'>저장정보 삭제</button>
</div></form></div>
<p><a href='/'>← 실적회의로 돌아가기</a></p>
</body></html>"""


@app.route("/fcst-connect", methods=["GET", "POST"])
def fcst_connect():
    user = base.current_user()
    if base.request.method == "GET":
        return fcst_page()

    if not user:
        return base.redirect(base.url_for("login", next="/fcst-connect"))
    if not can_manage_fcst(user):
        return fcst_page("전체 관리 권한이 필요합니다."), 403

    action = base.request.form.get("action", "test")
    if action == "delete":
        ext.delete_credentials()
        return fcst_page("저장된 Global Maps 연결정보를 삭제했습니다.")

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
        message = "Global Maps FCST 읽기 연결 성공" + count_text + ". Global Maps는 변경하지 않았습니다."
        if base.request.form.get("save_global") == "1":
            ext.save_credentials(username, password)
            message += " 연결정보는 공간4에 암호화 저장했습니다."
        return fcst_page(message, summary)
    except Exception as exc:
        return fcst_page("Global Maps FCST 연결 실패: " + str(exc))


_original_health = app.view_functions.get("health")


def health_fcst_entry_v3():
    response = _original_health()
    try:
        data = response.get_json(silent=True) or {}
        data["global_fcst_entry_v3"] = True
        data["global_fcst_route"] = "/fcst-connect"
        return base.jsonify(data)
    except Exception:
        return response


if _original_health is not None:
    app.view_functions["health"] = health_fcst_entry_v3
