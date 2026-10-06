"""확정마감 칸은 확정된 지역만 채운다 (2026-10-06).

증상
  9월이 아직 잠정마감인데 현황판 '9월 확정마감' 칸에 국내 숫자만 들어왔다.
  국내는 SalesOps 잠정마감 금액이 실적 원장(actuals)에 들어가 있어서
  전월 마감 칸이 원장 값을 그대로 읽었고, 해외는 확정 전이라 비어 있었다.
  국내만 찬 합계는 확정마감처럼 읽혀 오해를 낳는다.

규칙
  전월 확정마감 칸(prev_close)은 지역별로 확정됐을 때만 채운다.
    국내 : SalesOps 연동값의 마감 단계가 '확정마감'
    해외 : 해외 오더 파이프라인 확정마감 금액이 있음
  확정 전이면 그 지역 행은 빈칸, 소계·합계도 빈 행이 하나라도 있으면 빈칸.
  잠정마감 숫자는 '잠정마감' 칸(prev_preclose)에 그대로 있다.
  PPT 5일 회의 표의 '전월 잠정마감' 칸도 잠정마감 자리(prev_preclose)에서 읽게 한다.

  계산·원장은 건드리지 않는다. 화면과 PPT 에 보이는 칸만 정리한다.
"""

import narrative_table_cfg as tcfg
import overseas_live as over
import root_boot_cache as cache
import root_live_fetch as live
import ytd_stage as prev

app = prev.app


def _prev(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def confirmed(year, month):
    out = {"국내": False, "해외": False}
    try:
        dom, _ = live._fetch(year, month)
        out["국내"] = any((v or {}).get("close_stage") == "확정마감" for v in (dom or {}).values())
    except Exception:
        pass
    try:
        ovs, _ = over._load(year, month)
        out["해외"] = any((v or {}).get("final_close") for v in (ovs or {}).values())
    except Exception:
        pass
    return out


def apply(report, year, month):
    rows = report.get("rows") if isinstance(report, dict) else None
    if not rows:
        return report
    ok = confirmed(*_prev(year, month))
    details = [r for r in rows if not r.get("is_total")]
    for r in details:
        if not ok.get(r.get("region")):
            r["prev_close"] = None
    for t in [r for r in rows if r.get("is_total")]:
        scope = details if t.get("is_grand") else [
            r for r in details if r.get("business") == t.get("business")]
        vals = [r.get("prev_close") for r in scope]
        t["prev_close"] = sum(vals) if scope and all(v is not None for v in vals) else None
    report["close_confirmed"] = ok
    return report


def _wrap(module):
    original = module._build_report

    def _build_report(year, month):
        report = original(year, month)
        try:
            return apply(report, year, month)
        except Exception:
            return report

    module._build_report = _build_report


for _module in (live, cache):
    _wrap(_module)

for _col in (tcfg.MIDDLE.get("r1") or []):
    if _col.get("label") == "{pm}월 잠정마감" and _col.get("f") == "prev_close":
        _col["f"] = "prev_preclose"
