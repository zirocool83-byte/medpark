import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import ppt_highlight_patch as ph
from flask import request

app = ph.app
base = ph.base
ppt = ph.ppt
ui = ppt.ui
rt = ppt.rt

SALESOPS_BASE = "https://medparkallo-medpark-salesops.mycafe24.ai"
SALESOPS_API = SALESOPS_BASE + "/api/performance"
TOKEN_ENV = "PERFORMANCE_READ_ONLY_TOKEN"
_CACHE = {}
_CACHE_TTL = 30

def _norm_key(value):
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").strip().lower())

def _flatten_dict(obj, prefix=""):
    out = {}
    if not isinstance(obj, dict):
        return out
    for key, value in obj.items():
        nk = _norm_key(key)
        full = (prefix + nk) if prefix else nk
        if isinstance(value, dict):
            out.update(_flatten_dict(value, full))
        else:
            out[full] = value
            out[nk] = value
    return out

def _extract_rows(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    preferred = {"rows", "data", "items", "results", "performance", "performances"}
    for key, value in payload.items():
        if _norm_key(key) in preferred:
            if isinstance(value, list):
                rows = [x for x in value if isinstance(x, dict)]
                if rows:
                    return rows
            if isinstance(value, dict):
                rows = _extract_rows(value)
                if rows:
                    return rows
    best = []
    for value in payload.values():
        if isinstance(value, list):
            rows = [x for x in value if isinstance(x, dict)]
            if len(rows) > len(best):
                best = rows
        elif isinstance(value, dict):
            rows = _extract_rows(value)
            if len(rows) > len(best):
                best = rows
    return best

def _classify_dimensions(flat):
    business = region = kind = None
    for value in flat.values():
        text = _norm_key(value)
        if not business:
            if text in {"덴탈", "dental"}:
                business = "덴탈"
            elif text in {"메디컬", "medical", "medicaldevice"}:
                business = "메디컬"
            elif text in {"에스테틱", "aesthetic", "aesthetics"}:
                business = "에스테틱"
        if not region:
            if text in {"국내", "domestic", "korea", "kr"}:
                region = "국내"
            elif text in {"해외", "overseas", "international", "global"}:
                region = "해외"
        if not kind:
            if text in {"기존", "existing", "old"}:
                kind = "기존"
            elif text in {"신규", "new"}:
                kind = "신규"
    return business, region, kind

def _to_int(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(round(value))
    text = str(value).strip().replace(",", "").replace("₩", "")
    if not text or text.lower() in {"-", "null", "none"}:
        return None
    try:
        return int(round(float(text)))
    except Exception:
        return None

def _find_num(flat, aliases=(), predicate=None):
    norm_aliases = {_norm_key(x) for x in aliases}
    for key, value in flat.items():
        if key in norm_aliases:
            parsed = _to_int(value)
            if parsed is not None:
                return parsed
    if predicate:
        for key, value in flat.items():
            if predicate(key):
                parsed = _to_int(value)
                if parsed is not None:
                    return parsed
    return None

def _parse_row(row):
    flat = _flatten_dict(row)
    business, region, kind = _classify_dimensions(flat)
    if not (business and region and kind):
        return None
    first = _find_num(flat, ("first_fcst","fcst_1","fcst1","first_forecast","1차fcst","1차예상","1차"), lambda k: ("1차" in k or "fcst1" in k or "first" in k) and "전월" not in k)
    second = _find_num(flat, ("second_fcst","fcst_2","fcst2","second_forecast","2차fcst","2차예상","2차"), lambda k: ("2차" in k or "fcst2" in k or "second" in k) and "전월" not in k)
    third_confirmed = _find_num(flat, ("third_confirmed","fcst_3_confirmed","fcst3confirmed","3차확정"), lambda k: ("3차" in k or "fcst3" in k or "third" in k) and ("확정" in k or "confirm" in k))
    third_forecast = _find_num(flat, ("third_forecast","fcst_3_forecast","fcst3forecast","3차예상"), lambda k: ("3차" in k or "fcst3" in k or "third" in k) and ("예상" in k or "forecast" in k or "fcst" in k) and ("확정" not in k and "confirm" not in k))
    close = _find_num(flat, ("final_close","finalclose","close","actual","final_actual","최종마감","마감"), lambda k: ("최종마감" in k or "finalclose" in k or k.endswith("close") or k.endswith("actual")) and "가마감" not in k)
    carryover = _find_num(flat, ("carryover","rollover","carry_over","이월","이월금액"), lambda k: "이월" in k or "carryover" in k or "rollover" in k)
    return {"business":business,"region":region,"kind":kind,"first":first,"second":second,"third_confirmed":third_confirmed,"third_forecast":third_forecast,"close":close,"carryover":carryover or 0}

def _fetch_remote(year, month, force=False):
    cache_key = (int(year), int(month))
    now = time.time()
    if not force and cache_key in _CACHE:
        stamp, data, meta = _CACHE[cache_key]
        if now - stamp < _CACHE_TTL:
            return data, meta
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        meta = {"ok":False,"reason":"token_missing","raw_rows":0,"parsed_rows":0}
        _CACHE[cache_key] = (now, {}, meta)
        return {}, meta
    url = SALESOPS_API + "?" + urllib.parse.urlencode({"year":int(year),"month":int(month)})
    attempts = [{"Authorization":"Bearer " + token},{"X-Read-Only-Token":token}]
    last_error = None
    for auth_headers in attempts:
        headers = {"Accept":"application/json","User-Agent":"MedPark-Performance-Report/1.0"}
        headers.update(auth_headers)
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=8) as res:
                raw = res.read()
                status = getattr(res, "status", 200)
            if status != 200:
                last_error = "http_" + str(status)
                continue
            payload = json.loads(raw.decode("utf-8","replace"))
            raw_rows = _extract_rows(payload)
            index = {}
            for item in raw_rows:
                parsed = _parse_row(item)
                if parsed:
                    index[(parsed["business"],parsed["region"],parsed["kind"])] = parsed
            meta = {"ok":bool(index),"reason":"ok" if index else "no_parsed_rows","raw_rows":len(raw_rows),"parsed_rows":len(index),"auth":"bearer" if "Authorization" in auth_headers else "x-read-only-token"}
            _CACHE[cache_key] = (now, index, meta)
            return index, meta
        except urllib.error.HTTPError as exc:
            last_error = "http_" + str(exc.code)
            if exc.code not in (401,403):
                break
        except Exception as exc:
            last_error = type(exc).__name__
            break
    meta = {"ok":False,"reason":last_error or "request_failed","raw_rows":0,"parsed_rows":0}
    _CACHE[cache_key] = (now, {}, meta)
    return {}, meta

def _latest_remote(remote):
    for key in ("close","third_forecast","second","first"):
        value = remote.get(key)
        if value is not None:
            return value
    return None

_original_report_data = ui.report_data

def report_data_with_salesops(year, month):
    report = _original_report_data(year, month)
    index, meta = _fetch_remote(year, month)
    report["salesops_api"] = meta
    if not meta.get("ok"):
        return report
    store = base.read_store()
    details = [r for r in report.get("rows",[]) if not r.get("is_total")]
    for row in details:
        key = (row.get("business"),row.get("region"),row.get("kind"))
        remote = index.get(key)
        if not remote:
            continue
        local_best = ui.best_month(store, year, month, *key)
        remote_best = _latest_remote(remote)
        for field in ("first","second","third_confirmed","third_forecast","close"):
            if remote.get(field) is not None:
                row[field] = remote[field]
        row["carryover"] = remote.get("carryover", row.get("carryover",0))
        if remote.get("close") is not None:
            row["close_has"] = True
        if remote_best is not None and local_best is not None:
            delta = remote_best - local_best
            if row.get("qproj") is not None:
                row["qproj"] += delta
            if month >= 7 and row.get("second_half") is not None:
                row["second_half"] += delta
            if month in (10,11,12):
                month_field = {10:"october",11:"november",12:"december"}[month]
                row[month_field] = remote_best
                if row.get("q4proj") is not None:
                    row["q4proj"] += delta
    def sum_nullable(rows, field):
        vals = [r.get(field) for r in rows if r.get(field) is not None]
        return sum(vals) if vals else None
    sum_fields = ("first","second","third_confirmed","third_forecast","close","next_first","carryover","qproj","october","november","december","q4proj","second_half")
    for total_row in [r for r in report.get("rows",[]) if r.get("is_total")]:
        source = details if total_row.get("is_grand") else [r for r in details if r.get("business")==total_row.get("business")]
        for field in sum_fields:
            total_row[field] = sum_nullable(source, field)
        total_row["close_has"] = bool(source) and all(r.get("close_has") for r in source)
    grand = next((r for r in report.get("rows",[]) if r.get("is_grand")), None)
    if grand:
        report["third_total"] = grand.get("third_forecast")
        close_total = grand.get("close") if grand.get("close_has") else None
        report["diff"] = close_total - report["third_total"] if close_total is not None and report["third_total"] is not None else None
        report["error_rate"] = abs(report["diff"]) / report["third_total"] if report.get("diff") is not None and report.get("third_total") else None
    return report

ui.report_data = report_data_with_salesops

_original_scope_stage = rt._scope_stage
_original_previous_close = rt._previous_close
_original_prior_year_same_month = rt._prior_year_same_month

def _remote_for(year, month, business, region, kind):
    index, meta = _fetch_remote(year, month)
    if not meta.get("ok"):
        return None
    return index.get((business,region,kind))

def scope_stage_with_salesops(data, year, month, stage, business, region, kind):
    remote = _remote_for(year, month, business, region, kind)
    if remote:
        if stage == "1차" and remote.get("first") is not None:
            return remote["first"], None, remote.get("carryover",0)
        if stage == "2차" and remote.get("second") is not None:
            return remote["second"], None, remote.get("carryover",0)
        if stage == "3차" and (remote.get("third_forecast") is not None or remote.get("third_confirmed") is not None):
            forecast = remote.get("third_forecast")
            if forecast is None:
                forecast = remote.get("third_confirmed")
            return forecast, remote.get("third_confirmed"), remote.get("carryover",0)
        if stage == "마감" and remote.get("close") is not None:
            return remote["close"], remote["close"], remote.get("carryover",0)
    return _original_scope_stage(data, year, month, stage, business, region, kind)

def previous_close_with_salesops(data, year, month, business, region, kind):
    py, pm = ((year-1,12) if month==1 else (year,month-1))
    remote = _remote_for(py, pm, business, region, kind)
    if remote and remote.get("close") is not None:
        return remote["close"]
    return _original_previous_close(data, year, month, business, region, kind)

def prior_year_same_month_with_salesops(data, year, month, business, region, kind):
    remote = _remote_for(year-1, month, business, region, kind)
    if remote and remote.get("close") is not None:
        return remote["close"]
    return _original_prior_year_same_month(data, year, month, business, region, kind)

rt._scope_stage = scope_stage_with_salesops
rt._previous_close = previous_close_with_salesops
rt._prior_year_same_month = prior_year_same_month_with_salesops

@app.get("/salesops-health")
def salesops_health():
    try:
        year = int(request.args.get("year",2026))
        month = int(request.args.get("month",9))
    except Exception:
        year, month = 2026, 9
    _, meta = _fetch_remote(year, month, force=True)
    payload = {"status":"ok" if meta.get("ok") else "error","connected":bool(meta.get("ok")),"year":year,"month":month,"raw_rows":meta.get("raw_rows",0),"parsed_rows":meta.get("parsed_rows",0),"auth":meta.get("auth"),"reason":meta.get("reason"),"token_configured":bool(os.environ.get(TOKEN_ENV,"").strip()),"mode":"read-only"}
    return payload, (200 if meta.get("ok") else 503)

@app.get("/salesops-diagnostic-code")
def salesops_diagnostic_code():
    try:
        year = int(request.args.get("year",2026)); month = int(request.args.get("month",9))
    except Exception:
        year, month = 2026, 9
    _, meta = _fetch_remote(year, month, force=True)
    reason = str(meta.get("reason") or "request_failed")
    codes = {"ok":201,"token_missing":202,"no_parsed_rows":203,"http_401":204,"http_403":205,"http_404":206,"http_500":207,"http_502":208,"http_503":209,"TimeoutError":210,"URLError":211,"JSONDecodeError":212,"request_failed":213}
    code = codes.get(reason, 218)
    return {"status":"ok" if meta.get("ok") else "error","reason":reason,"raw_rows":meta.get("raw_rows",0),"parsed_rows":meta.get("parsed_rows",0)}, code

_original_health = app.view_functions.get("health")
def salesops_health_wrapper():
    payload = _original_health() if _original_health else {"status":"ok"}
    if isinstance(payload, dict):
        payload = dict(payload)
        payload["runtime"] = "excel-layout-v7-salesops-api"
        payload["salesops_mode"] = "api-read-only"
        payload["salesops_api"] = "/api/performance"
        payload["salesops_health"] = "/salesops-health"
        payload["token_configured"] = bool(os.environ.get(TOKEN_ENV,"").strip())
    return payload
app.view_functions["health"] = salesops_health_wrapper
