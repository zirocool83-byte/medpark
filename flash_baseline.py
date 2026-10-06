"""가마감은 회의한 날 숫자로 고정하고, 그 뒤 바뀐 것은 기록으로 남긴다 (2026-10-06).

배경
  9월 가마감 회의 때 총액은 1,411.6백만원(14.12억)이었다. 회의 뒤
    국내 : SalesOps 가 25일 가마감을 ERP 실적으로 다시 계산 (메디컬 +38.6 등)
    해외 : Medicaid 9월 편입 정정 (+35.6)
  으로 지금은 1,486.1백만원이 됐다. 가마감 대비 잠정·확정을 비교하려면
  회의 때 보고한 숫자가 기준이어야 한다.

규칙
  1) 고정 시점 : 가마감 회의 PPT 를 내려받는 날. 그날 안에는 다시 받으면
     새 숫자로 덮고, 다음 날부터는 잠긴다(회의한 날 1차 고정).
     9월은 회의 당일(9/29 09:23) 연동값으로 복원해 고정했다.
  2) 고정된 달의 '가마감' 칸(당월 가마감, 다음 달 화면의 전월 가마감,
     PPT·문안 포함)은 고정값을 보여준다.
  3) 고정 뒤 원천 숫자가 바뀌면 사업부·지역·구분별로 언제 무엇이 얼마나
     바뀌었는지 기록에 쌓는다. 현황판 아래와 /flash-baseline 화면에서 본다.
  계산·원장·원천 데이터는 건드리지 않는다.
"""

import datetime
import json
import os
import threading
from pathlib import Path

from flask import jsonify, request

import close_confirmed_only as prev
import narrative_pptx_ui as pptx
import root_boot_cache as cache
import root_live_fetch as live

app = prev.app
base = live.base
ui = live.ui

PATH = Path(base.DATA_DIR) / "flash_baseline.json"
_LOCK = threading.Lock()
_RAW = threading.local()
KST = datetime.timezone(datetime.timedelta(hours=9))

SEED_2026_09 = {
    "fixed_at": "2026-09-29 09:23",
    "source": "9월 가마감 회의 당일 연동값 복원(국내 SalesOps 09:23 · 해외 오더 파이프라인 09:23)",
    "rows": {
        "덴탈|국내|기존": 170170723, "덴탈|국내|신규": 6724096,
        "메디컬|국내|기존": 629481862, "메디컬|국내|신규": 19151403,
        "에스테틱|국내|기존": 16000000, "에스테틱|국내|신규": 1100000,
        "덴탈|해외|기존": 178621865, "덴탈|해외|신규": 354002994,
        "메디컬|해외|기존": 7656837, "메디컬|해외|신규": 13010973,
        "에스테틱|해외|기존": 4407626, "에스테틱|해외|신규": 11301605,
    },
    "seed_history": [
        {"at": "2026-09-29 15:28", "axis": "덴탈|해외|기존", "from": 178621865, "to": 214192253,
         "note": "해외 Medicaid 9월 편입 정정(10월 1차에서 이동)"},
        {"at": "2026-10-06 22:30", "axis": "메디컬|국내|기존", "from": 629481862, "to": None,
         "note": "SalesOps 가마감 재계산(ERP 실적 반영) — 회의 뒤 변경, 변경 시각은 기록 시작 전"},
        {"at": "2026-10-06 22:30", "axis": "덴탈|국내|기존", "from": 170170723, "to": None,
         "note": "SalesOps 가마감 재계산(ERP 실적 반영) — 회의 뒤 변경, 변경 시각은 기록 시작 전"},
    ],
}


def _now():
    return datetime.datetime.now(KST)


def _key(year, month):
    return "%04d-%02d" % (int(year), int(month))


def _load():
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save(data):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PATH)


def _axis(row):
    return "%s|%s|%s" % (row.get("business"), row.get("region"), row.get("kind"))


def _num(v):
    try:
        return None if v is None else int(round(float(v)))
    except (TypeError, ValueError):
        return None


def current_values(year, month):
    """고정을 적용하지 않은 지금 원천의 가마감 값."""
    _RAW.on = True
    try:
        rep = live._build_report(int(year), int(month))
    finally:
        _RAW.on = False
    out = {}
    for r in (rep or {}).get("rows", []) or []:
        if not r.get("is_total"):
            out[_axis(r)] = _num(r.get("third_forecast"))
    return out


def _seed(data):
    if "2026-09" in data:
        return data
    s = SEED_2026_09
    cur = None
    try:
        cur = current_values(2026, 9)
    except Exception:
        cur = {}
    hist = []
    for h in s["seed_history"]:
        h = dict(h)
        if h["to"] is None:
            h["to"] = (cur or {}).get(h["axis"])
        hist.append(h)
    data["2026-09"] = {"fixed_at": s["fixed_at"], "source": s["source"],
                       "rows": dict(s["rows"]), "history": hist,
                       "last_seen": dict(cur or {})}
    _save(data)
    return data


