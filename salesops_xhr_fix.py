import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import domestic_api_auth_json_scan as active
import salesops_api_patch as sap
from flask import jsonify, request

app = active.app
BASE = "https://medparkallo-medpark-salesops.mycafe24.ai/api/performance"

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch_remote_xhr(year, month, force=False):
    cache_key = (int(year), int(month))
    now = time.time()
    if not force and cache_key in sap._CACHE:
        stamp, data, meta = sap._CACHE[cache_key]
        if now - stamp < sap._CACHE_TTL:
            return data, meta
    token = os.environ.get("PERFORMANCE_READ_ONLY_TOKEN", "").strip()
    if not token:
        return {}, {"ok":False,"reason":"token_missing","raw_rows":0,"parsed_rows":0}
    url = BASE + "?" + urllib.parse.urlencode({"year":int(year),"month":int(month)})
    headers = {
        "Accept":"application/json",
        "User-Agent":"MedPark-Performance-Report/1.0",
        "X-Requested-With":"XMLHttpRequest",
        "Authorization":"Bearer " + token,
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=8) as res:
            raw = res.read()
            status = getattr(res, "status", 200)
        if status != 200:
            return {}, {"ok":False,"reason":"http_"+str(status),"raw_rows":0,"parsed_rows":0}
        payload = json.loads(raw.decode("utf-8","replace"))
        raw_rows = sap._extract_rows(payload)
        index = {}
        for item in raw_rows:
            parsed = sap._parse_row(item)
            if parsed:
                index[(parsed["business"],parsed["region"],parsed["kind"])] = parsed
        meta = {"ok":bool(index),"reason":"ok" if index else "no_parsed_rows","raw_rows":len(raw_rows),"parsed_rows":len(index),"auth":"bearer"}
        sap._CACHE[cache_key] = (now, index, meta)
        return index, meta
    except urllib.error.HTTPError as exc:
        return {}, {"ok":False,"reason":"http_"+str(exc.code),"raw_rows":0,"parsed_rows":0}
    except json.JSONDecodeError:
        return {}, {"ok":False,"reason":"JSONDecodeError","raw_rows":0,"parsed_rows":0}
    except urllib.error.URLError as exc:
        return {}, {"ok":False,"reason":"URLError","detail":str(getattr(exc,"reason","") or "")[:100],"raw_rows":0,"parsed_rows":0}
    except Exception as exc:
        return {}, {"ok":False,"reason":type(exc).__name__,"raw_rows":0,"parsed_rows":0}

# Make every existing SalesOps hook use the working direct bridge.
sap._fetch_remote = _fetch_remote_xhr
sap._CACHE.clear()


def _latest_remote(remote):
    for key in ("close", "third_forecast", "second", "first"):
        value = remote.get(key)
        if value is not None:
            return value
    return None


def report_data_final(year, month):
    report = sap._original_report_data(year, month)
    index, meta = _fetch_remote_xhr(year, month)
    report["salesops_api"] = meta
    if not meta.get("ok"):
        return report
    store = sap.base.read_store()
    details = [r for r in report.get("rows", []) if not r.get("is_total")]
    for row in details:
        key = (row.get("business"), row.get("region"), row.get("kind"))
        remote = index.get(key)
        if not remote:
            continue
        local_best = sap.ui.best_month(store, year, month, *key)
        remote_best = _latest_remote(remote)
        for field in ("first", "second", "third_confirmed", "third_forecast", "close"):
            if remote.get(field) is not None:
                row[field] = remote[field]
        row["carryover"] = remote.get("carryover", row.get("carryover", 0))
        if remote.get("close") is not None:
            row["close_has"] = True
        if remote_best is not None and local_best is not None:
            delta = remote_best - local_best
            if row.get("qproj") is not None:
                row["qproj"] += delta
            if month >= 7 and row.get("second_half") is not None:
                row["second_half"] += delta
            if month in (10, 11, 12):
                month_field = {10:"october",11:"november",12:"december"}[month]
                row[month_field] = remote_best
                if row.get("q4proj") is not None:
                    row["q4proj"] += delta
    def sum_nullable(rows, field):
        vals = [r.get(field) for r in rows if r.get(field) is not None]
        return sum(vals) if vals else None
    sum_fields = ("first","second","third_confirmed","third_forecast","close","next_first","carryover","qproj","october","november","december","q4proj","second_half")
    for total_row in [r for r in report.get("rows", []) if r.get("is_total")]:
        source = details if total_row.get("is_grand") else [r for r in details if r.get("business") == total_row.get("business")]
        for field in sum_fields:
            total_row[field] = sum_nullable(source, field)
        total_row["close_has"] = bool(source) and all(r.get("close_has") for r in source)
    grand = next((r for r in report.get("rows", []) if r.get("is_grand")), None)
    if grand:
        report["third_total"] = grand.get("third_forecast")
        close_total = grand.get("close") if grand.get("close_has") else None
        report["diff"] = close_total - report["third_total"] if close_total is not None and report["third_total"] is not None else None
        report["error_rate"] = abs(report["diff"]) / report["third_total"] if report.get("diff") is not None and report.get("third_total") else None
    return report

