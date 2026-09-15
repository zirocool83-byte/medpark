"""SalesOps 연동을 회의 흐름에 맞게 현황판에 채운다.

바로잡은 것
  1) 3차가 비어 있었다
     SalesOps 는 third_estimated/third_confirmed 를 내려주는데 받는 쪽이
     1차·2차·마감만 썼다. 빠진 곳이 세 군데였다.
       browser_bridge._parse_doc      스냅샷에 저장 안 함
       root_live_fetch._build_report  narrative 계열 화면
       root_boot_cache._build_report  현황판이 쓰는 캐시 경로(핵심)
  2) 마감이 8월에만 들어왔다(root_boot_cache 가 month == 8 고정)
  3) 열 구성이 회의 흐름과 달랐다
     3차가 확정·예상 두 칸을 차지하고 가마감·잠정마감이 없었다.
       전월 비교  전월 가마감 · 전월 잠정마감 · 전월 확정마감
       당월      1차 예상 · 2차 예상 · 3차 예상 · 가마감 · 마감
     표 구조(열 개수)는 그대로 두고 값과 머리글만 바꾼다.
  4) 배너 문구가 "8월 잠정마감 · 9월 2차"로 고정이었다
  5) 지금이 몇 차 기간인지 표에 표시가 없었다
     당월 진행 회차와 전월 확정마감을 함께 강조한다. 회의에서 보는 두 기준이
     '��난달 확정 결과'와 '이번달 진행 숫자'이기 때문이다. 성격이 달라 색을
     구분한다(확정=초록 계열, 진행=파랑 계열).
  6) 가마감·마감 칸이 노란 '수동 입력' 색이었고 값이 0으로 보였다
     연동값으로 채우는 칸이므로 노란색을 떼고, 아직 시점이 안 된 값은 0 대신
     '-' 로 표시한다. 0원으로 읽히는 오해를 막는다.

값의 출처
  SalesOps /api/performance 계약 필드만 쓴다. 화면 숫자를 옮겨 적지 않는다.
"""

import datetime
import re

import salesops_actual_sync as prev
import browser_bridge as bridge
import root_boot_cache as cache
import root_live_fetch as live

app = prev.app
ui = live.ui

_BANNER = {}

# 당월 회차 열의 CSS 클래스. excel_ui 의 셀 클래스와 같다.
STAGE_CLASS = {"1차": "c1", "2차": "c2", "3차": "c3c", "가마감": "c3f", "마감": "cc"}
STAGE_HEADER = {"1차": "1차 예상", "2차": "2차 예상", "3차": "3차 예상",
                "가마감": "가마감", "마감": "마감"}


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


def current_round(today=None):
    """오늘이 어느 회차 기간인지. 회의는 5일 2차 · 15일 3차 · 25일 가마감."""
    day = (today or datetime.date.today()).day
    if day >= 24:
        return "가마감"
    if day >= 15:
        return "3차"
    if day >= 5:
        return "2차"
    return "1차"


# ---------- 1) 브라우저가 넘겨준 응답을 전부 스냅샷에 담는다 ----------

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
        target["flash_close"] = _num(row.get("flash_close_amount"))
        target["provisional_close"] = _num(row.get("provisional_close_amount"))
        target["close_stage"] = stage
    return index


bridge._parse_doc = _parse_doc


# ---------- 2·3) 리포트 조립: 회의 흐름대로 값을 앉힌다 ----------

def _fetch_index(module, year, month):
    fetch = getattr(module, "_fetch", None) or live._fetch
    try:
        return fetch(year, month)[0]
    except Exception:
        return {}


def _fill(module, report, year, month):
    rows = report.get("rows") if isinstance(report, dict) else None
    if not rows:
        return report
    current = _fetch_index(module, year, month)
    py, pm = ((year - 1, 12) if month == 1 else (year, month - 1))
    previous = _fetch_index(module, py, pm)
    details = [row for row in rows if not row.get("is_total")]

    for row in details:
        if row.get("region") != "국내":
            continue
        key = (row.get("business"), "국내", row.get("kind"))
        cur = current.get(key) or {}
        old = previous.get(key) or {}
        # 전월 비교: 가마감 → 잠정마감 → 확정마감
        if old.get("flash_close") is not None:
            row["prev_first"] = old["flash_close"]
        if old.get("provisional_close") is not None:
            row["prev_preclose"] = old["provisional_close"]
        if old.get("close") is not None:
            row["prev_close"] = old["close"]
        # 당월: 1차 → 2차 → 3차 예상 → 가마감 → 마감
        for field in ("first", "second"):
            if cur.get(field) is not None:
                row[field] = cur[field]
        if cur.get("third_forecast") is not None:
            row["third_confirmed"] = cur["third_forecast"]
        row["third_forecast"] = cur.get("flash_close")
        close = cur.get("close") or cur.get("provisional_close")
        row["close"] = close
        row["close_has"] = close is not None

    summer = getattr(module, "_sum", None) or live._sum
    fields = (
        "prev_first", "prev_preclose", "prev_close", "first", "second",
        "third_confirmed", "third_forecast", "close", "next_first", "carryover",
        "qproj", "october", "november", "december", "q4proj", "second_half",
    )
    for total in [row for row in rows if row.get("is_total")]:
        scope = details if total.get("is_grand") else [
            row for row in details if row.get("business") == total.get("business")
        ]
        for field in fields:
            total[field] = summer(scope, field) or None
        total["close_has"] = bool(scope) and all(row.get("close_has") for row in scope)

    stages = [v.get("close_stage") for v in previous.values() if v.get("close_stage")]
    domestic = [row for row in details if row.get("region") == "국내"]
    _BANNER[(year, month)] = {
        "previous_month": pm,
        "previous_stage": stages[0] if stages else "마감",
        "second_total": summer(domestic, "second"),
    }
    for field, label in (("third_confirmed", "3차"), ("second", "2차"), ("first", "1차")):
        total = summer(domestic, field)
        if total:
            _BANNER[(year, month)].update({"round_label": label, "round_total": total})
            break
    return report


