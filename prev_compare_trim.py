"""현황판 '전월 비교' 칸을 회의 시점에 맞게 줄인다.

배경 (2026-09-28)
  전월 비교는 전월 가마감 · 전월 잠정마감 · 전월 확정마감 세 칸이 날짜와
  상관없이 늘 보였다. 9월 가마감 회의(25일경)에서 8월 가마감·잠정마감은
  이미 확정마감으로 끝난 중간 숫자라 볼 이유가 없다.

보여주는 칸 (보고 대상월이 이번 달일 때, 오늘 날짜 기준)
  1~4일   전월 가마감 · 전월 마감   (전월이 아직 잠정/확정 전)
  5~14일  전월 잠정마감 · 전월 마감 (2차 실적회의: 잠정 → 확정 차이 확인)
  15일~   전월 마감 한 칸           (3차 · 가마감 회의: 전월 대비 기준만)
  지난달 이전을 조회할 때는 전월 마감 한 칸만 보인다.

원칙
  값·계산은 건드리지 않는다. 렌더된 표에서 칸만 뺀다.
  머리글과 모든 행에서 같은 수만큼 정확히 찾았을 때만 바꾸고,
  하나라도 어긋나면 원래 화면을 그대로 돌려준다(칸 밀림 방지).
  PPT 간편보기(/ppt-view)는 별도 화면이라 영향이 없다.
"""

import datetime
import re

import narrative_round_fix as prev
import root_live_fetch as live

app = prev.app
ui = live.ui

_HEAD_GROUP = "<th colspan='3'>전월 비교</th>"
_HEAD_CELLS = re.compile(
    r"<th>(\d+)월 가마감</th><th>\1월 잠정마감</th>(<th class='stage-done'>[^<]*</th>)"
)
_ROW_CELLS = re.compile(
    r"<td>([^<]*)</td><td>([^<]*)</td>(<td class='stage-done'>[^<]*</td>)(?=<td class='c1)"
)


def keep_columns(year, month, today=None):
    """남길 칸: 'flash'(전월 가마감) · 'provisional'(전월 잠정마감). 전월 마감은 항상."""
    today = today or datetime.date.today()
    if (year, month) != (today.year, today.month):
        return ()
    if today.day <= 4:
        return ("flash",)
    if today.day <= 14:
        return ("provisional",)
    return ()


def trim(html, keep):
    count = 1 + len(keep)
    if count == 3 or html.count(_HEAD_GROUP) != 1:
        return html
    head = _HEAD_CELLS.findall(html)
    rows = _ROW_CELLS.findall(html)
    body_rows = html.count("<tr class='")
    if len(head) != 1 or not rows or len(rows) != body_rows:
        return html

    def head_sub(m):
        pm = m.group(1)
        out = ""
        if "flash" in keep:
            out += f"<th>{pm}월 가마감</th>"
        if "provisional" in keep:
            out += f"<th>{pm}월 잠정마감</th>"
        return out + m.group(2)

    def row_sub(m):
        out = ""
        if "flash" in keep:
            out += f"<td>{m.group(1)}</td>"
        if "provisional" in keep:
            out += f"<td>{m.group(2)}</td>"
        return out + m.group(3)

    html = html.replace(_HEAD_GROUP, f"<th colspan='{count}'>전월 비교</th>", 1)
    html = _HEAD_CELLS.sub(head_sub, html, count=1)
    return _ROW_CELLS.sub(row_sub, html)


_original_render_report = ui.render_report


def render_report(report, user, capture=False):
    html = _original_render_report(report, user, capture)
    try:
        year = int(report.get("year") or 0)
        month = int(report.get("month") or 0)
        return trim(html, keep_columns(year, month))
    except Exception:
        return html


ui.render_report = render_report
