import base64
import gzip
import json
import os

DATA_DIR = os.environ.get('DATA_DIR', '/app/user_data')
DATA_FILE = os.path.join(DATA_DIR, 'performance_data.json')

if os.environ.get('APPLY_INITIAL_DATA') == '1':
    packed = os.environ.get('INITIAL_DATA_GZ', '').strip()
    if packed:
        raw = gzip.decompress(base64.b64decode(packed)).decode('utf-8')
        data = json.loads(raw)
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = DATA_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)
        print('Initial performance data applied.')

if os.environ.get('RUN_SELFTEST') == '1':
    import app as appmod

    expected_scopes = {
        'mpadmin': [('덴탈','국내'),('덴탈','해외'),('메디컬','국내'),('메디컬','해외'),('에스테틱','국내'),('에스테틱','해외')],
        'mpdomestic': [('덴탈','국내'),('메디컬','국내'),('에스테틱','국내')],
        'mpdental': [('덴탈','국내')],
        'mpglobal': [('덴탈','해외'),('메디컬','해외'),('에스테틱','해외')],
        'mpaesthetic': [('에스테틱','국내'),('에스테틱','해외')],
    }
    results = {'login': {}, 'admin_access': {}, 'scopes': {}, 'numbers': {}, 'all_ok': True}
    for uid, expected in expected_scopes.items():
        user = appmod.get_user(uid)
        scope_ok = appmod.scope_pairs(user) == expected
        results['scopes'][uid] = {'ok': scope_ok, 'actual': appmod.scope_pairs(user)}
        client = appmod.app.test_client()
        resp = client.post('/login', data={'user_id': uid, 'password': 'medpark2026'}, follow_redirects=False)
        login_ok = resp.status_code == 302
        home = client.get('/', follow_redirects=False)
        login_ok = login_ok and home.status_code == 200
        results['login'][uid] = {'ok': login_ok, 'login_status': resp.status_code, 'home_status': home.status_code}
        users_resp = client.get('/users', follow_redirects=False)
        access_ok = (users_resp.status_code == 200) if uid == 'mpadmin' else (users_resp.status_code == 302)
        results['admin_access'][uid] = {'ok': access_ok, 'status': users_resp.status_code}
        results['all_ok'] = results['all_ok'] and scope_ok and login_ok and access_ok

    report = appmod.report_data(2026, 8)
    grand = next(r for r in report['rows'] if r.get('is_grand'))
    checks = {
        'ytd_1_7': (grand['ytd'], 9417886063),
        'aug_1': (grand['first'], 1643693152),
        'aug_2': (grand['second'], 1772844502.6230001),
        'aug_3_confirmed': (grand['third_confirmed'], 1176386384),
        'aug_3_forecast': (grand['third_forecast'], 1483709990),
        'sep_1': (grand['next_first'], 1784250384),
    }
    for name, (actual, expected) in checks.items():
        ok = abs(float(actual) - float(expected)) < 0.01
        results['numbers'][name] = {'ok': ok, 'actual': actual, 'expected': expected}
        results['all_ok'] = results['all_ok'] and ok
    print('SELFTEST_RESULT=' + json.dumps(results, ensure_ascii=False, sort_keys=True))
