"""누계에 마감 전 달을 단계 숫자로 넣는다 (가마감 → 잠정마감 → 확정마감).

배경 (2026-09-29)
  누계는 실적 원장(actuals)에 있는 달만 더해 왔다. 그래서 9월 가마감 회의에서
  '26년 누계(~9월)'라고 적힌 칸이 실제로는 1~8월이었다.
  회의에서는 이번 달 가마감부터 누계에 넣고, 잠정 → 확정으로 숫자를 바꿔 가는
  편이 흐름에 맞는다.

규칙
  대상은 보고 대상월(M)과 그 전월(M-1) 두 달이다. 그 이전 달은 원장 그대로다.
  한 행(사업부·지역·기존/신규)의 그 달 값은 아래 순서로 처음 있는 값을 쓴다.
    전월 M-1  원장 → 전월 마감(확정/잠정) → 전월 잠정마감 → 전월 가마감
    당월 M    원장 → 당월 마감 → 당월 가마감
  국내·해외 모두 그 달 값이 하나라도 있어야 그 달을 누계에 넣는다.
  한쪽이라도 없으면 그 달은 넣지 않는다(한쪽만 더해 증감이 틀어지는 것을 막는다).
  25년 누계는 26년에 넣은 마지막 달까지 원장 실적으로 맞춘다.

표시
  누계 제목에 마지막 달과 단계를 붙인다.  예) 누계 (~9월 가마감)
  단계는 그 달에 쓴 값 중 가장 이른 단계다(가마감 < 잠정 < 확정).

원칙
  화면·PPT 숫자만 바꾼다. 실적 원장(actuals)에는 아무것도 쓰지 않는다.
  원장에는 지금처럼 SalesOps 마감 연동값만 들어간다.
"""

import narrative_pptx_ui as pptx
import narrative_table_cfg as tcfg
import overseas_live as over
import pptx_field_fix as prev
import root_boot_cache as cache
import root_live_fetch as live

app = prev.app
base = live.base
ui = live.ui

RANK = {"가마감": 1, "잠정": 2, "확정": 3}
META = {}


