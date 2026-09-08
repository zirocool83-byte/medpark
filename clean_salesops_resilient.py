import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import clean_salesops_runtime as active

app = active.app
_original_health = app.view_functions.get("health")

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_OPENER = urllib.request.build_opener(_NoRedirect)

def _direct_once(year, month):
    token = os.environ.get(active.TOKEN_ENV, "").strip()
    if not token:
        return {}, {"ok":False,"reason":"token_missing","source":"live","rows":0}

    url = active.SALESOPS_API + "?" + urllib.parse.urlencode({"year":int(year),"month":int(month)})
    headers = {
        "Accept":"application/json",
        "User-Agent":"MedPark-Performance-Report/resilient-3.0",
        "X-Requested-With":"XMLHttpRequest",
        "Authorization":"Bearer " + token,
        "X-Forwarded-Proto":"https",
        "X-Forwarded-Host":active.SALESOPS_HOST,
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with _OPENER.open(req, timeout=8) as res:
            raw = res.read().decode("utf-8", "replace")
            status = getattr(res, "status", 200)
            ctype = str(res.headers.get("Content-Type") or "").lower()
        if status != 200:
            return {}, {"ok":False,"reason":"http_"+str(status),"source":"live","rows":0}
        if "json" not in ctype and not raw.lstrip().startswith(("{", "[")):
            return {}, {"ok":False,"reason":"non_json_response","source":"live","rows":0}
        payload = json.loads(raw)
        rows = active._extract_rows(payload)
        index = {}
        for item in rows:
            parsed = active._parse_row(item)
            if parsed:
                index[(parsed["business"], parsed["region"], parsed["kind"])] = parsed
        if not index:
            return {}, {"ok":False,"reason":"no_parsed_rows","source":"live","rows":0}
        try:
            active._save_snapshot(year, month, index)
        except Exception:
            pass
        return index, {"ok":True,"reason":"ok","source":"live","rows":len(index)}
    except urllib.error.HTTPError as exc:
        if exc.code in (301,302,303,307,308):
            loc = str(exc.headers.get("Location") or "")
            return {}, {"ok":False,"reason":"redirect_blocked:"+loc[:100],"source":"live","rows":0}
        return {}, {"ok":False,"reason":"http_"+str(exc.code),"source":"live","rows":0}
    except urllib.error.URLError as exc:
        return {}, {"ok":False,"reason":"URLError:"+str(getattr(exc,"reason",exc))[:120],"source":"live","rows":0}
    except json.JSONDecodeError:
        return {}, {"ok":False,"reason":"invalid_json","source":"live","rows":0}
    except Exception as exc:
        return {}, {"ok":False,"reason":type(exc).__name__+":"+str(exc)[:120],"source":"live","rows":0}


def _fetch_retry(year, month, force=False):
    key = (int(year), int(month))
    now = time.time()
    if not force and key in active._CACHE:
        ts, data, meta = active._CACHE[key]
        if now - ts < active._CACHE_TTL:
            return data, meta

    last_data, last_meta = {}, {"ok":False,"reason":"request_failed","source":"live","rows":0}
    for idx in range(3):
        data, meta = _direct_once(year, month)
        last_data, last_meta = data, meta
        if meta.get("ok"):
            active._CACHE[key] = (time.time(), data, meta)
            return data, meta
        if idx < 2:
            time.sleep(0.25 if idx == 0 else 0.75)

    cached, saved_at = active._load_snapshot(year, month)
    if cached:
        meta = {
            "ok":True,
            "reason":"snapshot_fallback_after_retries",
            "warning":last_meta.get("reason"),
            "source":"snapshot",
            "saved_at":saved_at,
            "rows":len(cached),
        }
        active._CACHE[key] = (time.time(), cached, meta)
        return cached, meta

    active._CACHE[key] = (time.time(), last_data, last_meta)
    return last_data, last_meta


active._fetch = _fetch_retry


def resilient_health():
    payload = _original_health() if _original_health else {"status":"ok"}
    if isinstance(payload, tuple):
        payload = payload[0]
    if not isinstance(payload, dict):
        payload = {"status":"ok"}
    payload = dict(payload)
    p8 = Path(active._snapshot_path(2026, 8))
    p9 = Path(active._snapshot_path(2026, 9))
    payload.update({
        "runtime":"clean-salesops-3.0-noredirect",
        "snapshot_2026_08_exists":p8.exists(),
        "snapshot_2026_09_exists":p9.exists(),
        "snapshot_2026_08_size":p8.stat().st_size if p8.exists() else 0,
        "snapshot_2026_09_size":p9.stat().st_size if p9.exists() else 0,
    })
    return payload

app.view_functions["health"] = resilient_health
