import json, os, urllib.parse, urllib.request, urllib.error
import august_overseas_provisional_close as active
from flask import Response

app = active.app
api = __import__('salesops_api_patch')
BASE = 'https://medparkallo-medpark-salesops.mycafe24.ai/api/performance'
TOKEN_ENV = 'PERFORMANCE_READ_ONLY_TOKEN'

def request_once(headers=None, params=None):
    token = os.environ.get(TOKEN_ENV, '').strip()
    q = {'year':2026,'month':9}
    if params: q.update(params)
    url = BASE + '?' + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={'Accept':'application/json','User-Agent':'MedPark-Performance-Report/1.0', **(headers or {})}, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            raw = res.read().decode('utf-8','replace')
            return getattr(res,'status',200), raw
    except urllib.error.HTTPError as e:
        try: raw = e.read().decode('utf-8','replace')
        except Exception: raw = ''
        return e.code, raw
    except Exception as e:
        return 0, type(e).__name__

def auth_scan():
    t=os.environ.get(TOKEN_ENV,'').strip()
    if not t: return {'token_configured':False}
    variants = [
        ('bearer', {'Authorization':'Bearer '+t}, None),
        ('authorization-token', {'Authorization':'Token '+t}, None),
        ('authorization-raw', {'Authorization':t}, None),
        ('x-read-only-token', {'X-Read-Only-Token':t}, None),
        ('x-api-key', {'X-API-Key':t}, None),
        ('x-auth-token', {'X-Auth-Token':t}, None),
        ('x-performance-token', {'X-Performance-Token':t}, None),
        ('x-performance-read-only-token', {'X-Performance-Read-Only-Token':t}, None),
        ('api-key', {'Api-Key':t}, None),
        ('query-token', {}, {'token':t}),
        ('query-api-key', {}, {'api_key':t}),
        ('query-read-only-token', {}, {'read_only_token':t}),
    ]
    out={'token_configured':True,'results':{}}
    for name,h,p in variants:
        code,_ = request_once(h,p)
        out['results'][name]=code
    return out

def fetch():
    t=os.environ.get(TOKEN_ENV,'').strip()
    if not t:
        return {'token':False,'http':None,'json':False,'rows':0,'parsed':0,'domestic':0,'reason':'token_missing','top_keys':[],'row_keys':[]}
    for name,h in [('bearer',{'Authorization':'Bearer '+t}),('xro',{'X-Read-Only-Token':t})]:
        status,raw=request_once(h)
        if status==200:
            try: payload=json.loads(raw)
            except Exception:
                return {'token':True,'auth':name,'http':status,'json':False,'rows':0,'parsed':0,'domestic':0,'reason':'invalid_json','top_keys':[],'row_keys':[]}
            rows=api._extract_rows(payload)
            parsed=[api._parse_row(r) for r in rows]
            parsed=[r for r in parsed if r]
            domestic=[r for r in parsed if r.get('region')=='국내']
            top_keys=sorted([str(k) for k in payload.keys()]) if isinstance(payload,dict) else ['<list>']
            row_keys=sorted([str(k) for k in rows[0].keys()]) if rows and isinstance(rows[0],dict) else []
            return {'token':True,'auth':name,'http':status,'json':True,'rows':len(rows),'parsed':len(parsed),'domestic':len(domestic),'reason':'ok' if parsed else 'no_parsed_rows','top_keys':top_keys,'row_keys':row_keys}
    return {'token':True,'http':401,'json':False,'rows':0,'parsed':0,'domestic':0,'reason':'http_401','top_keys':[],'row_keys':[]}

def bool_response(ok,label,data):
    body=label+'='+('OK' if ok else 'FAIL')+';'+json.dumps(data,ensure_ascii=False,separators=(',',':'))
    return Response(body,status=200 if ok else 409,mimetype='text/plain; charset=utf-8')

@app.get('/domestic-diag/auth')
def diag_auth():
    d=fetch(); return bool_response(d.get('http')==200,'AUTH',d)
@app.get('/domestic-diag/json')
def diag_json():
    d=fetch(); return bool_response(bool(d.get('json')),'JSON',d)
@app.get('/domestic-diag/rows')
def diag_rows():
    d=fetch(); return bool_response(d.get('rows',0)>0,'ROWS',d)
@app.get('/domestic-diag/parsed')
def diag_parsed():
    d=fetch(); return bool_response(d.get('parsed',0)>0,'PARSED',d)
@app.get('/domestic-diag/domestic')
def diag_domestic():
    d=fetch(); return bool_response(d.get('domestic',0)>0,'DOMESTIC',d)
@app.get('/domestic-diag/summary')
def diag_summary():
    return Response(json.dumps(fetch(),ensure_ascii=False),status=200,mimetype='application/json')
@app.get('/domestic-diag/auth-scan')
def diag_auth_scan():
    return Response(json.dumps(auth_scan(),ensure_ascii=False),status=200,mimetype='application/json')
