"""회의 주기 설정.

여기만 고치면 문안 생성기의 회의 구성·열 이름·비교 기준이 바뀐다.

meetings[키]
  label / when : 화면에 표시할 회의 이름과 시점
  close        : 마감 섹션. off = 회의월 기준 대상월 오프셋(0=당월, -1=전월)
                 cols = 왼쪽부터 표시할 열 이름
                 cur  = 이번 회의가 보고하는 열 번호(1부터). 비교 기준은 그 왼쪽 열
                 word = 문장에서 쓸 표현
  fcst         : 예상 섹션. 구조 동일
  tol          : 허용 오차 판정을 쓸지 여부(잠정 → 확정 검증용)

field_of : 열 이름을 성과리포트 필드명에 연결한다. 여기 없는 열은 수기 입력이다.
"""

CONFIG = {
    "order": ["pre", "r1", "r2"],
    "default_meeting": "r1",
    "meetings": {
        "pre": {
            "label": "가마감 회의",
            "when": "25일경",
            "close": {"off": 0, "cols": ["3차 예상", "가마감"], "cur": 2, "word": "가마감"},
            "fcst": {"off": 1, "cols": ["사업계획", "1차 예상"], "cur": 2},
            "tol": False,
        },
        "r1": {
            "label": "1차 실적회의",
            "when": "5일경",
            "close": {"off": -1, "cols": ["가마감", "마감(잠정)"], "cur": 2, "word": "잠정마감"},
            "fcst": {"off": 0, "cols": ["1차 예상", "2차 예상"], "cur": 2},
            "tol": False,
        },
        "r2": {
            "label": "2차 실적회의",
            "when": "15일경",
            "close": {"off": -1, "cols": ["마감(잠정)", "마감(확정)"], "cur": 2, "word": "확정마감"},
            "fcst": {"off": 0, "cols": ["1차 예상", "2차 예상", "3차 예상"], "cur": 3},
            "tol": True,
        },
    },
    # 열 이름 → 성과리포트 필드. 없는 열은 수기 입력.
    "field_of": {
        "1차 예상": "first",
        "2차 예상": "second",
        "3차 예상": "third_forecast",
        "3차 확정": "third_confirmed",
        "마감(잠정)": "close",
    },
}
