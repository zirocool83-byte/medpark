"""회차 기록용 사용자·권한 구조 점검.

담당자 선택과 조회 전용 권한을 붙이기 전에
공간4가 사용자와 역할을 어떤 이름으로 들고 있는지 확인한다.
읽기 전용이며 비밀번호 계열 키는 값 없이 이름만 노출한다.
"""

import narrative_page as prev
from flask import jsonify

app = prev.app
base = prev.base

SECRET_HINTS = ("password", "passwd", "pw", "hash", "salt", "token", "secret", "key")
USER_HINTS = ("user", "role", "perm", "auth", "account", "member", "manage")


def _safe(value, depth=0):
    if depth > 2:
        return "..."
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if any(h in str(k).lower() for h in SECRET_HINTS):
                out[k] = "<hidden>"
            else:
                out[k] = _safe(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_safe(v, depth + 1) for v in value[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return type(value).__name__


@app.get("/narrative-introspect")
def narrative_introspect():
    user = None
    try:
        user = base.current_user()
    except Exception:
        user = None
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    info = {
        "base_module": getattr(base, "__name__", "?"),
        "current_user": _safe(user),
        "base_names": sorted(
            n for n in dir(base)
            if not n.startswith("_") and any(h in n.lower() for h in USER_HINTS)
        ),
    }

    store = None
    try:
        store = base.read_store()
    except Exception as exc:
        info["read_store_error"] = type(exc).__name__
    if isinstance(store, dict):
        info["store_top_keys"] = sorted(store.keys())
        users = store.get("users")
        if isinstance(users, dict):
            info["users_shape"] = "dict"
            info["user_count"] = len(users)
            info["users"] = {k: _safe(v) for k, v in list(users.items())[:40]}
        elif isinstance(users, list):
            info["users_shape"] = "list"
            info["user_count"] = len(users)
            info["users"] = [_safe(v) for v in users[:40]]
        else:
            info["users_shape"] = type(users).__name__

    for name in ("ROLES", "ROLE_LABELS", "PERMISSIONS", "BUSINESSES", "KINDS", "REGIONS", "MARKETS"):
        if hasattr(base, name):
            info[name] = _safe(getattr(base, name))

    return jsonify(info)
