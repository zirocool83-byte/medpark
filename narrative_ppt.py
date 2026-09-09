"""회차 문안과 표를 회사 장표 3장으로 만든다.

narrative_template.pptx 는 실제 결산회의 장표에서 실적 슬라이드 3장과
마스터·레이아웃·테마만 남기고 엑셀 캡처를 제거한 것이다.
본문 텍스트 상자의 문단을 갈아끼우고, 비워둔 표 자리에 네이티브 표를 넣는다.

문단 크기를 명시하지 않으면 상자 기본값이 먹어 원본보다 커진다.
표를 덮지 않도록 크기를 지정해서 넣는다.

주의 1: txBody 는 <a:bodyPr>...</a:bodyPr><a:lstStyle/> 다음에 문단이 온다.
        bodyPr 이 자식(<a:spAutoFit/>)을 가질 수 있어서 여는 태그만 잘라내면
        XML 이 깨지고, 파워포인트는 오류 없이 그 상자를 통째로 무시한다.

주의 2: 이 서버에는 Flask 와 gunicorn 만 설치돼 있다.
        외부 라이브러리를 쓰면 모듈 로드가 통째로 실패해 기능이 화면에서 사라진다.
"""

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

TEMPLATE = Path(__file__).with_name("narrative_template.pptx")

SLIDE_CLOSE = "ppt/slides/slide3.xml"
SLIDE_FCST = "ppt/slides/slide4.xml"
SLIDE_PLAN = "ppt/slides/slide5.xml"

BLUE = "0000FF"
RED = "FF0000"
BLACK = "000000"

SIZE_TITLE = 1400
SIZE_BODY = 1200
SIZE_SMALL = 1100

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


def _insert_frame(slide_xml, frame_xml):
    idx = slide_xml.rindex("</p:spTree>")
    return slide_xml[:idx] + frame_xml + slide_xml[idx:]


def build(blocks, frames=None):
    if not TEMPLATE.exists():
        raise FileNotFoundError("narrative_template.pptx 가 없습니다")

    frames = frames or {}
    src = zipfile.ZipFile(TEMPLATE)
    out_buf = io.BytesIO()
    report = {"replaced": [], "missing": [], "tables": [], "checked": []}

    targets = {
        SLIDE_CLOSE: ([("TextBox 2", blocks.get("close") or [])], frames.get("close")),
        SLIDE_FCST: ([("TextBox 2", blocks.get("fcst") or [])], frames.get("fcst")),
        SLIDE_PLAN: ([("TextBox 2", blocks.get("plan_left") or []),
                      ("직사각형 5", blocks.get("plan_right") or [])], frames.get("plan")),
    }

    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename in targets:
                shapes, frame = targets[item.filename]
                xml = data.decode("utf-8")
                for shape_name, paras in shapes:
                    if not paras:
                        continue
                    xml, ok = _replace_txbody(xml, shape_name, paras)
                    tag = item.filename.split("/")[-1] + ":" + shape_name
                    (report["replaced"] if ok else report["missing"]).append(tag)
                if frame:
                    xml = _insert_frame(xml, frame)
                    report["tables"].append(item.filename.split("/")[-1])
                ElementTree.fromstring(xml)
                report["checked"].append(item.filename.split("/")[-1])
                data = xml.encode("utf-8")
            out.writestr(item, data)
    return out_buf.getvalue(), report
