import json, os, urllib.parse, urllib.request, urllib.error
import domestic_api_path_scan as active
from flask import Response

app=active.app
BASE='https://medparkallo-medpark-salesops.mycafe24.ai/api/performance'
TOKEN_ENV='PERFORMANCE_READ_ONLY_TOKEN'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl): return None

def test(headers=None, params=None):
    q={'year':2026,'month':9}
    if params: q.update(params)
    url=BASE+'?'+urllib.parse.urlencode(q)
    req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'MedPark-Performance-Report/1.0','X-Requested-With':'XMLHttpRequest',**(headers or {})},method='GET')
    opener=urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req,timeout=8) as r:
            raw=r.read(700).decode('utf-8','replace')
            c=(r.headers.get('Content-Type') or '').lower()
            js=('json' in c) or raw.lstrip().startswith(('{','['))
            return {'status':getattr(r,'status',200),'json':js,'location':r.headers.get('Location')}
    except urllib.error.HTTPError as e:
        try: raw=e.read(700).decode('utf-8','replace')
        except Exception: raw=''
        c=(e.headers.get('Content-Type') or '').lower()
        js=('json' in c) or raw.lstrip().startswith(('{','['))
        return {'status':e.code,'json':js,'location':e.headers.get('Location')}
    except Exception as e:
        return {'status':0,'json':False,'error':type(e).__name__}

@app.get('/domestic-diag/auth-json-scan')
def auth_json_scan():
    t=os.environ.get(TOKEN_ENV,'').strip()
    variants=[
      ('bearer',{'Authorization':'Bearer '+t},None),
      ('x-read-only-token',{'X-Read-Only-Token':t},None),
      ('x-api-key',{'X-API-Key':t},None),
      ('x-auth-token',{'X-Auth-Token':t},None),
      ('x-performance-token',{'X-Performance-Token':t},None),
      ('x-performance-read-only-token',{'X-Performance-Read-Only-Token':t},None),
      ('authorization-token',{'Authorization':'Token '+t},None),
      ('authorization-raw',{'Authorization':t},None),
      ('bearer+xro',{'Authorization':'Bearer '+t,'X-Read-Only-Token':t},None),
      ('bearer+x-api-key',{'Authorization':'Bearer '+t,'X-API-Key':t},None),
      ('query-token',{}, {'token':t}),
      ('query-api-key',{}, {'api_key':t}),
      ('query-read-only-token',{}, {'read_only_token':t}),
    ]
    results={}; winner=None
    for name,h,p in variants:
        r=test(h,p); results[name]=r
        if r.get('status')==200 and r.get('json') and winner is None:
            winner=name
    return Response(json.dumps({'winner':winner,'results':results},ensure_ascii=False),status=200,mimetype='application/json')
