import json, os, urllib.parse, urllib.request, urllib.error
import domestic_api_redirect_diag as active
from flask import Response

app=active.app
HOST='https://medparkallo-medpark-salesops.mycafe24.ai'
TOKEN_ENV='PERFORMANCE_READ_ONLY_TOKEN'
PATHS=[
 '/api/performance','/api/performance/','/api/v1/performance','/api/read-only/performance',
 '/api/performance-read-only','/performance-api','/api/performance.json','/performance'
]

def hit(path, headers):
    url=HOST+path+'?'+urllib.parse.urlencode({'year':2026,'month':9})
    req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'MedPark-Performance-Report/1.0',**headers},method='GET')
    try:
        with urllib.request.urlopen(req,timeout=8) as r:
            raw=r.read(500).decode('utf-8','replace')
            ctype=(r.headers.get('Content-Type') or '').lower()
            ok=getattr(r,'status',200)==200 and ('json' in ctype or raw.lstrip().startswith(('{','[')))
            return {'status':getattr(r,'status',200),'json':ok,'ctype':ctype[:60]}
    except urllib.error.HTTPError as e:
        return {'status':e.code,'json':False,'ctype':(e.headers.get('Content-Type') or '')[:60]}
    except Exception as e:
        return {'status':0,'json':False,'error':type(e).__name__}

@app.get('/domestic-diag/path-scan')
def path_scan():
    t=os.environ.get(TOKEN_ENV,'').strip()
    variants=[('bearer',{'Authorization':'Bearer '+t}),('xro',{'X-Read-Only-Token':t})]
    out={}; winner=None
    for p in PATHS:
        out[p]={}
        for n,h in variants:
            r=hit(p,h); out[p][n]=r
            if r.get('json') and not winner: winner={'path':p,'auth':n}
    return Response(json.dumps({'winner':winner,'results':out},ensure_ascii=False),status=200,mimetype='application/json')