def freeze(year, month, source):
    """그날 첫 고정이거나 같은 날 다시 받은 경우에만 고정값을 쓴다."""
    k = _key(year, month)
    today = _now().strftime("%Y-%m-%d")
    with _LOCK:
        data = _seed(_load())
        rec = data.get(k)
        if rec and not str(rec.get("fixed_at", "")).startswith(today):
            return {"status": "locked", "fixed_at": rec.get("fixed_at")}
        cur = current_values(year, month)
        if not any(v for v in cur.values() if v):
            return {"status": "empty"}
        hist = list((rec or {}).get("history") or [])
        data[k] = {"fixed_at": _now().strftime("%Y-%m-%d %H:%M"), "source": source,
                   "rows": cur, "history": hist, "last_seen": dict(cur)}
        _save(data)
        return {"status": "fixed", "total": sum(v or 0 for v in cur.values())}


def _track(year, month, rec, cur):
    """고정 뒤 원천이 바뀌면 기록한다."""
    seen = rec.setdefault("last_seen", {})
    changed = False
    for ax, v in cur.items():
        if v is None:
            continue
        old = seen.get(ax)
        if old is not None and old != v:
            rec.setdefault("history", []).append(
                {"at": _now().strftime("%Y-%m-%d %H:%M"), "axis": ax, "from": old, "to": v,
                 "note": "원천 변경 감지"})
            changed = True
        if old != v:
            seen[ax] = v
            changed = True
    return changed


def baseline(year, month):
    with _LOCK:
        data = _seed(_load())
        return data.get(_key(year, month))


def _apply(report, year, month):
    if getattr(_RAW, "on", False):
        return report
    rows = report.get("rows") if isinstance(report, dict) else None
    if not rows:
        return report
    details = [r for r in rows if not r.get("is_total")]
    py, pm = ((year - 1, 12) if month == 1 else (year, month - 1))
    targets = (((year, month), "third_forecast"), ((py, pm), "prev_first"))
    info = {}
    with _LOCK:
        data = _seed(_load())
        dirty = False
        for (y, m), field in targets:
            rec = data.get(_key(y, m))
            if not rec:
                continue
            cur = {_axis(r): _num(r.get(field)) for r in details}
            dirty |= _track(y, m, rec, cur)
            for r in details:
                ax = _axis(r)
                if ax in rec["rows"]:
                    r[field] = rec["rows"][ax]
            info[field] = {"month": _key(y, m), "fixed_at": rec.get("fixed_at"),
                           "fixed_total": sum(v or 0 for v in rec["rows"].values()),
                           "current_total": sum(v or 0 for v in cur.values() if v)}
        if dirty:
            _save(data)
    for t in [r for r in rows if r.get("is_total")]:
        scope = details if t.get("is_grand") else [r for r in details if r.get("business") == t.get("business")]
        for field in info:
            vals = [r.get(field) for r in scope if r.get(field) is not None]
            t[field] = sum(vals) if vals else None
    if info:
        report["flash_baseline"] = info
    return report


def _wrap(module):
    original = module._build_report

    def _build_report(year, month):
        report = original(year, month)
        try:
            return _apply(report, year, month)
        except Exception:
            return report

    module._build_report = _build_report


for _module in (live, cache):
    _wrap(_module)


# ---------- 가마감 회의 PPT 를 받는 날 고정 ----------

_orig_pptx_view = app.view_functions.get("narrative_pptx")


def _pptx_with_freeze(*args, **kwargs):
    try:
        payload = request.get_json(silent=True) or {}
        key = str(payload.get("key") or "")
        if key.endswith(":pre") and len(key) >= 7:
            y, m = int(key[:4]), int(key[5:7])
            freeze(y, m, "가마감 회의 PPT 내려받기")
    except Exception:
        pass
    return _orig_pptx_view(*args, **kwargs)


if _orig_pptx_view:
    app.view_functions["narrative_pptx"] = _pptx_with_freeze


# ---------- 화면: 고정값 안내 · 변경 기록 ----------

def _m(v):
    return "-" if v is None else "{:,.1f}".format(v / 1e6)


def _history_html(month_key, rec, limit=12):
    hist = (rec or {}).get("history") or []
    if not hist:
        return "<p style='font-size:15px;margin:4px 0'>회의 뒤 바뀐 것이 없습니다.</p>"
    rows = []
    for h in hist[-limit:][::-1]:
        d = (h.get("to") or 0) - (h.get("from") or 0)
        arrow = ("<b style='color:#C00000'>▲%s</b>" % _m(d)) if d > 0 else (
            ("<b style='color:#1F4E9E'>▼%s</b>" % _m(-d)) if d < 0 else "-")
        rows.append("<tr><td>%s</td><td>%s</td><td style='text-align:right'>%s</td>"
                    "<td style='text-align:right'>%s</td><td style='text-align:right'>%s</td><td>%s</td></tr>"
                    % (h.get("at", ""), h.get("axis", "").replace("|", " · "), _m(h.get("from")),
                       _m(h.get("to")), arrow, ui.esc(h.get("note", ""))))
    return ("<table style='font-size:15px;border-collapse:collapse' cellpadding='6' border='1'>"
            "<tr style='background:#EDF2F6'><th>기록 시각</th><th>사업부 · 지역 · 구분</th><th>이전</th>"
            "<th>이후</th><th>변경</th><th>내용</th></tr>%s</table>" % "".join(rows))


