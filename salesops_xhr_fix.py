import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import domestic_api_auth_json_scan as active
import salesops_api_patch as sap
from flask import jsonify

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

sap._fetch_remote = _fetch_remote_xhr
sap._CACHE.clear()

@app.get('/salesops-bridge-health')
def salesops_bridge_health():
    _, meta = _fetch_remote_xhr(2026, 9, True)
    return jsonify(meta), 200
