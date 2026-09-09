"""회의별 표 열 구성.

이 파일만 고치면 PPT 표의 열이 바뀐다.

label 안의 자리표시자
  {cy} 회의 연도  {py} 전년  {cm} 당월  {pm} 전월  {nm} 익월
  {close_m} 이 회의가 다루는 마감월. 누계 비교 구간의 끝이다.

f = 리포트 필드
  ytd              26년 누계
  prev_ytd         25년 누계 (월별을 마감월까지 누적한 값. 기존 행에만 들어간다)
  yoy              증감률(누계 기준, 자동 계산)
  prev_preclose    전월 가마감
  prev_close       전월 마감(현재값. 확정 이후에는 확정마감)
  prev_provisional 전월 잠정마감
  first/second     당월 1차·2차 예상
  third_forecast   당월 3차 예상
  third_confirmed  당월 3차 확정
  next_first       익월 1차 예상
  preclose_cur     당월 가마감(익월 리포트에서 가져옴)
  second_half      하반기

bold=True 인 열은 이번 회의에서 보고하는 값이라 숫자를 굵게 찍는다.

누계 열에 마감월을 같이 적는다. 26년과 25년이 같은 구간인지 회의에서 바로 보이게 하기 위해서다.
"""

HEAD = [
    {"label": "{cy}년 누계\n(~{close_m}월)", "f": "ytd"},
    {"label": "{py}년 누계\n(~{close_m}월)", "f": "prev_ytd"},
    {"label": "증감", "f": "yoy"},
]

TAIL = [
    {"label": "하반기", "f": "second_half"},
]

MIDDLE = {
    "pre": [
        {"label": "{cm}월 3차 예상", "f": "third_forecast"},
        {"label": "{cm}월 가마감", "f": "preclose_cur", "bold": True},
        {"label": "{nm}월 1차", "f": "next_first", "bold": True},
    ],
    "r1": [
        {"label": "{pm}월 가마감", "f": "prev_preclose"},
        {"label": "{pm}월 잠정마감", "f": "prev_close", "bold": True},
        {"label": "{cm}월 1차", "f": "first"},
        {"label": "{cm}월 2차", "f": "second", "bold": True},
    ],
    "r2": [
        {"label": "{pm}월 잠정", "f": "prev_provisional"},
        {"label": "{pm}월 확정", "f": "prev_close", "bold": True},
        {"label": "{cm}월 1차", "f": "first"},
        {"label": "{cm}월 2차", "f": "second"},
        {"label": "{cm}월 3차", "f": "third_forecast", "bold": True},
    ],
}

# 3장은 계획이 주인공이라 이번 차수 하나만 놓는다.
PLAN_ONLY = {
    "pre": [{"label": "{nm}월 1차", "f": "next_first", "bold": True}],
    "r1": [{"label": "{cm}월 2차 FCST", "f": "second", "bold": True}],
    "r2": [{"label": "{cm}월 3차 FCST", "f": "third_forecast", "bold": True}],
}

# 표 위치와 크기 (인치). 슬라이드는 13.33 x 7.5
LAYOUT = {
    "full": {"x": 0.17, "y": 2.42, "w": 12.95, "h": 5.00},
    "plan": {"x": 0.17, "y": 3.05, "w": 6.60, "h": 4.30},
}


def fill(label, ctx):
    out = label
    for key, value in ctx.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def columns(meeting, ctx, plan=False):
    middle = (PLAN_ONLY if plan else MIDDLE).get(meeting) or MIDDLE.get("r1")
    cols = (HEAD + middle + TAIL) if not plan else middle
    out = []
    for col in cols:
        item = dict(col)
        item["label"] = fill(item.get("label", ""), ctx)
        out.append(item)
    return out
