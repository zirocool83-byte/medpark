"""PPT 표의 가마감·잠정 칸을 현황판과 같은 자리에서 읽게 한다.

증상 (2026-09-29)
  가마감 회의 PPT 표의 '9월 가마감' 칸이 비어 있었다. 현황판에는 854.9백만원이
  보이는데 PPT 만 0/빈칸이었다.

원인
  PPT 는 당월 가마감을 '익월 리포트의 prev_preclose' 에서 가져왔다.
  third_round_live 가 현황판 열을 회의 흐름대로 재배치하면서 필드 자리가 바뀌었는데
  PPT 쪽은 예전 자리를 계속 읽고 있었다.
    현재 자리  당월 가마감      = third_forecast (현황판 '가마감' 칸)
              전월 가마감      = prev_first
              전월 잠정마감    = prev_preclose
              전월 마감(확정)  = prev_close
  같은 이유로 다음 회의 표도 어긋나 있었다.
    5일 회의  '전월 가마감' 이 잠정마감 값을 읽음
    15일 회의 '전월 잠정'   이 확정마감 값을 읽음

고친 것
  PPT 표가 읽는 값만 위 자리로 맞춘다. 리포트 계산·저장값·현황판은 건드리지 않는다.
"""

import narrative_pptx_ui as pptx
import narrative_table_cfg as tcfg
import prev_compare_trim as prev

app = prev.app

if "prev_first" not in pptx.FIELDS:
    pptx.FIELDS = tuple(pptx.FIELDS) + ("prev_first",)

_original_table_index = pptx._table_index


def _table_index(year, month, meeting):
    index = _original_table_index(year, month, meeting)
    for rec in index.values():
        # 전월 잠정마감은 현황판 재배치 이후 prev_preclose 자리에 있다.
        rec["prev_provisional"] = rec.get("prev_preclose")
        if meeting == "pre":
            # 당월 가마감 = 현황판 '가마감' 칸
            rec["preclose_cur"] = rec.get("third_forecast")
    if meeting == "pre":
        # 지역(국내/해외) 전체가 0이면 가마감 차수가 아직 없는 것이다.
        # 0으로 찍으면 '매출 0'으로 읽히므로 '-'(값 없음)로 둔다.
        for region in ("국내", "해외"):
            recs = [rec for key, rec in index.items() if key[1] == region]
            if recs and not any(rec.get("preclose_cur") for rec in recs):
                for rec in recs:
                    rec["preclose_cur"] = None
    return index


pptx._table_index = _table_index

# 5일 회의 '전월 가마감' 은 prev_first 자리에서 읽는다.
for _column in (tcfg.MIDDLE.get("r1") or []):
    if _column.get("label") == "{pm}월 가마감" and _column.get("f") == "prev_preclose":
        _column["f"] = "prev_first"
