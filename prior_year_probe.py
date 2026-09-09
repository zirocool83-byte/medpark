"""리포트가 2025년 값을 어디서 읽는지 확인한다.

읽기 전용이다. 아무것도 바꾸지 않는다.

리포트 행에는 prev_ytd, prev_same 같은 전년 필드가 있는데 모두 0 이다.
저장소에 2025년 키가 아예 없는지, 있는데 못 읽는지부터 갈라야
8월 국내 때처럼 정확한 자리에 넣을 수 있다.
"""

import re

import august_domestic_close as prev
import narrative_page as npage
from flask import jsonify, request

app = prev.app
base = npage.base


@app.get("/prior-year-probe")
def prior_year_probe():
    user = npage._current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    out = {}

    # 1) 리포트 행의 전년 관련 필드
    report = npage._build(2026, 9)
    detail = None
    for row in (report or {}).get("rows", []) or []:
        if isinstance(row, dict) and not row.get("is_total"):
            detail = row
            break
    if detail:
        out["행_전년필드"] = {k: detail.get(k) for k in detail
                          if "prev" in k or "yoy" in k or "ytd" in k or "hist" in k}

    # 2) 저장소에 2025 가 들어간 키가 있는지
    try:
        store = base.read_store() or {}
    except Exception as exc:
        return jsonify({"store_error": type(exc).__name__ + ": " + str(exc)[:150]}), 500

    out["저장소_최상위키"] = sorted(store.keys())
    actuals = store.get("actuals") or {}
    out["actuals_총개수"] = len(actuals)

    keys_2025 = [k for k in actuals if "2025" in str(k)]
    out["actuals_2025_개수"] = len(keys_2025)
    out["actuals_2025_예시"] = sorted(keys_2025)[:12]
    total_2025 = 0
    for k in keys_2025:
        try:
            total_2025 += int(actuals.get(k) or 0)
        except Exception:
            pass
    out["actuals_2025_합계_억"] = round(total_2025 / 1e8, 2)

    keys_2026 = [k for k in actuals if "2026" in str(k)]
    out["actuals_2026_개수"] = len(keys_2026)
    out["actuals_2026_예시"] = sorted(keys_2026)[:6]

    # 3) actual_key 가 만드는 키 모양
    try:
        out["키_형식_2025_08"] = base.actual_key(2025, 8, "덴탈", "국내", "기존")
        out["키_형식_2026_08"] = base.actual_key(2026, 8, "덴탈", "국내", "기존")
    except Exception as exc:
        out["키_형식_오류"] = type(exc).__name__ + ": " + str(exc)[:120]

    # 4) 2025 리포트를 만들어 보면 값이 나오는지
    try:
        r25 = npage._build(2025, 12)
        tot = 0
        rows = 0
        for row in (r25 or {}).get("rows", []) or []:
            if isinstance(row, dict) and not row.get("is_total"):
                rows += 1
                try:
                    tot += int(row.get("close") or 0)
                except Exception:
                    pass
        out["2025_12_리포트"] = {"상세행": rows, "close합계_억": round(tot / 1e8, 2)}
    except Exception as exc:
        out["2025_리포트_오류"] = type(exc).__name__ + ": " + str(exc)[:120]

    # 5) base 에 전년 관련 이름이 있는지
    out["base_이름"] = sorted(
        n for n in dir(base)
        if not n.startswith("_") and re.search(r"prev|prior|last|ytd|year|hist", n, re.I)
    )
    return jsonify(out)
