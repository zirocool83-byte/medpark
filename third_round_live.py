"""3차 회차(3차 예상·3차 확정)를 SalesOps 연동에 실어 현황판에 채운다.

문제
  SalesOps /api/performance 는 third_estimated_amount, third_confirmed_amount 를
  내려주는데 받는 쪽이 세 필드(1차·2차·마감)만 쓰고 있었다. 그래서 3차를
  입력·확정해도 현황판의 3차 예상·3차 확정 칸이 계속 비어 있었다.
  빠진 곳이 세 군데였다.
    1) browser_bridge._parse_doc      스냅샷에 3차를 저장하지 않음
    2) root_live_fetch._build_report  narrative 계열 화면에 반영하지 않음
    3) root_boot_cache._build_report  현황판이 실제로 쓰는 경로. 여기가 핵심
  현황판은 root_direct_endpoint → root_boot_cache_stable → root_boot_cache
  캐시를 거쳐 렌더되므로, 3)을 고치지 않으면 화면은 그대로다.

방식
  기존 모듈을 고치지 않고 위 세 지점만 감싼다. 스냅샷 형식은 그대로 두고
  키만 늘리므로 예전 스냅샷을 읽어도 동작이 같다(없는 키는 None).

값의 출처
  SalesOps 계약 필드를 그대로 쓴다. 화면 숫자를 옮겨 적지 않는다.
    third_estimated_amount → 3차 예상(third_forecast)
    third_confirmed_amount → 3차 확정(third_confirmed, ERP 실제 출고분)
"""

import salesops_actual_sync as prev
import browser_bridge as bridge
import root_boot_cache as cache
import root_live_fetch as live

app = prev.app

THIRD_FIELDS = ("third_forecast", "third_confirmed")


def _num(value):
    try:
        if value is None or value == "":
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


# ---------- 1) 브라우저가 넘겨준 응답에서 3차까지 저장 ----------

_original_parse_doc = bridge._parse_doc


def _parse_doc(doc):
    index = _original_parse_doc(doc)
    if not isinstance(doc, dict) or not index:
        return index
    for row in (doc.get("rows") or []):
        if not isinstance(row, dict):
            continue
        key = (row.get("business_division"), row.get("market"), row.get("customer_type"))
        target = index.get(key)
        if target is None:
            continue
        target["third_forecast"] = _num(row.get("third_estimated_amount"))
        target["third_confirmed"] = _num(row.get("third_confirmed_amount"))
    return index


bridge._parse_doc = _parse_doc


# ---------- 2·3) 리포트 조립 시 국내 행과 소계에 3차 반영 ----------

def _fill_third(module, report, year, month):
    try:
        current, _meta = module._fetch(year, month) if hasattr(module, "_fetch") else live._fetch(year, month)
    except Exception:
        return report
    rows = report.get("rows") if isinstance(report, dict) else None
    if not rows:
        return report
    details = [row for row in rows if not row.get("is_total")]
    for row in details:
        if row.get("region") != "국내":
            continue
        source = current.get((row.get("business"), "국내", row.get("kind"))) or {}
        for field in THIRD_FIELDS:
            if source.get(field) is not None:
                row[field] = source[field]
    summer = getattr(module, "_sum", None) or live._sum
    for total in [row for row in rows if row.get("is_total")]:
        scope = details if total.get("is_grand") else [
            row for row in details if row.get("business") == total.get("business")
        ]
        for field in THIRD_FIELDS:
            total[field] = summer(scope, field)
    return report


def _wrap_build_report(module):
    original = module._build_report

    def _build_report(year, month):
        return _fill_third(module, original(year, month), year, month)

    module._build_report = _build_report


_wrap_build_report(live)
_wrap_build_report(cache)

# 현황판은 캐시를 거쳐 렌더되므로, 이미 담긴 캐시를 비워 새 값으로 다시 채운다.
try:
    cache._CACHE.clear()
    cache._META.clear()
except Exception:
    pass
