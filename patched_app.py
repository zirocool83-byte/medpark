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
        tag = tag.lower()
        if tag == "form":
            self.current = {
                "action": attrs.get("action", ""),
                "method": attrs.get("method", "post").lower(),
                "inputs": [],
            }
        elif tag == "input" and self.current is not None:
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
        with open(GLOBAL_FCST_AUTH_FILE, "r", encoding="utf-8") as handle:
            raw = handle.read().strip()
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


def delete_credentials():
    if os.path.exists(GLOBAL_FCST_AUTH_FILE):
        os.remove(GLOBAL_FCST_AUTH_FILE)


def pick_login_form(html_text):
    parser = LoginFormParser()
    parser.feed(html_text)
    for form in parser.forms:
        if any(
            item.get("type") == "password" and item.get("name")
            for item in form.get("inputs", [])
        ):
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
        raise ValueError("Global Maps 로그인 정보를 입력하세요.")

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
        api_url, headers={"Accept": "application/json"}, method="GET"
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
        if "text/html" in content_type.lower() or "<html" in text[:300].lower():
            raise RuntimeError("FCST API 대신 로그인/HTML 화면이 반환되었습니다.") from exc
        raise RuntimeError("Global Maps FCST 응답이 JSON이 아닙니다.") from exc


def payload_summary(payload):
    rows = None
    rows_key = ""
    keys = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        keys = sorted(str(key) for key in payload.keys())[:50]
        for key in ("rows", "data", "items", "results", "fcst", "forecasts"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                rows_key = key
                break
    row_count = len(rows) if rows is not None else None
    row_keys = []
    if rows and isinstance(rows[0], dict):
        row_keys = sorted(str(key) for key in rows[0].keys())[:80]
    return {
        "type": type(payload).__name__,
        "keys": keys,
        "rows_key": rows_key,
        "row_count": row_count,
        "row_keys": row_keys,
    }


_original_save_comments = app.view_functions.get("save_comments")


@base.admin_required
def save_comments_bridge():
    mode = base.request.form.get("mode", "")
    if mode != "global_fcst":
        return _original_save_comments()

    year = base.request.form.get("year", "2026")
    month = base.request.form.get("month", "8")
    action = base.request.form.get("action", "test")
    saved = load_credentials()

    if action == "delete":
        delete_credentials()
        base.flash("Global Maps 연결정보를 삭제했습니다.", "success")
        return base.redirect(base.url_for("report", year=year, month=month))

    username = base.request.form.get("global_username", "").strip()
    password = base.request.form.get("global_password", "")
    if not username and saved:
        username = saved.get("username", "")
    if not password and saved:
        password = saved.get("password", "")

    try:
        payload = fetch_global_fcst(username, password)
        summary = payload_summary(payload)
        count_text = ""
        if summary.get("row_count") is not None:
            count_text = " / 데이터 " + str(summary["row_count"]) + "건"
        base.flash(
            "Global Maps FCST 읽기 연결 성공" + count_text + ". Global Maps는 변경하지 않았습니다.",
            "success",
        )
        if base.request.form.get("save_global") == "1":
            save_credentials(username, password)
            base.flash("연결정보를 공간4에 암호화 저장했습니다.", "success")
    except Exception as exc:
        base.flash("Global Maps FCST 연결 실패: " + str(exc), "error")

    return base.redirect(base.url_for("report", year=year, month=month))


if _original_save_comments is not None:
    app.view_functions["save_comments"] = save_comments_bridge


@app.after_request
def inject_global_fcst_panel(response):
    try:
        if base.request.endpoint != "report":
            return response
        user = base.current_user()
        if not user or user.get("role") != "admin":
            return response
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            return response
        html = response.get_data(as_text=True)
        marker = '<section class="comment-card no-capture" id="report-writer">'
        if marker not in html or "id='global-fcst-panel'" in html:
            return response

        saved = load_credentials()
        saved_user = escape((saved or {}).get("username", ""))
        status = "연결정보 저장됨" if saved else "미연결"
        try:
            year = int(base.request.args.get("year", 2026))
        except ValueError:
            year = 2026
        try:
            month = int(base.request.args.get("month", 8))
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
