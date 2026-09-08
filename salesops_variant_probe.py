import os
import urllib.error
import urllib.parse
import urllib.request

import root_direct_endpoint as current
from flask import jsonify

app = current.app
HOST = "medparkallo-medpark-salesops.mycafe24.ai"
BASE = "https://" + HOST

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe(path):
    token = os.environ.get("PERFORMANCE_READ_ONLY_TOKEN", "").strip()
    q = urllib.parse.urlencode({"year":2026,"month":9})
    url = BASE + path + "?" + q
    headers = {
        "Accept":"application/json",
        "X-Requested-With":"XMLHttpRequest",
        "Authorization":"Bearer " + token,
        "X-Forwarded-Proto":"https",
        "X-Forwarded-Host":HOST,
        "X-Forwarded-Port":"443",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=6) as res:
            body = res.read(120).decode("utf-8","replace")
            return {"status":getattr(res,"status",200),"location":res.headers.get("Location"),"json":("json" in str(res.headers.get("Content-Type") or "").lower() or body.lstrip().startswith(("{","[")))}
    except urllib.error.HTTPError as exc:
        return {"status":exc.code,"location":exc.headers.get("Location"),"json":False}
    except urllib.error.URLError as exc:
        return {"status":0,"error":"URLError:"+str(getattr(exc,"reason",exc))[:100],"json":False}
    except Exception as exc:
        return {"status":0,"error":type(exc).__name__,"json":False}

@app.get('/salesops-variant-probe')
def salesops_variant_probe():
    return jsonify({
        "no_slash":probe("/api/performance"),
        "slash":probe("/api/performance/"),
        "direct":probe("/api/performance-direct"),
    }), 200
