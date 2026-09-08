import json, os, urllib.parse, urllib.request, urllib.error
import domestic_api_diag as active
from flask import Response

app = active.app
BASE = 'https://medparkallo-medpark-salesops.mycafe24.ai/api/performance'
TOKEN_ENV = 'PERFORMANCE_READ_ONLY_TOKEN'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def probe(headers):
    t=os.environ.get(TOKEN_ENV,'').strip()
    url=BASE+'?'+urllib.parse.urlencode({'year':2026,'month':9})
    req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'MedPark-Performance-Report/1.0',**headers},method='GET')
    opener=urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req,timeout=8) as res:
            raw=res.read(300).decode('utf-8','replace')
            return {'status':getattr(res,'status',200),'location':res.headers.get('Location'),'content_type':res.headers.get('Content-Type'),'prefix':raw[:180]}
    except urllib.error.HTTPError as e:
        try: raw=e.read(300).decode('utf-8','replace')
        except Exception: raw=''
        return {'status':e.code,'location':e.headers.get('Location'),'content_type':e.headers.get('Content-Type'),'prefix':raw[:180]}
    except Exception as e:
        return {'status':0,'error':type(e).__name__}

@app.get('/domestic-diag/redirects')
def diag_redirects():
    t=os.environ.get(TOKEN_ENV,'').strip()
    data={
      'bearer':probe({'Authorization':'Bearer '+t}),
      'xro':probe({'X-Read-Only-Token':t}),
      'none':probe({}),
    }
    return Response(json.dumps(data,ensure_ascii=False),status=200,mimetype='application/json')
