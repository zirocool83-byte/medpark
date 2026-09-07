import json
import os
from datetime import datetime

import patched_app as ext

base = ext.base
app = ext.app

STATUS_FILE = os.path.join(base.DATA_DIR, ".global_fcst_status.json")
CACHE_FILE = os.path.join(base.DATA_DIR, "global_fcst_cache.json")


def can_manage_fcst(user):
    return bool(
        user
        and (
            user.get("role") == "admin"
            or user.get("permission_type") == "admin"
            or user.get("manage_all")
        )
    )


def _write_json(path, data):
    os.makedirs(base.DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_fcst_status():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {
        "connected": False,
        "saved": bool(ext.load_credentials()),
        "row_count": None,
        "checked_at": "",
        "message": "아직 연결 테스트 전",
    }


def save_fcst_status(connected, message, summary=None):
    summary = summary or {}
    data = {
        "connected": bool(connected),
        "saved": bool(ext.load_credentials()),
        "row_count": summary.get("row_count"),
        "rows_key": summary.get("rows_key", ""),
        "row_keys": summary.get("row_keys", []),
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": str(message)[:300],
    }
    _write_json(STATUS_FILE, data)
    return data


@app.before_request
def current_meeting_default():
    # 2026-09 현재 실적회의 기준은 9월. 월 파라미터가 없을 때만 9월로 이동한다.
    if base.request.method == "GET" and base.request.path == "/" and "month" not in base.request.args:
        try:
            year = int(base.request.args.get("year", 2026))
        except ValueError:
            year = 2026
        return base.redirect(base.url_for("report", year=year, month=9))
    return None


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
        month = int(base.request.form.get("month", 9))
    except ValueError:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9

    back_url = base.url_for("report", year=year, month=month) + "#global-fcst-panel"

    if not can_manage_fcst(user):
        message = "해외 FCST 연결은 전체 관리 권한자만 사용할 수 있습니다."
        save_fcst_status(False, message)
        base.flash(message, "error")
        return base.redirect(back_url)

    action = base.request.form.get("action", "test")
    if action == "delete":
        ext.delete_credentials()
        for path in (STATUS_FILE, CACHE_FILE):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        base.flash("Global Maps 연결정보와 공간4 캐시를 삭제했습니다.", "success")
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
        # Global Maps는 건드리지 않고 공간4에 응답 사본만 읽기전용 캐시한다.
        _write_json(CACHE_FILE, payload)
        if base.request.form.get("save_global") == "1":
            ext.save_credentials(username, password)
        count_text = ""
        if summary.get("row_count") is not None:
            count_text = " / 데이터 " + str(summary.get("row_count")) + "건"
        message = "Global Maps FCST 연결됨" + count_text
        status = save_fcst_status(True, message, summary)
        status["saved"] = bool(ext.load_credentials())
        _write_json(STATUS_FILE, status)
        base.flash(message + ". Global Maps는 변경하지 않았습니다.", "success")
        if status["saved"]:
            base.flash("연결정보는 공간4에 암호화 저장되어 있습니다.", "success")
    except Exception as exc:
        message = "Global Maps FCST 연결 실패: " + str(exc)
        save_fcst_status(False, message)
        base.flash(message, "error")

    return base.redirect(back_url)


@app.route("/fcst-connect", methods=["GET"])
def fcst_connect_fallback():
    user = base.current_user()
    if not user:
        return base.redirect(base.url_for("login", next="/?year=2026&month=9#global-fcst-panel"))
    if not can_manage_fcst(user):
        return base.redirect(base.url_for("report", year=2026, month=9))
    return base.redirect(base.url_for("report", year=2026, month=9) + "#global-fcst-panel")


@app.context_processor
def inject_global_fcst_state():
    return {"global_fcst_status": load_fcst_status()}


@app.after_request
def show_global_fcst_state(response):
    try:
        if base.request.endpoint != "report":
            return response
        if "text/html" not in response.headers.get("Content-Type", ""):
            return response
        html = response.get_data(as_text=True)
        status = load_fcst_status()
        if status.get("connected"):
            label = "연결됨"
            if status.get("row_count") is not None:
                label += " · 데이터 " + str(status.get("row_count")) + "건"
            if status.get("checked_at"):
                label += " · " + status.get("checked_at")
        else:
            label = status.get("message") or "미연결"
            if len(label) > 80:
                label = label[:80] + "…"
        html = html.replace(
            '<span class="notice">읽기 전용</span>',
            '<span class="notice">' + label.replace("<", "&lt;").replace(">", "&gt;") + '</span>',
            1,
        )
        response.set_data(html)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    except Exception:
        pass
    return response
