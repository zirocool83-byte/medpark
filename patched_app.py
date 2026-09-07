import base64
import hashlib
import hmac
import http.cookiejar
import json
import os
import secrets
import struct
import urllib.error
import urllib.parse
import urllib.request
from html import escape
from html.parser import HTMLParser

import app as base


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


base.scope_pairs = scope_pairs
base.can_edit_entry = can_edit_entry
app = base.app

# Global Maps FCST: read-only bridge. This module never sends write requests
# to Global Maps; it only logs in and performs a GET on the existing FCST API.
GLOBAL_MAPS_BASE_URL = os.environ.get(
    "GLOBAL_MAPS_BASE_URL", "https://medprk-medpark-global-maps.mycafe24.ai"
).rstrip("/")
GLOBAL_MAPS_FCST_PATH = os.environ.get(
    "GLOBAL_MAPS_FCST_PATH", "/api/monthly_sales_fcst"
)
GLOBAL_FCST_AUTH_FILE = os.path.join(base.DATA_DIR, ".global_fcst_auth")


class LoginFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "form":
            self.current = {
                "action": attrs.get("action", ""),
                "method": attrs.get("method", "post").lower(),
                "inputs": [],
            }
        elif tag.lower() == "input" and self.current is not None:
            self.current["inputs"].append(
                {
                    "name": attrs.get("name", ""),
                    "type": attrs.get("type", "text").lower(),
                    "value": attrs.get("value", ""),
                }
            )

    def handle_endtag(self, tag):
        if tag.lower() == "form" and self.current is not None:
            self.forms.append(self.current)
            self.current = None


def credential_keys():
    master = hashlib.sha256(str(app.secret_key).encode("utf-8")).digest()
    enc_key = hmac.new(master, b"global-fcst-enc", hashlib.sha256).digest()
    mac_key = hmac.new(master, b"global-fcst-mac", hashlib.sha256).digest()
    return enc_key, mac_key


def seal_credentials(username, password):
    enc_key, mac_key = credential_keys()
    nonce = secrets.token_bytes(16)
    plain = json.dumps(
        {"username": username, "password": password}, ensure_ascii=False
    ).encode("utf-8")
    body = bytearray()
    counter = 0
    for offset in range(0, len(plain), 32):
        block = plain[offset : offset + 32]
        stream = hmac.new(
            enc_key, nonce + struct.pack(">Q", counter), hashlib.sha256
        ).digest()
        body.extend(bytes(a ^ b for a, b in zip(block, stream)))
        counter += 1
    tag = hmac.new(mac_key, nonce + bytes(body), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + bytes(body) + tag).decode("ascii")


