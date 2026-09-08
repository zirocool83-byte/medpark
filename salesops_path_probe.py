import os
import urllib.error
import urllib.parse
import urllib.request

import clean_salesops_resilient as active
from flask import jsonify

app = active.app
HOST = "medparkallo-medpark-salesops.mycafe24.ai"
TOKEN_ENV = "PERFORMANCE_READ_ONLY_TOKEN"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

opener = urllib.request.build_opener(NoRedirect)

def probe(path):
    token = os.environ.get(TOKEN_ENV, "").strip()
    url = "https://" + HOST + path + "?" + urllib.parse.urlencode({"year":2026,"month":9})
    headers = {
        "Accept":"application/json",
        "User-Agent":"MedPark-PathProbe/1.0",
        "X-Requested-With":"XMLHttpRequest",
        "Authorization":"Bearer " + token,
        "X-Forwarded-Proto":"https",
        "X-Forwarded-Host":HOST,
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(req, timeout=5) as res:
            raw = res.read(300).decode("utf-8", "replace")
            return {"status":getattr(res,"status",200),"json":raw.lstrip().startswith(("{","[")),"location":res.headers.get("Location")}
    except urllib.error.HTTPError as exc:
        return {"status":exc.code,"json":False,"location":exc.headers.get("Location")}
    except urllib.error.URLError as exc:
        return {"status":0,"json":False,"error":"URLError:"+str(getattr(exc,"reason",exc))[:160]}
    except Exception as exc:
        return {"status":0,"json":False,"error":type(exc).__name__+":"+str(exc)[:160]}

@app.get('/__salesops-path-probe')
def salesops_path_probe():
    a = probe('/api/performance')
    b = probe('/api/performance/')
    return jsonify({"no_slash":a,"with_slash":b}), 200
