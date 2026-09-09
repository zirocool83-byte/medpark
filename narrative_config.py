"""회의 주기·성격 설정.

이 파일만 고치면 문안 생성기의 회의 구성, 입력 항목, 문장, 권한 범위가 바뀐다.

meetings[키]
  label / when : 화면에 표시할 회의 이름과 시점
  purpose      : 이 회의가 무엇을 하는 자리인지. 화면 안내에 그대로 쓴다
  close / fcst : off = 회의월 기준 대상월 오프셋(0=당월, -1=전월, 1=익월)
                 cols = 왼쪽부터 표시할 열 이름
                 cur  = 이번 회의가 보고하는 열 번호(1부터). 비교 기준은 그 왼쪽 열
                 word = 문장에서 쓸 표현
  tol          : 잠정 → 확정 허용오차 판정을 쓸지
  lists        : 회의별 추가 입력표. 아래 col type 참고
                   user   = 등록 사용자 드롭다운
                   select = options 중 선택
                   text   = 자유 입력
                   amount = 금액(입력 단위 적용)
                   date   = 날짜
                 sentence = 문장 조립 틀. {키}가 입력값으로 치환된다
"""

SCOPE_ALL = {"regions": ["국내", "해외"], "businesses": ["덴탈", "메디컬", "에스테틱"]}

CONFIG = {
    "order": ["pre", "r1", "r2"],
    "default_meeting": "r1",

    "businesses": ["덴탈", "메디컬", "에스테틱"],
    "regions": ["국내", "해외"],

    # 마감 관련 경고를 띄울 기간. 그 외에는 감춘다.
    "close_season": {
        "preclose": {"from_day": 23, "to_day": 31, "target": "당월 가마감"},
        "close": {"from_day": 1, "to_day": 15, "target": "전월 마감"},
    },

    # permission_type → 편집 가능 범위. 여기 없으면 조회만 가능하다.
    "scopes": {
        "admin": SCOPE_ALL,
        "domestic_all": {"regions": ["국내"], "businesses": ["덴탈", "메디컬", "에스테틱"]},
        "dental_domestic": {"regions": ["국내"], "businesses": ["덴탈"]},
        "overseas_all": {"regions": ["해외"], "businesses": ["덴탈", "메디컬", "에스테틱"]},
        "aesthetics_all": {"regions": ["국내", "해외"], "businesses": ["에스테틱"]},
    },

    "meetings": {
        "pre": {
            "label": "가마감 회의",
            "when": "25일경",
            "purpose": "당월 가마감 숫자를 마무리하고 익월 1차 FCST를 세우는 자리입니다. "
                       "당월에 추가로 손쓸 것은 많지 않으니, 익월 1차를 기존 예상·신규 추진·확정 이월로 나눠 구체적으로 잡습니다.",
            "close": {"off": 0, "cols": ["3차 예상", "가마감"], "cur": 2, "word": "가마감"},
            "fcst": {"off": 1, "cols": ["사업계획", "1차 예상"], "cur": 2},
            "tol": False,
            "lists": [
                {
                    "id": "nextplan",
                    "title": "익월 1차 구성",
                    "hint": "익월 1차 예상이 무엇으로 채워지는지 나눠 적습니다.",
                    "cols": [
                        {"key": "kind", "label": "구분", "type": "select",
                         "options": ["기존 예상", "신규 추진", "확정 이월"]},
                        {"key": "region", "label": "지역", "type": "select", "options": ["국내", "해외"]},
                        {"key": "biz", "label": "사업분야", "type": "select",
                         "options": ["전체", "덴탈", "메디컬", "에스테틱"]},
                        {"key": "what", "label": "대상", "type": "text"},
                        {"key": "amount", "label": "금액", "type": "amount"},
                        {"key": "owner", "label": "담당", "type": "user"},
                    ],
                    "sentence": "{region} {biz} {what} {amount} ({kind}, {owner})",
                    "lead": "익월 1차 구성은 ",
                    "tail": "입니다.",
                }
            ],
        },
        "r1": {
            "label": "1차 실적회의",
            "when": "5일경",
            "purpose": "전월 잠정마감으로 실제 성적표를 확인하고 분석하는 자리입니다. "
                       "당월 2차 FCST를 놓고 그것을 달성할 계획을 공격적으로 잡습니다. 누가 언제 무엇을 할지가 반드시 나와야 합니다.",
            "close": {"off": -1, "cols": ["가마감", "마감(잠정)"], "cur": 2, "word": "잠정마감"},
            "fcst": {"off": 0, "cols": ["1차 예상", "2차 예상"], "cur": 2},
            "tol": False,
            "lists": [
                {
                    "id": "action",
                    "title": "달성 계획",
                    "hint": "2차 FCST를 달성하기 위한 실행 항목입니다. 담당과 기한이 없으면 계획이 아닙니다.",
                    "required": ["owner", "what", "due"],
                    "cols": [
                        {"key": "owner", "label": "담당", "type": "user"},
                        {"key": "region", "label": "지역", "type": "select", "options": ["국내", "해외"]},
                        {"key": "biz", "label": "사업분야", "type": "select",
                         "options": ["전체", "덴탈", "메디컬", "에스테틱"]},
                        {"key": "what", "label": "실행 내용", "type": "text"},
                        {"key": "amount", "label": "목표 금액", "type": "amount"},
                        {"key": "due", "label": "기한", "type": "date"},
                    ],
                    "sentence": "{owner}가 {due}까지 {region} {biz} {what} {amount}",
                    "lead": "달성 계획은 ",
                    "tail": "입니다.",
                }
            ],
        },
        "r2": {
            "label": "2차 실적회의",
            "when": "15일경",
            "purpose": "전월 확정마감을 확인하는 자리입니다. 잠정과 확정 차이가 작으면 확인으로 끝내고, 크면 특이사항을 답니다. "
                       "당월 3차 FCST로 중간점검을 하고, 2차 대비 늘거나 줄면 백업플랜을 가동합니다.",
            "close": {"off": -1, "cols": ["마감(잠정)", "마감(확정)"], "cur": 2, "word": "확정마감"},
            "fcst": {"off": 0, "cols": ["1차 예상", "2차 예상", "3차 예상"], "cur": 3},
            "tol": True,
            "lists": [
                {
                    "id": "backup",
                    "title": "백업 플랜",
                    "hint": "3차가 2차 대비 흔들릴 때 가동할 대안입니다. 발동 조건을 적어두면 회의 중에 바로 결정할 수 있습니다.",
                    "cols": [
                        {"key": "trigger", "label": "발동 조건", "type": "text"},
                        {"key": "region", "label": "지역", "type": "select", "options": ["국내", "해외"]},
                        {"key": "biz", "label": "사업분야", "type": "select",
                         "options": ["전체", "덴탈", "메디컬", "에스테틱"]},
                        {"key": "what", "label": "대응 내용", "type": "text"},
                        {"key": "amount", "label": "보완 금액", "type": "amount"},
                        {"key": "owner", "label": "담당", "type": "user"},
                        {"key": "due", "label": "기한", "type": "date"},
                    ],
                    "sentence": "{trigger} 시 {owner}가 {due}까지 {region} {biz} {what} {amount}",
                    "lead": "백업 플랜은 ",
                    "tail": "입니다.",
                }
            ],
        },
    },

    # 열 이름 → 리포트 필드. 없는 열(사업계획, 마감(확정))은 수기 입력.
    "field_of": {
        "1차 예상": "first",
        "2차 예상": "second",
        "3차 예상": "third_forecast",
        "3차 확정": "third_confirmed",
        "가마감": "preclose",
        "마감(잠정)": "close",
    },
}
