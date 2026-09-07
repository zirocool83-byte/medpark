import base64
import gzip
import json
import os
from datetime import datetime


def _seed_data():
    data_dir = os.environ.get("DATA_DIR", "/app/user_data")
    data_file = os.path.join(data_dir, "performance_data.json")
    current = None
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            current = json.load(f)
    except Exception:
        current = None

    valid = (
        isinstance(current, dict)
        and current.get("meta", {}).get("initialized") is True
        and len(current.get("users", [])) == 10
    )
    if valid:
        return

    packed = os.environ.get("AUTO_SEED_GZ", "").strip()
    if not packed:
        raise RuntimeError("AUTO_SEED_GZ missing")
    seed = json.loads(gzip.decompress(base64.b64decode(packed)).decode("utf-8"))
    if len(seed.get("users", [])) != 10 or len(seed.get("actuals", {})) != 84:
        raise RuntimeError("Invalid performance seed")
    seed.setdefault("meta", {})["initialized"] = True
    seed["meta"]["runtime_seeded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(data_dir, exist_ok=True)
    tmp = data_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)
    os.replace(tmp, data_file)


def on_starting(server):
    _seed_data()


def post_worker_init(worker):
    import app as base
    from flask import jsonify, redirect, url_for

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
        return []

    def can_edit_entry(user, entry):
        if not user:
            return False
        if user.get("role") == "admin" or user.get("manage_all"):
            return True
        return (
            entry.get("user_id") == user.get("user_id")
            and (entry.get("business"), entry.get("region")) in scope_pairs(user)
        )

    def setup_redirect():
        return redirect(url_for("login"))

    def health_runtime():
        data = base.read_store()
        return jsonify({
            "status": "ok",
            "initialized": bool(data.get("meta", {}).get("initialized")),
            "users": len(data.get("users", [])),
            "entries": len(data.get("entries", [])),
            "actuals": len(data.get("actuals", {})),
            "seed_version": data.get("meta", {}).get("seed_version", ""),
            "runtime_patch": True,
        })

    base.scope_pairs = scope_pairs
    base.can_edit_entry = can_edit_entry
    base.app.view_functions["setup"] = setup_redirect
    base.app.view_functions["health"] = health_runtime
