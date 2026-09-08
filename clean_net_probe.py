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
    req = urllib.request.Request(url, headers={"User-Agent":"MedPark-NetProbe/2.0", **(headers or {})}, method="GET")
    opener = urllib.request.build_opener(NoRedirect) if no_redirect else urllib.request.build_opener()
    try:
        with opener.open(req, timeout=5) as res:
            body = res.read(240).decode("utf-8", "replace")
            return {
                "ok": True,
                "status": getattr(res, "status", 200),
                "content_type": res.headers.get("Content-Type"),
                "location": res.headers.get("Location"),
                "body_prefix": body[:180],
            }
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(240).decode("utf-8", "replace")
        except Exception:
            body = ""
        return {
            "ok": False,
            "kind": "HTTPError",
            "status": exc.code,
            "content_type": exc.headers.get("Content-Type"),
            "location": exc.headers.get("Location"),
            "body_prefix": body[:180],
        }
    except urllib.error.URLError as exc:
        return {"ok": False, "kind":"URLError", "detail": str(getattr(exc, "reason", exc))[:240]}
    except Exception as exc:
        return {"ok": False, "kind": type(exc).__name__, "detail": str(exc)[:240]}


@app.get('/clean-net-probe')
def clean_net_probe():
    token = os.environ.get(TOKEN_ENV, "").strip()
    q = urllib.parse.urlencode({"year":2026,"month":9})
    api = BASE + "/api/performance?" + q
    auth_headers = {
        "Accept":"application/json",
        "X-Requested-With":"XMLHttpRequest",
        "Authorization":"Bearer " + token,
    } if token else {"Accept":"application/json", "X-Requested-With":"XMLHttpRequest"}
    results = {
        "health": probe(BASE + "/health"),
        "api_noauth_redirect": probe(api, {"Accept":"application/json"}, no_redirect=False),
        "api_noauth_noredirect": probe(api, {"Accept":"application/json"}, no_redirect=True),
        "api_auth_redirect": probe(api, auth_headers, no_redirect=False),
        "api_auth_noredirect": probe(api, auth_headers, no_redirect=True),
    }
    winner = next((name for name, result in results.items() if name.startswith('api_auth') and result.get('ok') and result.get('status') == 200 and 'json' in str(result.get('content_type') or '').lower()), None)
    return jsonify({"winner": winner, "token_configured": bool(token), "results": results}), 200
