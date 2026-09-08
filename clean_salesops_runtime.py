import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import ppt_highlight_patch as ph
from flask import make_response, request

app = ph.app
base = ph.base
ui = ph.ppt.ui

SALESOPS_HOST = "medparkallo-medpark-salesops.mycafe24.ai"
SALESOPS_API = "https://" + SALESOPS_HOST + "/api/performance"
TOKEN_ENV = "PERFORMANCE_READ_ONLY_TOKEN"
_CACHE = {}
_CACHE_TTL = 20
SNAPSHOT_DIR = Path(base.DATA_DIR)


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


def _snapshot_path(year, month):
    return SNAPSHOT_DIR / f"salesops_readonly_snapshot_{int(year)}_{int(month):02d}.json"


def _save_snapshot(year, month, index):
    payload = {
        "year": int(year),
        "month": int(month),
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": {"|".join(key): value for key, value in index.items()},
    }
    path = _snapshot_path(year, month)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_snapshot(year, month):
    path = _snapshot_path(year, month)
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        rows = payload.get("rows", {}) if isinstance(payload, dict) else {}
        index = {}
        for key, value in rows.items():
            parts = str(key).split("|", 2)
            if len(parts) == 3 and isinstance(value, dict):
                index[(parts[0], parts[1], parts[2])] = value
        if index:
            return index, payload.get("saved_at")
    except Exception:
        pass
    return {}, None


def _fallback(year, month, reason, now):
    cached, saved_at = _load_snapshot(year, month)
    if cached:
        meta = {
            "ok": True,
            "reason": "snapshot_fallback",
            "warning": reason,
            "source": "snapshot",
            "saved_at": saved_at,
            "rows": len(cached),
        }
        _CACHE[(int(year), int(month))] = (now, cached, meta)
        return cached, meta
    meta = {"ok":False,"reason":reason,"source":"live","rows":0}
    _CACHE[(int(year), int(month))] = (now, {}, meta)
    return {}, meta


def _fetch(year, month, force=False):
    key = (int(year), int(month))
    now = time.time()
    if not force and key in _CACHE:
        ts, data, meta = _CACHE[key]
        if now - ts < _CACHE_TTL:
            return data, meta

    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        return _fallback(year, month, "token_missing", now)

    url = SALESOPS_API + "?" + urllib.parse.urlencode({"year":int(year),"month":int(month)})
    headers = {
        "Accept":"application/json",
        "User-Agent":"MedPark-Performance-Report/clean-2.0",
        "X-Requested-With":"XMLHttpRequest",
        "Authorization":"Bearer " + token,
        "X-Forwarded-Proto":"https",
        "X-Forwarded-Host":SALESOPS_HOST,
    }
    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            raw = res.read().decode("utf-8", "replace")
            status = getattr(res, "status", 200)
            ctype = str(res.headers.get("Content-Type") or "").lower()
        if status != 200:
            return _fallback(year, month, "http_" + str(status), now)
        if "json" not in ctype and not raw.lstrip().startswith(("{", "[")):
            return _fallback(year, month, "non_json_response", now)

        payload = json.loads(raw)
        rows = _extract_rows(payload)
        index = {}
        for item in rows:
            parsed = _parse_row(item)
            if parsed:
                index[(parsed["business"],parsed["region"],parsed["kind"])] = parsed
        if not index:
            return _fallback(year, month, "no_parsed_rows", now)

        meta = {"ok":True,"reason":"ok","source":"live","rows":len(index)}
        _CACHE[key] = (now, index, meta)
        try:
            _save_snapshot(year, month, index)
        except Exception:
            pass
        return index, meta
    except urllib.error.HTTPError as exc:
        return _fallback(year, month, "http_" + str(exc.code), now)
    except urllib.error.URLError as exc:
        return _fallback(year, month, "URLError:" + str(getattr(exc,"reason",exc))[:120], now)
    except json.JSONDecodeError:
        return _fallback(year, month, "invalid_json", now)
    except Exception as exc:
        return _fallback(year, month, type(exc).__name__ + ":" + str(exc)[:120], now)


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
        if c.get("first") is not None: row["first"] = c["first"]
        if c.get("second") is not None: row["second"] = c["second"]
        if month == 8 and c.get("close") is not None:
            row["close"] = c["close"]
            row["close_has"] = True
        if p.get("close") is not None: row["prev_close"] = p["close"]

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
    current = meta.get("current", {})
    previous = meta.get("previous", {})
    ok = current.get("ok") and previous.get("ok") and meta.get("domestic_rows") == 6
    if ok:
        prev_txt = ui.money_m(meta.get("prev_close_total"))
        second_txt = ui.money_m(meta.get("second_total"))
        cached = current.get("source") == "snapshot" or previous.get("source") == "snapshot"
        suffix = " · 최근 정상 API값 사용" if cached else ""
        return f"<div style='margin:8px 0 10px;padding:9px 12px;border:1px solid #91c8a7;background:#f1faf4;border-radius:7px;font-size:12px'><b>SalesOps 국내연동 OK</b> · 8월 잠정마감 {prev_txt}백만원 · 9월 2차 {second_txt}백만원{suffix}</div>"
    reason = current.get("reason") or previous.get("reason") or "unknown"
    return f"<div style='margin:8px 0 10px;padding:9px 12px;border:1px solid #d89c9c;background:#fff4f4;border-radius:7px;font-size:12px'><b>국내 API 연동 실패</b> · {ui.esc(reason)}</div>"


@base.login_required
def clean_dashboard():
    try:
        year = int(request.args.get("year", 2026)); month = int(request.args.get("month", 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12: month = 9
    report = _report(year, month)
    html = ui.render_report(report, base.current_user(), request.args.get("capture") == "1")
    if request.args.get("capture") != "1":
        html = html.replace("<div class='table-wrap'>", _status_banner(report) + "<div class='table-wrap'>", 1)
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-MedPark-Runtime"] = "clean-salesops-2.0"
    return resp
app.view_functions["dashboard"] = clean_dashboard

_original_health = app.view_functions.get("health")
def clean_health():
    payload = _original_health() if _original_health else {"status":"ok"}
    if not isinstance(payload, dict): payload = {"status":"ok"}
    cur, cm = _fetch(2026, 9, True)
    prev, pm = _fetch(2026, 8, True)
    keys = [(b,"국내",k) for b in base.BUSINESSES for k in base.KINDS]
    cur_domestic = [cur.get(key) or {} for key in keys]
    prev_domestic = [prev.get(key) or {} for key in keys]
    payload = dict(payload)
    payload.update({
        "runtime":"clean-salesops-2.0",
        "salesops_current_ok":bool(cm.get("ok")),
        "salesops_previous_ok":bool(pm.get("ok")),
        "salesops_current_source":cm.get("source"),
        "salesops_previous_source":pm.get("source"),
        "salesops_current_reason":cm.get("reason"),
        "salesops_previous_reason":pm.get("reason"),
        "salesops_domestic_rows":sum(1 for key in keys if key in cur),
        "salesops_prev_domestic_rows":sum(1 for key in keys if key in prev),
        "salesops_second_non_null":sum(1 for r in cur_domestic if r.get("second") is not None),
        "salesops_second_total":sum(r.get("second") for r in cur_domestic if r.get("second") is not None),
        "salesops_prev_close_non_null":sum(1 for r in prev_domestic if r.get("close") is not None),
        "salesops_prev_close_total":sum(r.get("close") for r in prev_domestic if r.get("close") is not None),
    })
    return payload
app.view_functions["health"] = clean_health
