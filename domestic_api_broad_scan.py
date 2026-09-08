import json, os, urllib.parse, urllib.request, urllib.error
import domestic_api_auth_json_scan as active
from flask import Response

app=active.app
HOST='https://medparkallo-medpark-salesops.mycafe24.ai'
TOKEN_ENV='PERFORMANCE_READ_ONLY_TOKEN'
PATHS=[
 '/api/performance','/api/performance/','/api/v1/performance','/api/read-only/performance','/api/performance-read-only',
 '/api/fcst','/api/fcst/','/api/fcst/summary','/api/fcst/current','/api/fcst-cycle','/api/fcst_cycle',
 '/api/forecast','/api/forecast/summary','/api/forecasts','/api/monthly-close','/api/monthly_close','/api/close','/api/closing',
 '/api/sales-performance','/api/sales_performance','/api/report-data','/api/report_data','/api/dashboard-data','/api/dashboard_data',
 '/api/erp/actual','/api/erp-actual','/api/monthly-performance','/api/monthly_performance'
]

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl): return None

def hit(path,headers):
    url=HOST+path+'?'+urllib.parse.urlencode({'year':2026,'month':9})
    req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'MedPark-Performance-Report/1.0','X-Requested-With':'XMLHttpRequest',**headers},method='GET')
    opener=urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req,timeout=6) as r:
            raw=r.read(800).decode('utf-8','replace')
            c=(r.headers.get('Content-Type') or '').lower()
            js=('json' in c) or raw.lstrip().startswith(('{','['))
            return {'status':getattr(r,'status',200),'json':js,'location':r.headers.get('Location')}
    except urllib.error.HTTPError as e:
        try: raw=e.read(800).decode('utf-8','replace')
        except Exception: raw=''
        c=(e.headers.get('Content-Type') or '').lower()
        js=('json' in c) or raw.lstrip().startswith(('{','['))
        return {'status':e.code,'json':js,'location':e.headers.get('Location')}
    except Exception as e:
        return {'status':0,'json':False,'error':type(e).__name__}

@app.get('/domestic-diag/broad-scan')
def broad_scan():
    t=os.environ.get(TOKEN_ENV,'').strip()
    auths=[('none',{}),('bearer',{'Authorization':'Bearer '+t}),('xro',{'X-Read-Only-Token':t}),('x-api-key',{'X-API-Key':t})]
    found=[]; results={}
    for p in PATHS:
        results[p]={}
        for name,h in auths:
            r=hit(p,h); results[p][name]=r
            if r.get('status')==200 and r.get('json'):
                found.append({'path':p,'auth':name})
    return Response(json.dumps({'found':found,'results':results},ensure_ascii=False),status=200,mimetype='application/json')
