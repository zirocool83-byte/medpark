"""회차 문안과 표를 회사 장표 3장으로 만든다.

narrative_template.pptx 는 실제 결산회의 장표에서 실적 슬라이드 3장과
마스터·레이아웃·테마만 남기고 엑셀 캡처를 제거한 것이다.

배치
  왼쪽 상자  요약(합계·국내/해외)          템플릿의 TextBox 2
  오른쪽 상자 변동 요인·특이사항            여기서 새로 만들어 넣는다
  아래        표                          네이티브 표

원본은 왼쪽 상자가 슬라이드 폭을 다 차지하는데 글자는 왼쪽 절반만 쓴다.
변동 요인이 늘면 상자가 아래로 자라 표를 덮는다.
그래서 요인을 오른쪽 빈 공간으로 옮긴다. 항목이 늘어도 표를 건드리지 않는다.

주의 1: txBody 는 <a:bodyPr>...</a:bodyPr><a:lstStyle/> 다음에 문단이 온다.
        bodyPr 이 자식(<a:spAutoFit/>)을 가질 수 있어서 여는 태그만 잘라내면
        XML 이 깨지고, 파워포인트는 오류 없이 그 상자를 통째로 무시한다.

주의 2: 이 서버에는 Flask 와 gunicorn 만 있다. 외부 라이브러리 금지.
"""

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

TEMPLATE = Path(__file__).with_name("narrative_template.pptx")
EMU = 914400

SLIDE_CLOSE = "ppt/slides/slide3.xml"
SLIDE_FCST = "ppt/slides/slide4.xml"
SLIDE_PLAN = "ppt/slides/slide5.xml"

BLUE = "0000FF"
RED = "FF0000"
BLACK = "000000"

SIZE_TITLE = 1400
SIZE_BODY = 1200
SIZE_SMALL = 1100

# 오른쪽 상자 위치 (인치)
RIGHT_BOX = {"x": 6.70, "y": 0.92, "w": 6.40, "h": 1.60}

SHADOW = (
    '<a:effectLst><a:outerShdw blurRad="38100" dist="38100" dir="2700000" algn="tl">'
    '<a:srgbClr val="000000"><a:alpha val="43137"/></a:srgbClr></a:outerShdw></a:effectLst>'
)
FONT = (
    '<a:latin typeface="Arial" panose="020B0604020202020204" pitchFamily="34" charset="0"/>'
    '<a:cs typeface="Arial" panose="020B0604020202020204" pitchFamily="34" charset="0"/>'
)

BODYPR_RE = re.compile(r'\s*(<a:bodyPr\b[^>]*/>|<a:bodyPr\b[^>]*>.*?</a:bodyPr>)', re.S)
LSTSTYLE_RE = re.compile(r'\s*(<a:lstStyle\b[^>]*/>|<a:lstStyle\b[^>]*>.*?</a:lstStyle>)', re.S)


def esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def para(text, color=BLACK, bold=False, indent=0, size=SIZE_BODY):
    pad = "  " * max(0, int(indent))
    body = esc(pad + str(text))
    rpr = '<a:rPr lang="ko-KR" altLang="en-US" sz="%d"%s dirty="0">' % (
        int(size), ' b="1"' if bold else "")
    rpr += '<a:solidFill><a:srgbClr val="%s"/></a:solidFill>' % color
    if bold:
        rpr += SHADOW
    rpr += FONT + "</a:rPr>"
    return "<a:p><a:r>" + rpr + "<a:t>" + body + "</a:t></a:r></a:p>"


def blank(size=SIZE_SMALL):
    return '<a:p><a:endParaRPr lang="ko-KR" altLang="en-US" sz="%d" dirty="0"/></a:p>' % int(size)


def textbox(shape_id, name, x, y, w, h, paragraphs):
    """새 텍스트 상자. 내용에 맞춰 아래로 자란다."""
    return (
        '<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/>'
        '<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
        '<p:txBody><a:bodyPr wrap="square" rtlCol="0"><a:spAutoFit/></a:bodyPr>'
        '<a:lstStyle/>%s</p:txBody></p:sp>'
        % (shape_id, name, int(x * EMU), int(y * EMU), int(w * EMU), int(h * EMU),
           "".join(paragraphs))
    )


