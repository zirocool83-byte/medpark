import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import ppt_highlight_patch as ph
from flask import jsonify, make_response, request

app = ph.app
base = ph.base
ui = ph.ppt.ui

SALESOPS_HOST = "medparkallo-medpark-salesops.mycafe24.ai"
SALESOPS_BASE = "https://" + SALESOPS_HOST
SALESOPS_API = SALESOPS_BASE + "/api/performance"
TOKEN_ENV = "PERFORMANCE_READ_ONLY_TOKEN"
SNAPSHOT_DIR = Path(base.DATA_DIR)


def _norm(v):
    return re.sub(r"[^0-9a-z가-힣]+", "", str(v or "").strip().lower())


def _flatten(obj):
    out = {}
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        nk = _norm(k)
        if isinstance(v, dict):
            out.update(_flatten(v))
        else:
            out[nk] = v
    return out


def _extract_rows(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("rows", "data", "items", "results", "performance", "performances"):
        for k, v in payload.items():
            if _norm(k) == key:
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


def _find_num(flat, aliases, contains=None):
    names = {_norm(x) for x in aliases}
    for k, v in flat.items():
        if k in names:
            n = _to_int(v)
            if n is not None:
                return n
    if contains:
        for k, v in flat.items():
            if contains(k):
                n = _to_int(v)
                if n is not None:
                    return n
    return None


def _parse_row(row):
    flat = _flatten(row)
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
    if not (business and region and kind):
        return None
    first = _find_num(flat, ("first_fcst","fcst_1","fcst1","first_forecast","1차fcst","1차예상","1차"), lambda k: ("1차" in k or "fcst1" in k or "first" in k) and "전월" not in k)
    second = _find_num(flat, ("second_fcst","fcst_2","fcst2","second_forecast","2차fcst","2차예상","2차"), lambda k: ("2차" in k or "fcst2" in k or "second" in k) and "전월" not in k)
    close = _find_num(flat, ("final_close","finalclose","close","actual","final_actual","최종마감","마감","잠정마감"), lambda k: ("잠정마감" in k or "최종마감" in k or "finalclose" in k or k.endswith("close") or k.endswith("actual")) and "가마감" not in k)
    return {"business":business,"region":region,"kind":kind,"first":first,"second":second,"close":close}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _rewrite_location(current, location):
    target = urllib.parse.urljoin(current, location or "")
    parsed = urllib.parse.urlsplit(target)
    if parsed.hostname in {"127.0.0.1", "localhost"}:
        target = urllib.parse.urlunsplit(("https", SALESOPS_HOST, parsed.path or "/api/performance", parsed.query, parsed.fragment))
    return target


def _snapshot_path(year, month):
    return SNAPSHOT_DIR / f"salesops_root_live_{int(year)}_{int(month):02d}.json"


def _save_snapshot(year, month, index):
    payload = {"year":int(year),"month":int(month),"saved_at":time.strftime("%Y-%m-%d %H:%M:%S"),"rows":{"|".join(k):v for k,v in index.items()}}
    path = _snapshot_path(year, month)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_snapshot(year, month):
    try:
        with open(_snapshot_path(year, month), "r", encoding="utf-8") as f:
            payload = json.load(f)
        index = {}
        for k, v in (payload.get("rows") or {}).items():
            p = str(k).split("|", 2)
            if len(p) == 3 and isinstance(v, dict):
                index[(p[0], p[1], p[2])] = v
        return index, payload.get("saved_at")
    except Exception:
        return {}, None


def _request_once(year, month):
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        return {}, {"ok":False,"reason":"token_missing","source":"live"}
    headers = {
        "Accept":"application/json",
        "User-Agent":"MedPark-Performance-Report/root-live-1.0",
        "X-Requested-With":"XMLHttpRequest",
        "Authorization":"Bearer " + token,
        "X-Forwarded-Proto":"https",
        "X-Forwarded-Host":SALESOPS_HOST,
        "X-Forwarded-Port":"443",
    }
    url = SALESOPS_API + "?" + urllib.parse.urlencode({"year":int(year),"month":int(month)})
    opener = urllib.request.build_opener(_NoRedirect)
    for hop in range(4):
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with opener.open(req, timeout=6) as res:
                raw = res.read().decode("utf-8", "replace")
                status = getattr(res, "status", 200)
                ctype = str(res.headers.get("Content-Type") or "").lower()
            if status != 200:
                return {}, {"ok":False,"reason":"http_"+str(status),"source":"live"}
            if "json" not in ctype and not raw.lstrip().startswith(("{","[")):
                return {}, {"ok":False,"reason":"non_json","source":"live"}
            payload = json.loads(raw)
            index = {}
            for item in _extract_rows(payload):
                parsed = _parse_row(item)
                if parsed:
                    index[(parsed["business"],parsed["region"],parsed["kind"])] = parsed
            if not index:
                return {}, {"ok":False,"reason":"no_parsed_rows","source":"live"}
            try: _save_snapshot(year, month, index)
            except Exception: pass
            return index, {"ok":True,"reason":"ok","source":"live","rows":len(index)}
        except urllib.error.HTTPError as exc:
            if exc.code in (301,302,303,307,308):
                loc = exc.headers.get("Location")
                if not loc:
                    return {}, {"ok":False,"reason":"redirect_without_location","source":"live"}
                url = _rewrite_location(url, loc)
                continue
            return {}, {"ok":False,"reason":"http_"+str(exc.code),"source":"live"}
        except urllib.error.URLError as exc:
            return {}, {"ok":False,"reason":"URLError:"+str(getattr(exc,"reason",exc))[:100],"source":"live"}
        except Exception as exc:
            return {}, {"ok":False,"reason":type(exc).__name__+":"+str(exc)[:100],"source":"live"}
    return {}, {"ok":False,"reason":"redirect_loop","source":"live"}


def _fetch(year, month):
    last = None
    for i in range(3):
        data, meta = _request_once(year, month)
        last = meta
        if meta.get("ok"):
            return data, meta
        if i < 2:
            time.sleep(0.25 * (i + 1))
    cached, saved = _load_snapshot(year, month)
    if cached:
        return cached, {"ok":True,"reason":"snapshot_fallback","source":"snapshot","saved_at":saved,"warning":(last or {}).get("reason"),"rows":len(cached)}
    return {}, (last or {"ok":False,"reason":"request_failed","source":"live"})


def _sum(rows, field):
    vals = [r.get(field) for r in rows if r.get(field) is not None]
    return sum(vals) if vals else None


def _build_report(year, month):
    report = ui.report_data(year, month)
    details = [r for r in report.get("rows", []) if not r.get("is_total")]
    cur, cm = _fetch(year, month)
    py, pm = ((year-1, 12) if month == 1 else (year, month-1))
    prev, pmmeta = _fetch(py, pm)
    for row in details:
        if row.get("region") != "국내":
            continue
        key = (row.get("business"), "국내", row.get("kind"))
        c = cur.get(key) or {}; p = prev.get(key) or {}
        if c.get("first") is not None: row["first"] = c["first"]
        if c.get("second") is not None: row["second"] = c["second"]
        if month == 8 and c.get("close") is not None:
            row["close"] = c["close"]; row["close_has"] = True
        if p.get("close") is not None: row["prev_close"] = p["close"]
    fields=("prev_close","first","second","third_confirmed","third_forecast","close","next_first","carryover","qproj","october","november","december","q4proj","second_half")
    for total in [r for r in report.get("rows", []) if r.get("is_total")]:
        source = details if total.get("is_grand") else [r for r in details if r.get("business")==total.get("business")]
        for f in fields: total[f]=_sum(source,f)
        total["close_has"] = bool(source) and all(r.get("close_has") for r in source)
    domestic=[r for r in details if r.get("region")=="국내"]
    report["live_meta"]={"current":cm,"previous":pmmeta,"second_total":_sum(domestic,"second"),"prev_close_total":_sum(domestic,"prev_close"),"domestic_rows":len(domestic)}
    return report


def _banner(report):
    m=report.get("live_meta",{}); c=m.get("current",{}); p=m.get("previous",{})
    ready=c.get("ok") and p.get("ok") and m.get("domestic_rows")==6
    if ready:
        note=" · 최근 정상값 사용" if c.get("source")=="snapshot" or p.get("source")=="snapshot" else ""
        return f"<div style='margin:8px 0 10px;padding:9px 12px;border:1px solid #91c8a7;background:#f1faf4;border-radius:7px;font-size:12px'><b>SalesOps 국내연동 OK</b> · 8월 잠정마감 {ui.money_m(m.get('prev_close_total'))}백만원 · 9월 2차 {ui.money_m(m.get('second_total'))}백만원{note}</div>"
    reason=c.get("reason") or p.get("reason") or "unknown"
    return f"<div style='margin:8px 0 10px;padding:9px 12px;border:1px solid #d89c9c;background:#fff4f4;border-radius:7px;font-size:12px'><b>국내 API 연동 실패</b> · {ui.esc(reason)}</div>"


@app.before_request
def root_live_before_request():
    if request.path != "/": return None
    user=base.current_user()
    if not user: return None
    try:
        year=int(request.args.get("year",2026)); month=int(request.args.get("month",9))
    except Exception:
        year,month=2026,9
    if month<1 or month>12: month=9
    report=_build_report(year,month)
    html=ui.render_report(report,user,request.args.get("capture")=="1")
    if request.args.get("capture")!="1": html=html.replace("<div class='table-wrap'>",_banner(report)+"<div class='table-wrap'>",1)
    resp=make_response(html)
    resp.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0, private"
    resp.headers["X-MedPark-Root-Runtime"]="root-live-1.0"
    return resp


@app.get('/root-live-check')
def root_live_check():
    cur,cm=_fetch(2026,9); prev,pm=_fetch(2026,8); keys=[(b,"국내",k) for b in base.BUSINESSES for k in base.KINDS]
    cr=[cur.get(k) or {} for k in keys]; pr=[prev.get(k) or {} for k in keys]
    second_total=sum(r.get("second") for r in cr if r.get("second") is not None)
    ok=cm.get("ok") and pm.get("ok") and sum(1 for k in keys if k in cur)==6 and sum(1 for k in keys if k in prev)==6 and sum(1 for r in cr if r.get("second") is not None)==6 and second_total==797318256 and sum(1 for r in pr if r.get("close") is not None)==6
    return jsonify({"status":"ok" if ok else "not_ready","current":cm,"previous":pm,"current_rows":sum(1 for k in keys if k in cur),"previous_rows":sum(1 for k in keys if k in prev),"second_total":second_total,"prev_close_non_null":sum(1 for r in pr if r.get("close") is not None)}),(200 if ok else 409)
