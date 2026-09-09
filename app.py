"""진입점.

모듈을 위에서부터 하나씩 올려보고 처음 성공한 것을 쓴다.
실패한 모듈은 오류 내용을 남겨 /entry-status 에서 볼 수 있게 한다.

이 서버에는 Flask 와 gunicorn 만 있다. 외부 라이브러리를 쓰면 그 모듈이
통째로 로드되지 않고, 그러면 화면에서 기능이 조용히 사라진다.
오늘 그 일이 반복돼 원인을 바로 볼 수 있게 만들었다.
"""

import traceback

CANDIDATES = [
    "load_2025_actuals",
    "prior_year_probe",
    "august_domestic_close",
    "narrative_ytd_diag",
    "narrative_pptx_ui",
    "narrative_page",
    "browser_bridge",
    "salesops_variant_probe",
]

IMPORT_ERRORS = []
LOADED = None
app = None

for name in CANDIDATES:
    try:
        module = __import__(name)
        candidate = getattr(module, "app", None)
        if candidate is None:
            IMPORT_ERRORS.append({"module": name, "error": "no app attribute"})
            continue
        app = candidate
        LOADED = name
        break
    except Exception as exc:
        IMPORT_ERRORS.append({
            "module": name,
            "error": type(exc).__name__ + ": " + str(exc)[:300],
            "trace": traceback.format_exc()[-1200:],
        })

if app is None:
    raise RuntimeError("모든 진입 모듈 로드 실패: " + str(IMPORT_ERRORS))


@app.get("/entry-status")
def entry_status():
    from flask import jsonify
    return jsonify({
        "loaded": LOADED,
        "skipped": [e["module"] for e in IMPORT_ERRORS],
        "errors": IMPORT_ERRORS,
    })


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False, use_reloader=False)
