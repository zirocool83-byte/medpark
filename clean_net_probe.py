import json
import os
import urllib.error
import urllib.parse
import urllib.request

import clean_salesops_runtime as active
from flask import jsonify

app = active.app
TOKEN_ENV = "PERFORMANCE_READ_ONLY_TOKEN"
BASE = "https://medparkallo-medpark-salesops.mycafe24.ai"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe(url, headers=None, no_redirect=False):
    req = urllib.request.Request(url, headers={"User-Agent":"MedPark-NetProbe/4.1", **(headers or {})}, method="GET")
    opener = urllib.request.build_opener(NoRedirect) if no_redirect else urllib.request.build_opener()
    try:
        with opener.open(req, timeout=5) as res:
            body = res.read(240).decode("utf-8", "replace")
            ctype = str(res.headers.get("Content-Type") or "").lower()
            return {"ok":True,"status":getattr(res,"status",200),"json":("json" in ctype or body.lstrip().startswith(("{","["))),"content_type":res.headers.get("Content-Type"),"location":res.headers.get("Location"),"final_url":res.geturl(),"body_prefix":body[:180]}
    except urllib.error.HTTPError as exc:
        try: body=exc.read(240).decode("utf-8","replace")
        except Exception: body=""
        ctype = str(exc.headers.get("Content-Type") or "").lower()
        return {"ok":False,"kind":"HTTPError","status":exc.code,"json":("json" in ctype or body.lstrip().startswith(("{","["))),"content_type":exc.headers.get("Content-Type"),"location":exc.headers.get("Location"),"final_url":getattr(exc,'url',None),"body_prefix":body[:180]}
    except urllib.error.URLError as exc:
        return {"ok":False,"kind":"URLError","detail":str(getattr(exc,"reason",exc))[:240]}
    except Exception as exc:
        return {"ok":False,"kind":type(exc).__name__,"detail":str(exc)[:240]}

@app.get('/clean-net-probe')
def clean_net_probe():
    token=os.environ.get(TOKEN_ENV,"").strip()
    q=urllib.parse.urlencode({"year":2026,"month":9})
    api=BASE+"/api/performance?"+q
    base_auth={"Accept":"application/json","X-Requested-With":"XMLHttpRequest","Authorization":"Bearer "+token} if token else {"Accept":"application/json","X-Requested-With":"XMLHttpRequest"}
    forwarded={**base_auth,"X-Forwarded-Proto":"https","X-Forwarded-Host":"medparkallo-medpark-salesops.mycafe24.ai"}
    results={
        "api_auth_noredirect":probe(api,base_auth,True),
        "api_auth_forwarded_noredirect":probe(api,forwarded,True),
        "api_auth_forwarded_redirect":probe(api,forwarded,False),
    }
    forwarded_ok = any(r.get("ok") and r.get("status")==200 and r.get("json") for name,r in results.items() if name.startswith("api_auth_forwarded"))
    return jsonify({"winner":"FORWARDED_OK" if forwarded_ok else "FORWARDED_FAIL","token_configured":bool(token),"results":results}),200
