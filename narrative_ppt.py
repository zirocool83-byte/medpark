"""회차 문안을 회사 장표 3장으로 만든다.

narrative_template.pptx 는 실제 결산회의 장표에서 실적 슬라이드 3장과
마스터·레이아웃·테마만 남기고 엑셀 캡처를 제거한 것이다.
여기서는 각 장의 본문 텍스트 상자만 새 문단으로 갈아끼운다.
배경·머리·폰트·색·슬라이드 번호는 원본 그대로 남는다.

표는 원본에서도 엑셀 캡처 이미지였으므로 자리를 비워 둔다.
받은 파일에 엑셀 캡처를 붙이면 회의 자료가 완성된다.

문단 서식 규칙(원본에서 읽은 것)
  검정 굵게  제목            1) 매출
  검정       부제목·하위항목  (1) …  /  - 기존 : …
  파랑 굵게  핵심 수치        ㄱ. 8월 잠정마감 …
  빨강 굵게  경고·부족        - 하반기 누적 … 부족
"""

import io
import re
import zipfile
from pathlib import Path

TEMPLATE = Path(__file__).with_name("narrative_template.pptx")

# 원본 슬라이드 번호 → 역할
SLIDE_CLOSE = "ppt/slides/slide3.xml"
SLIDE_FCST = "ppt/slides/slide4.xml"
SLIDE_PLAN = "ppt/slides/slide5.xml"

BLUE = "0000FF"
RED = "FF0000"
BLACK = "000000"

SHADOW = (
    '<a:effectLst><a:outerShdw blurRad="38100" dist="38100" dir="2700000" algn="tl">'
    '<a:srgbClr val="000000"><a:alpha val="43137"/></a:srgbClr></a:outerShdw></a:effectLst>'
)
FONT = (
    '<a:latin typeface="Arial" panose="020B0604020202020204" pitchFamily="34" charset="0"/>'
    '<a:cs typeface="Arial" panose="020B0604020202020204" pitchFamily="34" charset="0"/>'
)


def esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def para(text, color=BLACK, bold=False, indent=0):
    """문단 하나를 XML로 만든다."""
    pad = "  " * max(0, int(indent))
    body = esc(pad + str(text))
    rpr = '<a:rPr lang="ko-KR" altLang="en-US"%s dirty="0">' % (' b="1"' if bold else "")
    rpr += '<a:solidFill><a:srgbClr val="%s"/></a:solidFill>' % color
    if bold:
        rpr += SHADOW
    rpr += FONT + "</a:rPr>"
    return "<a:p><a:r>" + rpr + "<a:t>" + body + "</a:t></a:r></a:p>"


def blank():
    return '<a:p><a:endParaRPr lang="ko-KR" altLang="en-US" dirty="0"/></a:p>'


def _replace_txbody(slide_xml, shape_name, paragraphs):
    """지정한 도형의 txBody 안 문단만 교체한다. 도형 위치·크기는 그대로 둔다."""
    pattern = re.compile(
        r'(<p:sp>(?:(?!</p:sp>).)*?name="' + re.escape(shape_name) + r'"(?:(?!</p:sp>).)*?</p:sp>)',
        re.S,
    )
    match = pattern.search(slide_xml)
    if not match:
        return slide_xml, False
    sp = match.group(1)
    body_match = re.search(r'(<p:txBody>.*?<a:bodyPr[^>]*/?>)(.*?)(</p:txBody>)', sp, re.S)
    if not body_match:
        return slide_xml, False
    head = body_match.group(1)
    tail = body_match.group(3)
    # bodyPr 뒤에 lstStyle 이 있으면 살린다
    rest = body_match.group(2)
    lst = ""
    lst_match = re.match(r'\s*(<a:lstStyle[^>]*/?>(?:.*?</a:lstStyle>)?)', rest, re.S)
    if lst_match:
        lst = lst_match.group(1)
    new_body = head + lst + "".join(paragraphs) + tail
    new_sp = sp[:body_match.start()] + new_body + sp[body_match.end():]
    return slide_xml[:match.start(1)] + new_sp + slide_xml[match.end(1):], True


def build(blocks):
    """blocks = {"close": [문단...], "fcst": [...], "plan_left": [...], "plan_right": [...]}

    반환: (bytes, 보고서)
    """
    if not TEMPLATE.exists():
        raise FileNotFoundError("narrative_template.pptx 가 없습니다")

    src = zipfile.ZipFile(TEMPLATE)
    out_buf = io.BytesIO()
    report = {"replaced": [], "missing": []}

    targets = {
        SLIDE_CLOSE: [("TextBox 2", blocks.get("close") or [])],
        SLIDE_FCST: [("TextBox 2", blocks.get("fcst") or [])],
        SLIDE_PLAN: [("TextBox 2", blocks.get("plan_left") or []),
                     ("직사각형 5", blocks.get("plan_right") or [])],
    }

    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename in targets:
                xml = data.decode("utf-8")
                for shape_name, paras in targets[item.filename]:
                    if not paras:
                        continue
                    xml, ok = _replace_txbody(xml, shape_name, paras)
                    tag = item.filename.split("/")[-1] + ":" + shape_name
                    (report["replaced"] if ok else report["missing"]).append(tag)
                data = xml.encode("utf-8")
            out.writestr(item, data)
    return out_buf.getvalue(), report
