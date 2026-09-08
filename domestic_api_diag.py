import json, os, urllib.parse, urllib.request, urllib.error
import august_overseas_provisional_close as active
from flask import Response

app = active.app
api = __import__('salesops_api_patch')

BASE = 'https://medparkallo-medpark-salesops.mycafe24.ai/api/performance'
TOKEN_ENV = 'PERFORMANCE_READ_ONLY_TOKEN'

def fetch(year=2026, month=9):
    token = os.environ.get(TOKEN_ENV, '').strip()
    if not token:
        return {'token':False,'http':None,'json':False,'rows':0,'parsed':0,'domestic':0,'reason':'token_missing','top_keys':[],'row_keys':[]}
    url = BASE + '?' + urllib.parse.urlencode({'year':year,'month':month})
    last = None
    for name, headers in [
        ('bearer', {'Authorization':'Bearer '+token}),
        ('xro', {'X-Read-Only-Token':token}),
    ]:
        req = urllib.request.Request(url, headers={'Accept':'application/json','User-Agent':'MedPark-Diag/1.0', **headers}, method='GET')
        try:
            with urllib.request.urlopen(req, timeout=8) as res:
                raw = res.read().decode('utf-8','replace')
                status = getattr(res,'status',200)
            try:
                payload = json.loads(raw)
            except Exception:
                return {'token':True,'auth':name,'http':status,'json':False,'rows':0,'parsed':0,'domestic':0,'reason':'invalid_json','top_keys':[],'row_keys':[]}
            rows = api._extract_rows(payload)
            parsed = [api._parse_row(r) for r in rows]
            parsed = [r for r in parsed if r]
            domestic = [r for r in parsed if r.get('region')=='국내']
            top_keys = sorted([str(k) for k in payload.keys()]) if isinstance(payload,dict) else ['<list>']
            row_keys = sorted([str(k) for k in rows[0].keys()]) if rows and isinstance(rows[0],dict) else []
            return {'token':True,'auth':name,'http':status,'json':True,'rows':len(rows),'parsed':len(parsed),'domestic':len(domestic),'reason':'ok' if parsed else 'no_parsed_rows','top_keys':top_keys,'row_keys':row_keys}
        except urllib.error.HTTPError as e:
            last = {'token':True,'auth':name,'http':e.code,'json':False,'rows':0,'parsed':0,'domestic':0,'reason':'http_'+str(e.code),'top_keys':[],'row_keys':[]}
            if e.code not in (401,403):
                break
        except Exception as e:
            last = {'token':True,'auth':name,'http':None,'json':False,'rows':0,'parsed':0,'domestic':0,'reason':type(e).__name__,'top_keys':[],'row_keys':[]}
            break
    return last or {'reason':'failed'}

def bool_response(ok, label, data):
    body = label + '=' + ('OK' if ok else 'FAIL') + ';' + json.dumps(data, ensure_ascii=False, separators=(',',':'))
    return Response(body, status=200 if ok else 409, mimetype='text/plain; charset=utf-8')

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
    d=fetch(); return Response(json.dumps(d,ensure_ascii=False),status=200,mimetype='application/json')
