"""회의 자료 표를 PPT 네이티브 표로 그린다.

캡처도 이미지 변환도 필요 없다. 서버가 리포트 데이터를 그대로 표로 만든다.
받은 파일에서 파워포인트로 숫자 수정도 된다.

행: 사업부 3 × (국내·해외) × (기존·신규) = 12행 + 사업부 소계 3 + 합계 1 = 16행
    지역별 소계는 넣지 않는다. 사업부 안에 이미 국내·해외가 나뉘어 있어 중복이다.

표기 규칙
  증가 ▲ 빨강 · 감소 ▼ 파랑 · 보합 - 회색
  금액은 백만원 단위 정수
  글자 크기를 먼저 정하고 표 높이를 거기 맞춘다. A3 출력 기준이라 크게 간다.

이 서버에는 Flask 와 gunicorn 만 있다. 표준 라이브러리만 쓴다.
"""

EMU = 914400

UP = "C00000"
DOWN = "1F5FA8"
FLAT = "808080"
INK = "16202B"
HEAD_BG = "2E5C9A"
SUB_BG = "DCE6F1"
TOT_BG = "B8CCE4"
LINE = "8EA9C1"

FONT_DATA = 900
FONT_SUM = 1000
FONT_HEAD = 900

BIZ = ["덴탈", "메디컬", "에스테틱"]
REGIONS = ["국내", "해외"]
KINDS = ["기존", "신규"]

LABEL_COLS = [("사업부", 1.05), ("지역", 0.60), ("구분", 0.60)]


def esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _run(text, size, bold, color):
    return (
        '<a:r><a:rPr lang="ko-KR" altLang="en-US" sz="%d"%s dirty="0">'
        '<a:solidFill><a:srgbClr val="%s"/></a:solidFill>'
        '<a:latin typeface="맑은 고딕"/><a:ea typeface="맑은 고딕"/>'
        '</a:rPr><a:t>%s</a:t></a:r>' % (size, ' b="1"' if bold else "", color, esc(text))
    )


def _cell(text, size=FONT_DATA, bold=False, color=INK, align="r", fill=None):
    algn = {"l": "l", "c": "ctr", "r": "r"}[align]
    fill_xml = ('<a:solidFill><a:srgbClr val="%s"/></a:solidFill>' % fill) if fill else '<a:noFill/>'
    lines = "".join(
        '<a:ln%s w="6350"><a:solidFill><a:srgbClr val="%s"/></a:solidFill></a:ln%s>' % (s, LINE, s)
        for s in ("L", "R", "T", "B")
    )
    return (
        '<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>'
        '<a:p><a:pPr algn="%s"/>%s</a:p></a:txBody>'
        '<a:tcPr marL="18288" marR="18288" marT="0" marB="0" anchor="ctr">%s%s</a:tcPr></a:tc>'
        % (algn, _run(text, size, bold, color), lines, fill_xml)
    )


def fmt_m(value):
    if value is None:
        return "-"
    return "{:,}".format(int(round(value / 1000000.0)))


def fmt_delta_rate(cur, base):
    """증감률. (표시문자, 색)"""
    if cur is None or base is None or not base:
        return "-", FLAT
    rate = (cur - base) / abs(float(base)) * 100
    if abs(rate) < 0.05:
        return "-", FLAT
    return ("▲" if rate > 0 else "▼") + "%.1f%%" % abs(rate), (UP if rate > 0 else DOWN)


def _sum(records, field):
    vals = [r.get(field) for r in records if r.get(field) is not None]
    return sum(vals) if vals else None


def make_rows(index, cols):
    """index: {(사업부,지역,구분): {필드:값}} → 표 행 목록"""
    rows = []
    for biz in BIZ:
        group = []
        for region in REGIONS:
            for kind in KINDS:
                rec = index.get((biz, region, kind)) or {}
                group.append(rec)
                rows.append({
                    "label": [biz if (region == REGIONS[0] and kind == KINDS[0]) else "",
                              region if kind == KINDS[0] else "", kind],
                    "cells": _cells(rec, cols),
                    "style": "data",
                })
        rows.append({"label": [biz + " 소계", "", ""],
                     "cells": _cells(_merge(group), cols), "style": "sub"})
    everything = [index.get((b, r, k)) or {} for b in BIZ for r in REGIONS for k in KINDS]
    rows.append({"label": ["합계", "", ""], "cells": _cells(_merge(everything), cols), "style": "total"})
    return rows


def _merge(records):
    out = {}
    for rec in records:
        for field, value in (rec or {}).items():
            if value is None:
                continue
            out[field] = value if out.get(field) is None else out[field] + value
    return out


def _cells(rec, cols):
    out = []
    for col in cols:
        field = col.get("f")
        if field == "yoy":
            text, color = fmt_delta_rate(rec.get("ytd"), rec.get("prev_ytd"))
            out.append((text, color, True))
        else:
            out.append((fmt_m(rec.get(field)), INK, bool(col.get("bold"))))
    return out


def build_table(rows, cols, x_in, y_in, w_in, h_in, frame_id=90, label_cols=None):
    label_cols = LABEL_COLS if label_cols is None else label_cols
    widths = [w for _, w in label_cols]
    num_w = max(0.8, (w_in - sum(widths)) / max(1, len(cols)))
    widths += [num_w] * len(cols)
    total = sum(widths)
    grid = "".join('<a:gridCol w="%d"/>' % int(w / total * w_in * EMU) for w in widths)

    n = len(rows) + 1
    row_h = int(h_in * EMU / n)

    parts = ['<a:tr h="%d">' % row_h]
    for label, _ in label_cols:
        parts.append(_cell(label, FONT_HEAD, True, "FFFFFF", "c", HEAD_BG))
    for col in cols:
        parts.append(_cell(col.get("label", ""), FONT_HEAD, True, "FFFFFF", "c", HEAD_BG))
    parts.append("</a:tr>")

    for row in rows:
        style = row.get("style", "data")
        if style == "total":
            size, bold, fill = FONT_SUM, True, TOT_BG
        elif style == "sub":
            size, bold, fill = FONT_SUM, True, SUB_BG
        else:
            size, bold, fill = FONT_DATA, False, None
        parts.append('<a:tr h="%d">' % row_h)
        for i, lab in enumerate(row.get("label", [])):
            parts.append(_cell(lab, size, bold or i == 0, INK, "l", fill))
        for text, color, cbold in row.get("cells", []):
            parts.append(_cell(text, size, bold or cbold, color, "r", fill))
        parts.append("</a:tr>")

    return (
        '<p:graphicFrame><p:nvGraphicFramePr>'
        '<p:cNvPr id="%d" name="실적표"/><p:cNvGraphicFramePr>'
        '<a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr>'
        '<p:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></p:xfrm>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
        '<a:tbl><a:tblPr firstRow="1" bandRow="0"/><a:tblGrid>%s</a:tblGrid>%s</a:tbl>'
        '</a:graphicData></a:graphic></p:graphicFrame>'
        % (frame_id, int(x_in * EMU), int(y_in * EMU), int(w_in * EMU), int(h_in * EMU),
           grid, "".join(parts))
    )


def insert_frame(slide_xml, frame_xml):
    idx = slide_xml.rindex("</p:spTree>")
    return slide_xml[:idx] + frame_xml + slide_xml[idx:]