sap.ui.report_data = report_data_final


def _remote_for_final(year, month, business, region, kind):
    index, meta = _fetch_remote_xhr(year, month)
    if not meta.get("ok"):
        return None
    return index.get((business, region, kind))


def scope_stage_final(data, year, month, stage, business, region, kind):
    remote = _remote_for_final(year, month, business, region, kind)
    if remote:
        if stage == "1차" and remote.get("first") is not None:
            return remote["first"], None, remote.get("carryover", 0)
        if stage == "2차" and remote.get("second") is not None:
            return remote["second"], None, remote.get("carryover", 0)
        if stage == "3차" and (remote.get("third_forecast") is not None or remote.get("third_confirmed") is not None):
            forecast = remote.get("third_forecast") if remote.get("third_forecast") is not None else remote.get("third_confirmed")
            return forecast, remote.get("third_confirmed"), remote.get("carryover", 0)
        if stage == "마감" and remote.get("close") is not None:
            return remote["close"], remote["close"], remote.get("carryover", 0)
    return sap._original_scope_stage(data, year, month, stage, business, region, kind)

sap.rt._scope_stage = scope_stage_final


def salesops_health_final():
    try:
        year = int(request.args.get("year", 2026)); month = int(request.args.get("month", 9))
    except Exception:
        year, month = 2026, 9
    _, meta = _fetch_remote_xhr(year, month, True)
    payload = {"status":"ok" if meta.get("ok") else "error","connected":bool(meta.get("ok")),"year":year,"month":month,"raw_rows":meta.get("raw_rows",0),"parsed_rows":meta.get("parsed_rows",0),"auth":meta.get("auth"),"reason":meta.get("reason"),"mode":"read-only-xhr"}
    return jsonify(payload), (200 if meta.get("ok") else 503)

app.view_functions["salesops_health"] = salesops_health_final

@app.get('/salesops-bridge-health')
def salesops_bridge_health():
    _, meta = _fetch_remote_xhr(2026, 9, True)
    return jsonify(meta), 200

@app.get('/salesops-domestic-check')
def salesops_domestic_check():
    try:
        year = int(request.args.get('year', 2026)); month = int(request.args.get('month', 9))
    except Exception:
        year, month = 2026, 9
    index, meta = _fetch_remote_xhr(year, month, True)
    vals = {}
    for business in sap.base.BUSINESSES:
        for kind in sap.base.KINDS:
            row = index.get((business, '국내', kind), {})
            vals[business+'|'+kind] = {k: row.get(k) for k in ('first','second','third_confirmed','third_forecast','close')}
    totals = {}
    for field in ('first','second','third_confirmed','third_forecast','close'):
        nums = [v.get(field) for v in vals.values() if v.get(field) is not None]
        totals[field] = sum(nums) if nums else None
    return jsonify({'meta':meta,'values':vals,'totals':totals}), 200
