import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import ppt_highlight_patch as ph
from flask import make_response, request

app = ph.app
base = ph.base
ui = ph.ppt.ui

SALESOPS_API = "https://medparkallo-medpark-salesops.mycafe24.ai/api/performance"
TOKEN_ENV = "PERFORMANCE_READ_ONLY_TOKEN"
_CACHE = {}
_CACHE_TTL = 20


def _norm(v):
    return re.sub(r"[^0-9a-z가-힣]+", "", str(v or "").strip().lower())


def _flatten(obj, prefix=""):
    out = {}
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        nk = _norm(k)
        full = prefix + nk if prefix else nk
        if isinstance(v, dict):
            out.update(_flatten(v, full))
        else:
            out[full] = v
            out[nk] = v
    return out


def _extract_rows(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    preferred = {"rows", "data", "items", "results", "performance", "performances"}
    for k, v in payload.items():
        if _norm(k) in preferred:
            if isinstance(v, list):
                rows = [x for x in v if isinstance(x, dict)]
                if rows:
                    return rows
            if isinstance(v, dict):
                rows = _extract_rows(v)
                if rows:
                    return rows
    best = []
    for v in payload.values():
        if isinstance(v, list):
            rows = [x for x in v if isinstance(x, dict)]
            if len(rows) > len(best):
                best = rows
        elif isinstance(v, dict):
            rows = _extract_rows(v)
            if len(rows) > len(best):
                best = rows
    return best


def _to_int(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    s = str(v).strip().replace(",", "").replace("₩", "")
    if not s or s.lower() in {"-", "null", "none"}:
        return None
    try:
        return int(round(float(s)))
    except Exception:
        return None


def _find_num(flat, aliases, predicate=None):
    aliases = {_norm(x) for x in aliases}
    for k, v in flat.items():
        if k in aliases:
            n = _to_int(v)
            if n is not None:
                return n
    if predicate:
        for k, v in flat.items():
            if predicate(k):
                n = _to_int(v)
                if n is not None:
                    return n
    return None


def _dims(flat):
    business = region = kind = None
    for v in flat.values():
        t = _norm(v)
        if business is None:
            if t in {"덴탈", "dental"}: business = "덴탈"
            elif t in {"메디컬", "medical", "medicaldevice"}: business = "메디컬"
            elif t in {"에스테틱", "aesthetic", "aesthetics"}: business = "에스테틱"
        if region is None:
            if t in {"국내", "domestic", "korea", "kr"}: region = "국내"
            elif t in {"해외", "overseas", "international", "global"}: region = "해외"
        if kind is None:
            if t in {"기존", "existing", "old"}: kind = "기존"
            elif t in {"신규", "new"}: kind = "신규"
    return business, region, kind


def _parse_row(row):
    flat = _flatten(row)
    business, region, kind = _dims(flat)
    if not (business and region and kind):
        return None
    first = _find_num(flat, ("first_fcst","fcst_1","fcst1","first_forecast","1차fcst","1차예상","1차"), lambda k: ("1차" in k or "fcst1" in k or "first" in k) and "전월" not in k)
    second = _find_num(flat, ("second_fcst","fcst_2","fcst2","second_forecast","2차fcst","2차예상","2차"), lambda k: ("2차" in k or "fcst2" in k or "second" in k) and "전월" not in k)
    close = _find_num(flat, ("final_close","finalclose","close","actual","final_actual","최종마감","마감","잠정마감"), lambda k: ("잠정마감" in k or "최종마감" in k or "finalclose" in k or k.endswith("close") or k.endswith("actual")) and "가마감" not in k)
    return {"business":business,"region":region,"kind":kind,"first":first,"second":second,"close":close}


def _fetch(year, month, force=False):
    key = (int(year), int(month))
    now = time.time()
    if not force and key in _CACHE:
        ts, data, meta = _CACHE[key]
        if now - ts < _CACHE_TTL:
            return data, meta
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        return {}, {"ok":False,"reason":"token_missing","rows":0}
    url = SALESOPS_API + "?" + urllib.parse.urlencode({"year":int(year),"month":int(month)})
    headers = {
        "Accept":"application/json",
        "User-Agent":"MedPark-Performance-Report/clean-1.1",
        "X-Requested-With":"XMLHttpRequest",
        "Authorization":"Bearer " + token,
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        # IMPORTANT: allow the platform's redirect chain. The read-only API returns
        # valid JSON only when the normal redirect handler is allowed to complete.
        with urllib.request.urlopen(req, timeout=8) as res:
            raw = res.read().decode("utf-8", "replace")
            status = getattr(res, "status", 200)
            ctype = str(res.headers.get("Content-Type") or "").lower()
        if status != 200:
            meta = {"ok":False,"reason":"http_"+str(status),"rows":0}
            _CACHE[key] = (now, {}, meta)
            return {}, meta
        if "json" not in ctype and not raw.lstrip().startswith(("{", "[")):
            meta = {"ok":False,"reason":"non_json_response","rows":0}
            _CACHE[key] = (now, {}, meta)
            return {}, meta
        payload = json.loads(raw)
        rows = _extract_rows(payload)
        index = {}
        for item in rows:
            parsed = _parse_row(item)
            if parsed:
                index[(parsed["business"],parsed["region"],parsed["kind"])] = parsed
        meta = {"ok":len(index) > 0,"reason":"ok" if index else "no_parsed_rows","rows":len(index)}
        _CACHE[key] = (now, index, meta)
        return index, meta
    except urllib.error.HTTPError as exc:
        meta = {"ok":False,"reason":"http_"+str(exc.code),"rows":0}
    except urllib.error.URLError as exc:
        meta = {"ok":False,"reason":"URLError:"+str(getattr(exc,"reason",exc))[:120],"rows":0}
    except json.JSONDecodeError:
        meta = {"ok":False,"reason":"invalid_json","rows":0}
    except Exception as exc:
        meta = {"ok":False,"reason":type(exc).__name__+":"+str(exc)[:120],"rows":0}
    _CACHE[key] = (now, {}, meta)
    return {}, meta


def _sum(rows, field):
    vals = [r.get(field) for r in rows if r.get(field) is not None]
    return sum(vals) if vals else None


def _report(year, month):
    report = ui.report_data(year, month)
    details = [r for r in report.get("rows", []) if not r.get("is_total")]
    cur, cur_meta = _fetch(year, month, True)
    prev_year, prev_month = ((year-1, 12) if month == 1 else (year, month-1))
    prev, prev_meta = _fetch(prev_year, prev_month, True)

    for row in details:
        if row.get("region") != "국내":
            continue
        key = (row.get("business"), "국내", row.get("kind"))
        c = cur.get(key) or {}
        p = prev.get(key) or {}
        if c.get("first") is not None:
            row["first"] = c["first"]
        if c.get("second") is not None:
            row["second"] = c["second"]
        if month == 8 and c.get("close") is not None:
            row["close"] = c["close"]
            row["close_has"] = True
        if p.get("close") is not None:
            row["prev_close"] = p["close"]

    sum_fields = ("prev_close","first","second","third_confirmed","third_forecast","close","next_first","carryover","qproj","october","november","december","q4proj","second_half")
    totals = [r for r in report.get("rows", []) if r.get("is_total")]
    for total in totals:
        source = details if total.get("is_grand") else [r for r in details if r.get("business") == total.get("business")]
        for field in sum_fields:
            total[field] = _sum(source, field)
        total["close_has"] = bool(source) and all(r.get("close_has") for r in source)

    domestic = [r for r in details if r.get("region") == "국내"]
    report["clean_salesops"] = {
        "current":cur_meta,
        "previous":prev_meta,
        "domestic_rows":len(domestic),
        "second_total":_sum(domestic,"second"),
        "prev_close_total":_sum(domestic,"prev_close"),
    }
    return report


def _status_banner(report):
    meta = report.get("clean_salesops", {})
    ok = meta.get("current", {}).get("ok") and meta.get("previous", {}).get("ok") and meta.get("domestic_rows") == 6
    if ok:
        prev_txt = ui.money_m(meta.get("prev_close_total"))
        second_txt = ui.money_m(meta.get("second_total"))
        return f"<div style='margin:8px 0 10px;padding:9px 12px;border:1px solid #91c8a7;background:#f1faf4;border-radius:7px;font-size:12px'><b>SalesOps 국내연동 OK</b> · 8월 잠정마감 {prev_txt}백만원 · 9월 2차 {second_txt}백만원</div>"
    reason = meta.get("current", {}).get("reason") or meta.get("previous", {}).get("reason") or "unknown"
    return f"<div style='margin:8px 0 10px;padding:9px 12px;border:1px solid #d89c9c;background:#fff4f4;border-radius:7px;font-size:12px'><b>국내 API 연동 실패</b> · {ui.esc(reason)}</div>"


@base.login_required
def clean_dashboard():
    try:
        year = int(request.args.get("year", 2026)); month = int(request.args.get("month", 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9
    report = _report(year, month)
    html = ui.render_report(report, base.current_user(), request.args.get("capture") == "1")
    if request.args.get("capture") != "1":
        banner = _status_banner(report)
        html = html.replace("<div class='table-wrap'>", banner + "<div class='table-wrap'>", 1)
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-MedPark-Runtime"] = "clean-salesops-1.1"
    return resp

app.view_functions["dashboard"] = clean_dashboard


_original_health = app.view_functions.get("health")
def clean_health():
    payload = _original_health() if _original_health else {"status":"ok"}
    if not isinstance(payload, dict):
        payload = {"status":"ok"}
    cur, cm = _fetch(2026, 9, True)
    prev, pm = _fetch(2026, 8, True)
    keys = [(b,"국내",k) for b in base.BUSINESSES for k in base.KINDS]
    payload = dict(payload)
    payload.update({
        "runtime":"clean-salesops-1.1",
        "salesops_current_ok":bool(cm.get("ok")),
        "salesops_previous_ok":bool(pm.get("ok")),
        "salesops_current_reason":cm.get("reason"),
        "salesops_previous_reason":pm.get("reason"),
        "salesops_domestic_rows":sum(1 for key in keys if key in cur),
        "salesops_prev_domestic_rows":sum(1 for key in keys if key in prev),
    })
    return payload
app.view_functions["health"] = clean_health
