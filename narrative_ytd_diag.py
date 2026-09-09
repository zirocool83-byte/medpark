"""누계 계산 점검.

리포트의 26년 누계가 8월 잠정마감을 온전히 반영하지 못하고 있다.
어느 축에서 얼마가 비는지 사업부·지역별로 나란히 찍어 원인을 좁힌다.

읽기 전용이다. 아무것도 고치지 않는다.
"""

import narrative_pptx_ui as prev
import narrative_page as npage
import root_live_fetch as live
from flask import jsonify, request

try:
    import narrative_history as hist
except Exception:
    hist = None

app = prev.app
base = npage.base


def _n(v):
    if v is None:
        return 0
    try:
        return int(round(float(v)))
    except Exception:
        return 0


@app.get("/narrative-ytd-diag")
def narrative_ytd_diag():
    if not npage._current_user():
        return jsonify({"error": "unauthorized"}), 401
    try:
        year = int(request.args.get("year", 2026))
        month = int(request.args.get("month", 9))
    except Exception:
        year, month = 2026, 9

    report = npage._build(year, month)
    if report is None:
        return jsonify({"error": "report_build_failed"}), 500

    per = {}
    keys_seen = set()
    for row in report.get("rows", []) or []:
        if not isinstance(row, dict) or row.get("is_total"):
            continue
        b, g, k = row.get("business"), row.get("region"), row.get("kind")
        if not (b and g and k):
            continue
        keys_seen.add(k)
        slot = per.setdefault("%s|%s" % (b, g), {"ytd": 0, "prev_close": 0, "prev_preclose": 0})
        slot["ytd"] += _n(row.get("ytd"))
        slot["prev_close"] += _n(row.get("prev_close"))
        slot["prev_preclose"] += _n(row.get("prev_preclose"))

    out = {}
    for key, v in sorted(per.items()):
        biz, region = key.split("|")
        row = {
            "ytd_억": round(v["ytd"] / 1e8, 2),
            "전월마감_억": round(v["prev_close"] / 1e8, 2),
            "전월가마감_억": round(v["prev_preclose"] / 1e8, 2),
        }
        if hist is not None:
            plan7 = hist.cumulative(hist.PLAN2026, biz, region, 7)
            row["25년누계8월_억"] = round((hist.ytd_2025(biz, region, 8) or 0) / 1e8, 2)
            row["26사업계획7월_억"] = round((plan7 or 0) / 1e8, 2)
        out[key] = row

    total_ytd = sum(v["ytd"] for v in per.values())
    total_close = sum(v["prev_close"] for v in per.values())

    # actuals 저장소에 8월 값이 실제로 어떻게 들어 있는지
    actual_aug = {}
    try:
        store = base.read_store() or {}
        actuals = store.get("actuals") or {}
        for b in ("덴탈", "메디컬", "에스테틱"):
            for g in ("국내", "해외"):
                s = 0
                found = 0
                for k in ("기존", "신규"):
                    try:
                        key = base.actual_key(year, month - 1, b, g, k)
                    except Exception:
                        continue
                    if key in actuals:
                        found += 1
                        s += _n(actuals.get(key))
                actual_aug["%s|%s" % (b, g)] = {"금액_억": round(s / 1e8, 2), "키_개수": found}
    except Exception as exc:
        actual_aug = {"error": type(exc).__name__ + ": " + str(exc)[:120]}

    return jsonify({
        "기준": "%04d-%02d 리포트" % (year, month),
        "행_구분값": sorted(keys_seen),
        "사업부지역별": out,
        "합계_ytd_억": round(total_ytd / 1e8, 2),
        "합계_전월마감_억": round(total_close / 1e8, 2),
        "저장소_전월actuals": actual_aug,
        "리포트_상위키": sorted([k for k in report.keys() if k != "rows"]),
    })
