"""3차 회차(3차 예상·3차 확정)를 SalesOps 연동에 실어 현황판에 채운다.

문제
  SalesOps /api/performance 는 third_estimated_amount, third_confirmed_amount 를
  내려주는데, browser_bridge._parse_doc 는 first·second·close 세 필드만 저장하고
  root_live_fetch._build_report 도 그 세 개만 행에 반영했다. 그래서 3차를 입력·
  확정해도 현황판의 3차 예상·3차 확정 칸이 계속 비어 있었다.

방식
  기존 모듈을 고치지 않고 두 지점만 감싼다.
    1) browser_bridge._parse_doc  → 스냅샷에 third_forecast·third_confirmed 저장
    2) root_live_fetch._build_report → 국내 행과 소계에 두 필드 반영
  스냅샷 형식은 그대로 두고 키만 늘리므로, 예전 스냅샷을 읽어도 문제가 없다
  (없는 키는 None 으로 남아 기존 동작과 같다).

값의 출처
  SalesOps 계약 필드를 그대로 쓴다. 화면 숫자를 옮겨 적지 않는다.
    third_estimated_amount  → 3차 예상
    third_confirmed_amount  → 3차 확정(ERP 실제 출고로 확정된 부분)
"""

import salesops_actual_sync as prev
import browser_bridge as bridge
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


_original_parse_doc = bridge._parse_doc


def _parse_doc(doc):
    """브라우저가 넘겨준 SalesOps 응답에서 3차까지 함께 저장한다."""
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


_original_build_report = live._build_report


def _build_report(year, month):
    """국내 행과 소계에 3차 예상·3차 확정을 채운다."""
    report = _original_build_report(year, month)
    try:
        current, _meta = live._fetch(year, month)
    except Exception:
        return report
    details = [row for row in report.get("rows", []) if not row.get("is_total")]
    for row in details:
        if row.get("region") != "국내":
            continue
        source = current.get((row.get("business"), "국내", row.get("kind"))) or {}
        for field in THIRD_FIELDS:
            if source.get(field) is not None:
                row[field] = source[field]
    for total in [row for row in report.get("rows", []) if row.get("is_total")]:
        scope = details if total.get("is_grand") else [
            row for row in details if row.get("business") == total.get("business")
        ]
        for field in THIRD_FIELDS:
            total[field] = live._sum(scope, field)
    return report


live._build_report = _build_report