def load_credentials():
    if not os.path.exists(GLOBAL_FCST_AUTH_FILE):
        return None
    try:
        raw = open(GLOBAL_FCST_AUTH_FILE, "r", encoding="utf-8").read().strip()
        packed = base64.urlsafe_b64decode(raw.encode("ascii"))
        if len(packed) < 48:
            return None
        nonce = packed[:16]
        body = packed[16:-32]
        tag = packed[-32:]
        enc_key, mac_key = credential_keys()
        expected = hmac.new(mac_key, nonce + body, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            return None
        plain = bytearray()
        counter = 0
        for offset in range(0, len(body), 32):
            block = body[offset : offset + 32]
            stream = hmac.new(
                enc_key, nonce + struct.pack(">Q", counter), hashlib.sha256
            ).digest()
            plain.extend(bytes(a ^ b for a, b in zip(block, stream)))
            counter += 1
        data = json.loads(bytes(plain).decode("utf-8"))
        if data.get("username") and data.get("password"):
            return data
    except Exception:
        return None
    return None


def save_credentials(username, password):
    os.makedirs(base.DATA_DIR, exist_ok=True)
    tmp = GLOBAL_FCST_AUTH_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(seal_credentials(username, password))
    os.chmod(tmp, 0o600)
    os.replace(tmp, GLOBAL_FCST_AUTH_FILE)


def pick_login_form(html_text):
    parser = LoginFormParser()
    parser.feed(html_text)
    for form in parser.forms:
        has_password = any(
            item.get("type") == "password" and item.get("name")
            for item in form.get("inputs", [])
        )
        if has_password:
            return form
    return parser.forms[0] if parser.forms else None


def login_fields(form):
    inputs = [item for item in form.get("inputs", []) if item.get("name")]
    password_field = next(
        (item["name"] for item in inputs if item.get("type") == "password"),
        None,
    )
    by_lower = {item["name"].lower(): item["name"] for item in inputs}
    username_field = None
    for candidate in ("user_id", "username", "login_id", "userid", "email", "id"):
        if candidate in by_lower:
            username_field = by_lower[candidate]
            break
    if not username_field:
        username_field = next(
            (
                item["name"]
                for item in inputs
                if item.get("type") in ("text", "email")
            ),
            None,
        )
    return username_field, password_field


def fetch_global_fcst(username, password, timeout=12):
    if not username or not password:
        raise ValueError("Global Maps 로그인 정보가 없습니다.")

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", "MedPark-Performance-Report/1.0")]
    login_url = GLOBAL_MAPS_BASE_URL + "/login"

    try:
        response = opener.open(login_url, timeout=timeout)
        login_html = response.read().decode("utf-8", "replace")
        response.close()
    except Exception as exc:
        raise RuntimeError(
            "Global Maps 로그인 페이지 접속 실패: " + type(exc).__name__
        ) from exc

    form = pick_login_form(login_html)
    if not form:
        raise RuntimeError("Global Maps 로그인 폼을 찾지 못했습니다.")
    username_field, password_field = login_fields(form)
    if not username_field or not password_field:
        raise RuntimeError("Global Maps 로그인 필드 구조를 확인하지 못했습니다.")

    payload = {}
    for item in form.get("inputs", []):
        name = item.get("name")
        if name and item.get("type") in ("hidden", "submit"):
            payload[name] = item.get("value", "")
    payload[username_field] = username
    payload[password_field] = password

    action_url = urllib.parse.urljoin(login_url, form.get("action") or login_url)
    request_obj = urllib.request.Request(
        action_url,
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        response = opener.open(request_obj, timeout=timeout)
        response.read(256)
        response.close()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            "Global Maps 로그인 실패 (HTTP " + str(exc.code) + ")"
        ) from exc

    api_url = urllib.parse.urljoin(
        GLOBAL_MAPS_BASE_URL + "/", GLOBAL_MAPS_FCST_PATH.lstrip("/")
    )
    api_request = urllib.request.Request(
        api_url, headers={"Accept": "application/json"}
    )
    try:
        response = opener.open(api_request, timeout=timeout)
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
        response.close()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError(
                "Global Maps 인증 실패 (HTTP " + str(exc.code) + ")"
            ) from exc
        raise RuntimeError(
            "Global Maps FCST 조회 실패 (HTTP " + str(exc.code) + ")"
        ) from exc

    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        lower = text[:300].lower()
        if "text/html" in content_type.lower() or "<html" in lower:
            raise RuntimeError("FCST API 대신 로그인/HTML 화면이 반환되었습니다.") from exc
        raise RuntimeError("Global Maps FCST 응답이 JSON이 아닙니다.") from exc


def payload_summary(payload):
    summary = {"type": type(payload).__name__}
    rows = None
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        summary["keys"] = sorted(str(key) for key in payload.keys())[:50]
        for key in ("rows", "data", "items", "results", "fcst", "forecasts"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                summary["rows_key"] = key
                break
    if rows is not None:
        summary["row_count"] = len(rows)
        if rows and isinstance(rows[0], dict):
            summary["row_keys"] = sorted(str(key) for key in rows[0].keys())[:80]
            summary["sample"] = rows[0]
    return summary


@app.route("/global-fcst", methods=["GET", "POST"])
@base.admin_required
def global_fcst_settings():
    saved = load_credentials()
    message = ""
    summary = None
    connected = False

    if base.request.method == "POST":
        action = base.request.form.get("action", "test")
        if action == "delete":
            if os.path.exists(GLOBAL_FCST_AUTH_FILE):
                os.remove(GLOBAL_FCST_AUTH_FILE)
            saved = None
            message = "저장된 Global Maps 연결정보를 삭제했습니다."
        else:
            username = base.request.form.get("username", "").strip()
            password = base.request.form.get("password", "")
            if not username and saved:
                username = saved.get("username", "")
            if not password and saved:
                password = saved.get("password", "")
            try:
                payload = fetch_global_fcst(username, password)
                summary = payload_summary(payload)
                connected = True
                message = "Global Maps FCST 읽기 연결 성공. Global Maps 데이터는 변경하지 않았습니다."
                if base.request.form.get("save") == "1":
                    save_credentials(username, password)
                    saved = {"username": username, "password": password}
                    message += " 연결정보는 공간4에 암호화 저장했습니다."
            except Exception as exc:
                message = str(exc)

    safe_user = escape((saved or {}).get("username", ""))
    safe_message = escape(message)
    if connected:
        status_text = "연결 성공"
    elif saved:
        status_text = "연결정보 저장됨"
    else:
        status_text = "미연결"

    summary_html = ""
    if summary is not None:
        summary_text = json.dumps(summary, ensure_ascii=False, indent=2)
        summary_html = (
            "<pre style='background:#f6f8fa;padding:12px;border-radius:8px;"
            "overflow:auto;white-space:pre-wrap'>"
            + escape(summary_text)
            + "</pre>"
        )
    message_html = ""
    if message:
        message_html = "<div class='msg'>" + safe_message + "</div>"

    return """<!doctype html>
<html lang='ko'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Global Maps FCST 연결</title>
<style>
body{font-family:system-ui,-apple-system,sans-serif;max-width:760px;margin:40px auto;padding:0 18px;color:#1f2937}
.card{border:1px solid #e5e7eb;border-radius:14px;padding:22px;margin:16px 0}
label{display:block;font-weight:700;margin:12px 0 6px}
input{width:100%;box-sizing:border-box;padding:11px;border:1px solid #cbd5e1;border-radius:8px}
button{padding:10px 16px;border:0;border-radius:8px;background:#111827;color:white;font-weight:700;margin-top:12px}
.danger{background:#b91c1c}.note{font-size:14px;color:#475569;line-height:1.6}.msg{padding:12px;background:#f8fafc;border-radius:8px;margin-top:14px}
</style></head><body>
<h1>Global Maps FCST 읽기 전용 연결</h1>
<p class='note'>Global Maps에는 로그인과 FCST GET 조회만 수행합니다. 입력·수정·삭제 요청은 보내지 않습니다.</p>
<div class='card'><b>현재 상태: """ + escape(status_text) + """</b>""" + message_html + summary_html + """</div>
<div class='card'><form method='post'>
<label>Global Maps 로그인 ID</label>
<input name='username' autocomplete='username' value='""" + safe_user + """' placeholder='Global Maps ID'>
<label>Global Maps 비밀번호</label>
<input type='password' name='password' autocomplete='current-password' placeholder='저장된 정보가 있으면 비워도 됩니다'>
<label style='font-weight:500'><input type='checkbox' name='save' value='1' style='width:auto'> 연결 성공 시 공간4에 암호화 저장</label>
<button name='action' value='test'>연결 테스트 / 저장</button>
</form></div>
<div class='card'><form method='post'><button class='danger' name='action' value='delete'>저장된 연결정보 삭제</button></form></div>
<p><a href='/'>실적보고서로 돌아가기</a></p>
</body></html>"""