def _wrap_build_report(module):
    original = module._build_report

    def _build_report(year, month):
        return _fill(module, original(year, month), year, month)

    module._build_report = _build_report


def _wrap_banner(module):
    original = module._banner

    def _banner(report):
        html = original(report)
        if "국내연동 OK" not in html:
            return html
        info = _BANNER.get((report.get("year"), report.get("month"))) or {}
        month = report.get("month") or datetime.date.today().month
        previous_month = info.get("previous_month") or (month - 1 or 12)
        html = html.replace(
            f"{previous_month}월 잠정마감",
            f"{previous_month}월 {info.get('previous_stage') or '마감'}",
        )
        if info.get("round_label") and info["round_label"] != "2차":
            html = html.replace(
                f"{month}월 2차 {ui.money_m(info.get('second_total'))}백만원",
                f"{month}월 {info['round_label']} {ui.money_m(info.get('round_total'))}백만원",
            )
        return html

    module._banner = _banner


for _module in (live, cache):
    _wrap_build_report(_module)
    _wrap_banner(_module)


# ---------- 4·5·6) 머리글 정리 · 회차 강조 · 색과 빈값 표시 ----------

_STAGE_CSS = """<style>
/* 가마감·마감은 연동값으로 채우는 칸이다. 수동 입력을 뜻하는 노란색을 뗀다. */
table.report td.c3f { background:#f7fbff !important; }
table.report td.cc { background:#f4f7fa !important; }
/* 이번달 진행 회차 */
table.report td.stage-now, table.report th.stage-now { background:#e8f3ff !important; }
table.report th.stage-now { color:#0d3b66; }
table.report td.stage-now { font-weight:800; box-shadow: inset 2px 0 0 #2f7ac6, inset -2px 0 0 #2f7ac6; }
table.report tr.grand td.stage-now, table.report tr.subtotal td.stage-now { background:#d7e9fb !important; }
/* 지난달 확정마감 */
table.report td.stage-done, table.report th.stage-done { background:#eaf6ee !important; }
table.report th.stage-done { color:#14532d; }
table.report td.stage-done { font-weight:800; box-shadow: inset 2px 0 0 #2f9e74, inset -2px 0 0 #2f9e74; }
table.report tr.grand td.stage-done, table.report tr.subtotal td.stage-done { background:#dbeee2 !important; }
.stage-now-note { margin:0 0 10px; padding:8px 12px; border-radius:7px; border:1px solid #bcd8f1;
  background:#eef6ff; font-size:13px; font-weight:700; color:#0d3b66; }
.stage-now-note b { color:#14532d; }
</style>"""

_original_render_report = ui.render_report


def render_report(report, user, capture=False):
    html = _original_render_report(report, user, capture)
    month = report.get("month")
    previous_month = ((month - 1) or 12) if month else None
    stage = (_BANNER.get((report.get("year"), month)) or {}).get("previous_stage") or "마감"
    if previous_month:
        html = html.replace(
            f"<th>{previous_month}월 1차</th><th>{previous_month}월 가마감</th>"
            f"<th>{previous_month}월 마감</th>",
            f"<th>{previous_month}월 가마감</th><th>{previous_month}월 잠정마감</th>"
            f"<th class='stage-done'>{previous_month}월 {stage}</th>",
            1,
        )
    html = html.replace(
        "<th>3차 확정</th><th>3차 예상</th><th>실제 마감</th>",
        "<th>3차 예상</th><th>가마감</th><th>마감</th>",
        1,
    )

    # 전월 확정마감 열(전월 비교 세 번째 칸)에 표시
    html = re.sub(
        r"(<td>[^<]*</td><td>[^<]*</td>)(<td>)(?=[^<]*</td><td class='c1')",
        r"\1<td class='stage-done'>",
        html,
    )

    # 이번달 진행 회차 열에 표시
    today = datetime.date.today()
    round_label = current_round(today)
    header = STAGE_HEADER[round_label]
    cell_class = STAGE_CLASS[round_label]
    html = html.replace(f"<th>{header}</th>", f"<th class='stage-now'>{header}</th>", 1)
    html = html.replace(f"<td class='{cell_class}'>", f"<td class='{cell_class} stage-now'>")
    html = html.replace(
        "<div class='table-wrap'>",
        f"<p class='stage-now-note'>오늘 {today.month}월 {today.day}일 · "
        f"{round_label} 기간입니다. 이번달 {header}(파랑)과 "
        f"<b>{previous_month}월 {stage}(초록)</b>을 강조했습니다.</p>"
        "<div class='table-wrap'>",
        1,
    )
    return html.replace("</head>", _STAGE_CSS + "</head>", 1)


ui.render_report = render_report

# 현황판은 캐시를 거쳐 렌더되므로, 이미 담긴 캐시를 비워 새 값으로 다시 채운다.
try:
    cache._CACHE.clear()
    cache._META.clear()
except Exception:
    pass