def _prev(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _num(value):
    try:
        if value is None or value == "":
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _ledger(data, year, month, row):
    return ui.actual_value(data, year, month, row.get("business"), row.get("region"), row.get("kind"))


def _close_stage(year, month):
    """마감 원천이 말하는 단계. 모르면 확정으로 본다(원장에 들어간 값)."""
    stages = {}
    try:
        dom, _ = live._fetch(year, month)
        labels = {v.get("close_stage") for v in (dom or {}).values() if v.get("close_stage")}
        if "잠정마감" in labels:
            stages["국내"] = "잠정"
    except Exception:
        pass
    try:
        ovs, _ = over._load(year, month)
        finals = [v.get("final_close") for v in (ovs or {}).values()]
        provs = [v.get("provisional_close") for v in (ovs or {}).values()]
        if not any(finals) and any(provs):
            stages["해외"] = "잠정"
    except Exception:
        pass
    return stages


def _month_values(data, year, month, rows, is_current):
    """행별 (값, 단계). 값이 없으면 (None, None)."""
    close_stage = _close_stage(year, month)
    out = []
    for row in rows:
        region = row.get("region")
        ledger = _ledger(data, year, month, row)
        if ledger is not None:
            out.append((ledger, close_stage.get(region, "확정")))
            continue
        if is_current:
            chain = (("close", close_stage.get(region, "확정")), ("third_forecast", "가마감"))
        else:
            chain = (("prev_close", close_stage.get(region, "확정")),
                     ("prev_preclose", "잠정"), ("prev_first", "가마감"))
        picked = (None, None)
        for field, stage in chain:
            value = _num(row.get(field))
            if value is not None:
                picked = (value, stage)
                break
        out.append(picked)
    return out


def _covered(rows, values):
    for region in ("국내", "해외"):
        got = [v for row, (v, _) in zip(rows, values) if row.get("region") == region]
        # 모두 비었거나 모두 0이면 그 달 차수가 아직 없는 것이다.
        if got and not any(v for v in got):
            return False
    return True


def apply(report, year, month):
    rows = report.get("rows") if isinstance(report, dict) else None
    if not rows:
        return report
    details = [row for row in rows if not row.get("is_total")]
    data = base.read_store()
    py, pm = _prev(year, month)

    last = None  # (연, 월, 단계)
    added = {id(row): 0 for row in details}
    months_added = 0

    # 전월: 원장이 비어 있는 행만 단계 숫자로 채운다. 월 실적 칸도 같이 채운다.
    # 1월은 전월이 작년 12월이라 올해 누계에 들어가지 않는다.
    pvals = _month_values(data, py, pm, details, is_current=False) if py == year else []
    if py != year or _covered(details, pvals):
        for row, (value, _) in zip(details, pvals):
            if value is None or _ledger(data, py, pm, row) is not None:
                continue
            row.setdefault("hist", {})[pm] = value
            added[id(row)] += value
        stages = [s for _, s in pvals if s]
        last = (py, pm, min(stages, key=RANK.get) if stages else "확정")

        # 당월: 전월이 들어갔을 때만 이어서 넣는다.
        cvals = _month_values(data, year, month, details, is_current=True)
        if _covered(details, cvals):
            for row, (value, _) in zip(details, cvals):
                if value is not None:
                    added[id(row)] += value
            stages = [s for _, s in cvals if s]
            last = (year, month, min(stages, key=RANK.get) if stages else "확정")
            months_added = 1

    if py != year and not months_added:
        last = None
    if last is None:
        META[(year, month)] = {"through": month - 1, "stage": "", "label": "~%d월" % (month - 1)}
        return report

    through = last[1]
    for row in details:
        row["ytd"] = (row.get("ytd") or 0) + added[id(row)]
        row["avg"] = row["ytd"] / max(month - 1 + months_added, 1)
        if months_added:
            extra = ui.actual_value(data, year - 1, month, row.get("business"),
                                    row.get("region"), row.get("kind")) or 0
            row["prev_ytd"] = (row.get("prev_ytd") or 0) + extra
        prev_ytd = row.get("prev_ytd") or 0
        row["growth"] = ((row["ytd"] - prev_ytd) / prev_ytd) if prev_ytd else None

    for total in [row for row in rows if row.get("is_total")]:
        scope = details if total.get("is_grand") else [
            row for row in details if row.get("business") == total.get("business")
        ]
        total["ytd"] = sum(row.get("ytd") or 0 for row in scope)
        total["avg"] = sum(row.get("avg") or 0 for row in scope)
        total["prev_ytd"] = sum(row.get("prev_ytd") or 0 for row in scope)
        total["growth"] = ((total["ytd"] - total["prev_ytd"]) / total["prev_ytd"]) if total["prev_ytd"] else None
        hist = total.setdefault("hist", {})
        hist[pm] = sum((row.get("hist") or {}).get(pm, 0) or 0 for row in scope) if py == year else hist.get(pm)

    stage = "" if last[2] == "확정" else last[2]
    META[(year, month)] = {
        "through": through,
        "stage": stage,
        "label": ("~%d월 %s" % (through, stage)).strip(),
    }
    report["ytd_through"] = META[(year, month)]
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


# ---------- 화면: 누계 제목에 기간·단계를 붙인다 ----------

_original_render_report = ui.render_report


def render_report(report, user, capture=False):
    html = _original_render_report(report, user, capture)
    info = META.get((report.get("year"), report.get("month")))
    if not info:
        return html
    y = report.get("year")
    html = html.replace("<th colspan='2'>누계</th>",
                        "<th colspan='2'>누계 (%s)</th>" % info["label"], 1)
    html = html.replace("<th>%s년 누계</th>" % (y - 1),
                        "<th>%s년 누계 (~%d월)</th>" % (y - 1, info["through"]), 1)
    return html


ui.render_report = render_report


# ---------- PPT: 누계 열 제목 ----------

for _col in tcfg.HEAD:
    if _col.get("f") == "ytd":
        _col["label"] = "{cy}년 누계\n({ytd_to})"
    elif _col.get("f") == "prev_ytd":
        _col["label"] = "{py}년 누계\n({ytd_to_py})"

_original_ctx = pptx._ctx


def _ctx(year, month, meeting):
    ctx = _original_ctx(year, month, meeting)
    info = META.get((year, month))
    if info is None:
        try:
            live._build_report(year, month)
            info = META.get((year, month))
        except Exception:
            info = None
    if info:
        ctx["ytd_to"] = info["label"]
        ctx["ytd_to_py"] = "~%d월" % info["through"]
    else:
        ctx["ytd_to"] = ctx["ytd_to_py"] = "~%s월" % ctx.get("close_m")
    return ctx


pptx._ctx = _ctx