def _replace_txbody(slide_xml, shape_name, paragraphs):
    pattern = re.compile(
        r'(<p:sp>(?:(?!</p:sp>).)*?name="' + re.escape(shape_name) + r'"(?:(?!</p:sp>).)*?</p:sp>)',
        re.S,
    )
    match = pattern.search(slide_xml)
    if not match:
        return slide_xml, False
    sp = match.group(1)
    tb = re.search(r'<p:txBody>(.*?)</p:txBody>', sp, re.S)
    if not tb:
        return slide_xml, False

    inner = tb.group(1)
    body_match = BODYPR_RE.match(inner)
    if body_match:
        bodypr = body_match.group(1)
        rest = inner[body_match.end():]
    else:
        bodypr = '<a:bodyPr wrap="square" rtlCol="0"><a:spAutoFit/></a:bodyPr>'
        rest = inner
    lst_match = LSTSTYLE_RE.match(rest)
    lst = lst_match.group(1) if lst_match else "<a:lstStyle/>"

    new_inner = bodypr + lst + "".join(paragraphs)
    new_sp = sp[:tb.start(1)] + new_inner + sp[tb.end(1):]
    return slide_xml[:match.start(1)] + new_sp + slide_xml[match.end(1):], True


def _append(slide_xml, fragment):
    idx = slide_xml.rindex("</p:spTree>")
    return slide_xml[:idx] + fragment + slide_xml[idx:]


def build(blocks, frames=None):
    """blocks 키
         close, fcst              왼쪽 요약 문단
         close_right, fcst_right  오른쪽 변동 요인 문단
         plan_left, plan_right    3장 좌우
       frames: {"close":표, "fcst":표, "plan":표}
    """
    if not TEMPLATE.exists():
        raise FileNotFoundError("narrative_template.pptx 가 없습니다")

    frames = frames or {}
    src = zipfile.ZipFile(TEMPLATE)
    out_buf = io.BytesIO()
    report = {"replaced": [], "missing": [], "tables": [], "boxes": [], "checked": []}

    plan = {
        SLIDE_CLOSE: {"shapes": [("TextBox 2", blocks.get("close") or [])],
                      "right": blocks.get("close_right") or [],
                      "right_id": 71, "frame": frames.get("close")},
        SLIDE_FCST: {"shapes": [("TextBox 2", blocks.get("fcst") or [])],
                     "right": blocks.get("fcst_right") or [],
                     "right_id": 72, "frame": frames.get("fcst")},
        SLIDE_PLAN: {"shapes": [("TextBox 2", blocks.get("plan_left") or []),
                                ("직사각형 5", blocks.get("plan_right") or [])],
                     "right": [], "right_id": 73, "frame": frames.get("plan")},
    }

    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            data = src.read(item.filename)
            spec = plan.get(item.filename)
            if spec:
                short = item.filename.split("/")[-1]
                xml = data.decode("utf-8")
                for shape_name, paras in spec["shapes"]:
                    if not paras:
                        continue
                    xml, ok = _replace_txbody(xml, shape_name, paras)
                    (report["replaced"] if ok else report["missing"]).append(short + ":" + shape_name)
                if spec["right"]:
                    xml = _append(xml, textbox(
                        spec["right_id"], "변동요인",
                        RIGHT_BOX["x"], RIGHT_BOX["y"], RIGHT_BOX["w"], RIGHT_BOX["h"],
                        spec["right"]))
                    report["boxes"].append(short)
                if spec["frame"]:
                    xml = _append(xml, spec["frame"])
                    report["tables"].append(short)
                ElementTree.fromstring(xml)
                report["checked"].append(short)
                data = xml.encode("utf-8")
            out.writestr(item, data)
    return out_buf.getvalue(), report
