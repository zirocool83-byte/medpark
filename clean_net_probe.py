import json
import urllib.error
import urllib.request

import clean_salesops_runtime as active
from flask import jsonify

app = active.app

CANDIDATES = {
    "public_https": "https://medparkallo-medpark-salesops.mycafe24.ai/health",
    "public_http": "http://medparkallo-medpark-salesops.mycafe24.ai/health",
    "internal_8000": "http://medparkallo-medpark-salesops:8000/health",
    "internal_http": "http://medparkallo-medpark-salesops/health",
    "project_local": "http://medparkallo-medpark-salesops.mycafe24.ai:8000/health",
}


def probe(url):
    req = urllib.request.Request(url, headers={"User-Agent":"MedPark-NetProbe/1.0"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=3) as res:
            body = res.read(180).decode("utf-8", "replace")
            return {"ok": True, "status": getattr(res, "status", 200), "body": body[:120]}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "kind":"HTTPError", "status": exc.code, "detail": str(exc)[:120]}
    except urllib.error.URLError as exc:
        return {"ok": False, "kind":"URLError", "detail": str(getattr(exc, "reason", exc))[:180]}
    except Exception as exc:
        return {"ok": False, "kind": type(exc).__name__, "detail": str(exc)[:180]}


@app.get('/clean-net-probe')
def clean_net_probe():
    results = {name: probe(url) for name, url in CANDIDATES.items()}
    winner = next((name for name, result in results.items() if result.get('ok')), None)
    return jsonify({"winner": winner, "results": results}), 200
