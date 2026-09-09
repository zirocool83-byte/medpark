"""진입점.

폴백 체인은 한 모듈이 깨져도 화면이 살아 있게 해 준다.
다만 왜 깨졌는지가 안 보여서 원인 찾기가 어렵다.
그래서 로드 실패 사유를 기록해 두고 /boot-status 로 확인한다.
"""

BOOT = {"loaded": None, "errors": []}

CHAIN = [
    "august_domestic_actuals",
    "narrative_ytd_diag",
    "narrative_pptx_ui",
    "narrative_users_probe",
    "narrative_page",
    "browser_bridge",
    "salesops_variant_probe",
]

app = None
for _name in CHAIN:
    try:
        _module = __import__(_name)
        app = getattr(_module, "app")
        BOOT["loaded"] = _name
        break
    except Exception as _exc:
        import traceback
        BOOT["errors"].append({
            "module": _name,
            "error": type(_exc).__name__ + ": " + str(_exc)[:300],
            "trace": traceback.format_exc()[-1200:],
        })

if app is None:
    raise RuntimeError("no app module could be loaded: %s" % BOOT["errors"])


@app.get("/boot-status")
def boot_status():
    from flask import jsonify
    return jsonify(BOOT)


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False, use_reloader=False)