_orig_render = ui.render_report


def render_report(report, user, capture=False):
    html = _orig_render(report, user, capture)
    info = (report or {}).get("flash_baseline") or {}
    if capture or not info:
        return html
    parts = []
    for field, i in info.items():
        rec = baseline(*map(int, i["month"].split("-")))
        diff = i["current_total"] - i["fixed_total"]
        parts.append(
            "<div style='margin:14px 0;padding:12px 14px;border:1px solid #C9D2DA;border-radius:8px;background:#FAFBFC'>"
            "<p style='font-size:17px;font-weight:800;margin:0 0 6px'>%s 가마감은 회의 숫자로 고정돼 있습니다 · "
            "고정 %s백만원 (%s)</p>"
            "<p style='font-size:15px;margin:0 0 8px'>지금 원천 숫자 %s백만원 · 회의 뒤 변경 %s백만원 · "
            "<a href='/flash-baseline?month=%s'>변경 기록 전체 보기</a></p>%s</div>"
            % (i["month"], _m(i["fixed_total"]), i.get("fixed_at") or "-", _m(i["current_total"]),
               ("▲" if diff > 0 else "▼" if diff < 0 else "") + _m(abs(diff)), i["month"],
               _history_html(i["month"], rec, limit=6)))
    block = "".join(parts)
    if "<div class='caption'>" in html:
        return html.replace("<div class='caption'>", block + "<div class='caption'>", 1)
    return html.replace("</main>", block + "</main>", 1)


ui.render_report = render_report


@app.get("/flash-baseline")
def flash_baseline_view():
    try:
        user = base.current_user()
    except Exception:
        user = None
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    month = (request.args.get("month") or "2026-09").strip()
    try:
        y, m = int(month[:4]), int(month[5:7])
    except Exception:
        return jsonify({"error": "month=YYYY-MM"}), 400
    rec = baseline(y, m)
    if request.args.get("format") == "json":
        return jsonify({"month": month, "baseline": rec})
    if not rec:
        body = "<p style='font-size:17px'>%s 가마감은 아직 고정되지 않았습니다. 가마감 회의 PPT를 내려받는 날 고정됩니다.</p>" % month
    else:
        cur = current_values(y, m)
        trs = []
        for ax in sorted(rec["rows"]):
            f, c = rec["rows"].get(ax), cur.get(ax)
            d = (c or 0) - (f or 0)
            trs.append("<tr><td>%s</td><td style='text-align:right'>%s</td><td style='text-align:right'>%s</td>"
                       "<td style='text-align:right;color:%s'>%s</td></tr>"
                       % (ax.replace("|", " · "), _m(f), _m(c), "#C00000" if d > 0 else "#1F4E9E",
                          (("▲" if d > 0 else "▼") + _m(abs(d))) if d else "-"))
        ft = sum(v or 0 for v in rec["rows"].values()); ct = sum(v or 0 for v in cur.values() if v)
        body = ("<p style='font-size:17px'><b>고정 %s</b> · %s</p>"
                "<table style='font-size:16px;border-collapse:collapse' cellpadding='7' border='1'>"
                "<tr style='background:#EDF2F6'><th>사업부 · 지역 · 구분</th><th>회의 고정 (백만원)</th>"
                "<th>지금 원천 (백만원)</th><th>차이</th></tr>%s"
                "<tr style='font-weight:800;background:#F3F6F9'><td>합계</td><td style='text-align:right'>%s</td>"
                "<td style='text-align:right'>%s</td><td style='text-align:right'>%s</td></tr></table>"
                "<h3 style='font-size:18px;margin-top:20px'>변경 기록</h3>%s"
                % (rec.get("fixed_at"), ui.esc(rec.get("source", "")), "".join(trs), _m(ft), _m(ct),
                   (("▲" if ct > ft else "▼") + _m(abs(ct - ft))) if ct != ft else "-",
                   _history_html(month, rec, limit=200)))
    html = ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s 가마감 고정값</title></head><body style='font-family:Arial,sans-serif;margin:24px;color:#16202B'>"
            "<h1 style='font-size:24px'>%s 가마감 — 회의 고정값과 변경 기록</h1>%s"
            "<p style='margin-top:20px'><a href='/?year=%d&month=%d'>현황판으로</a></p></body></html>"
            % (month, month, body, y, m))
    return html
