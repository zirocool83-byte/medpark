import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import domestic_api_auth_json_scan as active
import salesops_api_patch as sap

app = active.app

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
    token = os.environ.get(sap.TOKEN_ENV, "").strip()
    if not token:
        meta = {"ok":False,"reason":"token_missing","raw_rows":0,"parsed_rows":0}
        sap._CACHE[cache_key] = (now, {}, meta)
        return {}, meta
    url = sap.SALESOPS_API + "?" + urllib.parse.urlencode({"year":int(year),"month":int(month)})
    attempts = [{"Authorization":"Bearer " + token},{"X-Read-Only-Token":token}]
    last_error = None
    opener = urllib.request.build_opener(_NoRedirect)
    for auth_headers in attempts:
        headers = {
            "Accept":"application/json",
            "User-Agent":"MedPark-Performance-Report/1.0",
            "X-Requested-With":"XMLHttpRequest",
        }
        headers.update(auth_headers)
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with opener.open(req, timeout=8) as res:
                raw = res.read()
                status = getattr(res, "status", 200)
            if status != 200:
                last_error = "http_" + str(status)
                continue
            payload = json.loads(raw.decode("utf-8","replace"))
            raw_rows = sap._extract_rows(payload)
            index = {}
            for item in raw_rows:
                parsed = sap._parse_row(item)
                if parsed:
                    index[(parsed["business"],parsed["region"],parsed["kind"])] = parsed
            meta = {
                "ok":bool(index),
                "reason":"ok" if index else "no_parsed_rows",
                "raw_rows":len(raw_rows),
                "parsed_rows":len(index),
                "auth":"bearer" if "Authorization" in auth_headers else "x-read-only-token",
            }
            sap._CACHE[cache_key] = (now, index, meta)
            return index, meta
        except urllib.error.HTTPError as exc:
            last_error = "http_" + str(exc.code)
            if exc.code not in (401,403):
                break
        except json.JSONDecodeError:
            last_error = "JSONDecodeError"
            break
        except urllib.error.URLError:
            last_error = "URLError"
            break
        except Exception as exc:
            last_error = type(exc).__name__
            break
    meta = {"ok":False,"reason":last_error or "request_failed","raw_rows":0,"parsed_rows":0}
    sap._CACHE[cache_key] = (now, {}, meta)
    return {}, meta

sap._fetch_remote = _fetch_remote_xhr
sap._CACHE.clear()
