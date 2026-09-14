"""3차 회차 연동과 배너 문구를 SalesOps 실제 단계에 맞춘다.

문제 1 · 3차가 비어 있었다
  SalesOps /api/performance 는 third_estimated_amount, third_confirmed_amount 를
  내려주는데 받는 쪽이 1차·2차·마감만 썼다. 빠진 곳이 세 군데였다.
    1) browser_bridge._parse_doc      스냅샷에 3차를 저장하지 않음
    2) root_live_fetch._build_report  narrative 계열 화면
    3) root_boot_cache._build_report  현황판이 실제로 쓰는 캐시 경로(핵심)

문제 2 · 배너 문구가 고정이었다
  "8월 잠정마감 · 9월 2차"가 코드에 박혀 있어, 8월을 최종마감하고 9월 3차를
  확정해도 문구가 그대로였다. 월·마감단계·회차를 실제 값으로 만든다.
  마감단계는 SalesOps 응답의 close 블록(final/provisional)을 스냅샷에 함께
  저장해 쓴다.

값의 출처
  SalesOps 계약 필드를 그대로 쓴다. 화면 숫자를 옮겨 적지 않는다.
"""

import datetime

import salesops_actual_sync as prev
import browser_bridge as bridge
import root_boot_cache as cache
import root_live_fetch as live

app = prev.app
ui = live.ui

THIRD_FIELDS = ("third_forecast", "third_confirmed")
_CLOSE_STAGE = {}


def _num(value):
    try:
        if value is None or value == "":
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _stage_label(doc):
    close = doc.get("close") if isinstance(doc.get("close"), dict) else {}
    if close.get("final"):
        return "확정마감"
    if close.get("provisional"):
        return "잠정마감"
    if close.get("locked"):
        return "마감"
    return ""


# ---------- 1) 브라우저가 넘겨준 응답에서 3차·마감단계까지 저장 ----------

_original_parse_doc = bridge._parse_doc


def _parse_doc(doc):
    index = _original_parse_doc(doc)
    if not isinstance(doc, dict) or not index:
        return index
    stage = _stage_label(doc)
    for row in (doc.get("rows") or []):
        if not isinstance(row, dict):
            continue
        key = (row.get("business_division"), row.get("market"), row.get("customer_type"))
        target = index.get(key)
        if target is None:
            continue
        target["third_forecast"] = _num(row.get("third_estimated_amount"))
        target["third_confirmed"] = _num(row.get("third_confirmed_amount"))
        target["close_stage"] = stage
    return index


bridge._parse_doc = _parse_doc


# ---------- 2·3) 리포트 조립 시 국내 행과 소계에 3차 반영 ----------

def _fetch_index(module, year, month):
    fetch = getattr(module, "_fetch", None) or live._fetch
    try:
        return fetch(year, month)[0]
    except Exception:
        return {}


def _fill_third(module, report, year, month):
    rows = report.get("rows") if isinstance(report, dict) else None
    if not rows:
        return report
    current = _fetch_index(module, year, month)
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
    # 배너용: 전월 마감단계와 당월 회차·금액을 기억해 둔다.
    py, pm = ((year - 1, 12) if month == 1 else (year, month - 1))
    previous = _fetch_index(module, py, pm)
    stages = [v.get("close_stage") for v in previous.values() if v.get("close_stage")]
    domestic = [row for row in details if row.get("region") == "국내"]
    for field, label in (("third_forecast", "3차"), ("second", "2차"), ("first", "1차")):
        total = summer(domestic, field)
        if total:
            _CLOSE_STAGE[(year, month)] = {
                "previous_stage": stages[0] if stages else "마감",
                "round_label": label, "round_total": total,
                "previous_month": pm,
            }
            break
    return report


def _wrap_build_report(module):
    original = module._build_report

    def _build_report(year, month):
        return _fill_third(module, original(year, month), year, month)

    module._build_report = _build_report


def _wrap_banner(module, meta_key):
    original = module._banner

    def _banner(report):
        html = original(report)
        if "국내연동 OK" not in html:
            return html
        today = datetime.date.today()
        info = _CLOSE_STAGE.get((today.year, today.month)) or {}
        stage = info.get("previous_stage") or "마감"
        previous_month = info.get("previous_month") or (today.month - 1 or 12)
        meta = report.get(meta_key, {})
        html = html.replace(
            f"{previous_month}월 잠정마감", f"{previous_month}월 {stage}",
        )
        if info.get("round_label") and info.get("round_label") != "2차":
            html = html.replace(
                f"{today.month}월 2차 {ui.money_m(meta.get('second_total'))}백만원",
                f"{today.month}월 {info['round_label']} {ui.money_m(info.get('round_total'))}백만원",
            )
        return html

    module._banner = _banner


for module, meta_key in ((live, "live_meta"), (cache, "boot_cache")):
    _wrap_build_report(module)
    _wrap_banner(module, meta_key)

# 현황판은 캐시를 거쳐 렌더되므로, 이미 담긴 캐시를 비워 새 값으로 다시 채운다.
try:
    cache._CACHE.clear()
    cache._META.clear()
except Exception:
    pass
