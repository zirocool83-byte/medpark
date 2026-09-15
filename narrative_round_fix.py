"""문안 작성기의 회차를 현황판과 맞춘다.

바로잡은 것
  1) 회의 이름이 한 칸 밀려 있었다
     5일 회의는 당월 2차 FCST 를 보고하는 자리인데 "1차 실적회의"로,
     15일 회의는 3차를 보고하는데 "2차 실적회의"로 되어 있었다.
     보고하는 FCST 는 맞게 잡혀 있었으므로 이름만 실제 차수에 맞춘다.
       5일  → 2차 실적회의   15일 → 3차 실적회의   25일 → 가마감 회의
  2) 열 → 필드 매핑이 어긋났다
     현황판 열을 회의 흐름대로 재배치하면서 당월 3차 예상을 third_confirmed,
     가마감을 third_forecast 자리에 앉혔다(third_round_live). 문안 작성기는
     예전 자리를 읽고 있어 숫자가 비거나 다른 값이 나왔다.
  3) 처음 열 때 회의가 날짜를 따르지 않았다
     항상 5일 회의로 열렸다. 오늘 날짜에 맞는 회의를 먼저 보여준다.

설정 파일을 통째로 다시 쓰지 않고 이 세 곳만 고친다. 입력표·문장 틀은 그대로다.
"""

import datetime

import overseas_live as prev
import narrative_config as ncfg

app = prev.app

CONFIG = ncfg.CONFIG

# 1) 회의 이름을 실제 차수에 맞춘다.
LABELS = {
    "r1": ("2차 실적회의", "5일경"),
    "r2": ("3차 실적회의", "15일경"),
    "pre": ("가마감 회의", "25일경"),
}
for key, (label, when) in LABELS.items():
    meeting = (CONFIG.get("meetings") or {}).get(key)
    if isinstance(meeting, dict):
        meeting["label"] = label
        meeting["when"] = when

# 2) 열 → 필드 매핑을 현재 자리에 맞춘다.
CONFIG.setdefault("field_of", {}).update({
    "3차 예상": "third_confirmed",
    "가마감": "third_forecast",
})

# 3) 처음 열 때 오늘 날짜에 맞는 회의를 고른다.
_day = datetime.date.today().day
CONFIG["default_meeting"] = "pre" if _day >= 24 else "r2" if _day >= 15 else "r1"
