"""PPT 생성 자체 점검.

브라우저를 거치지 않고 서버가 혼자 PPT를 만들어 본다.
여기서 성공하면 문제는 화면 쪽, 실패하면 서버 쪽이다.
"""

import re
import traceback
import zipfile

import narrative_pptx_ui as prev
import narrative_ppt as builder
from flask import jsonify

app = prev.app


@app.get("/narrative-pptx-selftest")
def narrative_pptx_selftest():
    if not prev.prev._current_user():
        return jsonify({"error": "unauthorized"}), 401

    out = {"template": str(builder.TEMPLATE), "exists": builder.TEMPLATE.exists()}

    # 1) 템플릿 안에 우리가 찾는 도형 이름이 실제로 있는지
    try:
        z = zipfile.ZipFile(builder.TEMPLATE)
        shapes = {}
        for name in (builder.SLIDE_CLOSE, builder.SLIDE_FCST, builder.SLIDE_PLAN):
            xml = z.read(name).decode("utf-8")
            shapes[name] = re.findall(r'<p:cNvPr[^>]*name="([^"]+)"', xml)
        out["shape_names"] = shapes
    except Exception as exc:
        out["shape_scan_error"] = type(exc).__name__ + ": " + str(exc)[:200]
        return jsonify(out), 500

    # 2) 실제로 한 장씩 바꿔 본다
    blocks = {
        "close": [builder.para("1) 매출", bold=True),
                  builder.para("ㄱ. 시험 문단", color=builder.BLUE, bold=True, indent=1)],
        "fcst": [builder.para("1) 매출", bold=True),
                 builder.para("ㄱ. 시험 문단", color=builder.BLUE, bold=True, indent=1)],
        "plan_left": [builder.para("1) 매출", bold=True)],
        "plan_right": [builder.para("ㄴ. 시험 문단", color=builder.BLUE, bold=True, indent=1)],
    }
    try:
        data, report = builder.build(blocks)
        out["built_bytes"] = len(data)
        out["replaced"] = report.get("replaced")
        out["missing"] = report.get("missing")
        out["ok"] = bool(report.get("replaced")) and not report.get("missing")
    except Exception as exc:
        out["build_error"] = type(exc).__name__ + ": " + str(exc)[:300]
        out["trace"] = traceback.format_exc()[-800:]
        return jsonify(out), 500

    return jsonify(out)
