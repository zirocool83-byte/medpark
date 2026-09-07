import base64
import gzip
import json
import os
import shutil
from datetime import datetime

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('DATA_DIR', '/app/user_data')
DATA_FILE = os.path.join(DATA_DIR, 'performance_data.json')
APP_FILE = os.path.join(BASE_DIR, 'app.py')

# Keep admin management rights separate from ordinary input scope.
if os.path.exists(APP_FILE):
    with open(APP_FILE, 'r', encoding='utf-8') as f:
        source = f.read()
    old = 'if user.get("role") == "admin" or p == "admin":\n        return ALL_PAIRS'
    new = 'if p == "admin":\n        return ALL_PAIRS'
    if old in source:
        source = source.replace(old, new, 1)
        with open(APP_FILE, 'w', encoding='utf-8') as f:
            f.write(source)
    elif new not in source:
        raise RuntimeError('scope policy patch target not found')

# Legacy initial-data hook; normally disabled after first initialization.
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

expected_payload = None
if os.environ.get('APPLY_USER_FIX') == '1':
    packed = os.environ.get('USER_FIX_GZ', '').strip()
    if not packed:
        raise RuntimeError('USER_FIX_GZ missing')
    expected_payload = json.loads(gzip.decompress(base64.b64decode(packed)).decode('utf-8'))
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    backup = DATA_FILE + '.before_userfix.' + datetime.now().strftime('%Y%m%d%H%M%S')
    shutil.copy2(DATA_FILE, backup)

    prepared = []
    for raw_user in expected_payload.get('users', []):
        user = dict(raw_user)
        password = user.pop('initial_password')
        user['password_hash'] = generate_password_hash(password)
        user['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        user['updated_at'] = user['created_at']
        prepared.append(user)
    data['users'] = prepared

    remove_ids = set(expected_payload.get('remove_user_ids', []))
    remove_names = set(expected_payload.get('remove_display_names', []))
    for entry in data.get('entries', []):
        if entry.get('user_id') in remove_ids:
            entry['user_id'] = ''
        if entry.get('writer') in remove_names:
            entry['writer'] = '초기이관'
    data.setdefault('meta', {})['user_seed_version'] = expected_payload.get('version', '')

    tmp = DATA_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)
    print('User account correction applied: %d users.' % len(prepared))

if os.environ.get('RUN_USER_SELFTEST') == '1':
    if expected_payload is None:
        packed = os.environ.get('USER_FIX_GZ', '').strip()
        if not packed:
            raise RuntimeError('USER_FIX_GZ missing for self-test')
        expected_payload = json.loads(gzip.decompress(base64.b64decode(packed)).decode('utf-8'))

    import app as appmod

    expected_by_id = {u['user_id']: u for u in expected_payload.get('users', [])}
    data = appmod.read_store()
    actual_ids = {u.get('user_id') for u in data.get('users', [])}
    ok = actual_ids == set(expected_by_id)

    expected_scopes = {
        'admin': appmod.ALL_PAIRS,
        'domestic_all': [(b, '국내') for b in appmod.BUSINESSES],
        'dental_domestic': [('덴탈', '국내')],
        'overseas_all': [(b, '해외') for b in appmod.BUSINESSES],
        'aesthetics_all': [('에스테틱', '국내'), ('에스테틱', '해외')],
    }

    for uid, expected in expected_by_id.items():
        user = appmod.get_user(uid)
        if not user:
            ok = False
            continue
        if user.get('display_name') != expected.get('display_name'):
            ok = False
        if user.get('role') != expected.get('role') or user.get('permission_type') != expected.get('permission_type'):
            ok = False
        if appmod.scope_pairs(user) != expected_scopes.get(expected.get('permission_type'), []):
            ok = False

        client = appmod.app.test_client()
        login = client.post('/login', data={'user_id': uid, 'password': expected.get('initial_password', '')}, follow_redirects=False)
        home = client.get('/', follow_redirects=False)
        users_page = client.get('/users', follow_redirects=False)
        if login.status_code != 302 or home.status_code != 200:
            ok = False
        if expected.get('role') == 'admin':
            if users_page.status_code != 200:
                ok = False
        elif users_page.status_code != 302:
            ok = False

    remove_ids = set(expected_payload.get('remove_user_ids', []))
    remove_names = set(expected_payload.get('remove_display_names', []))
    if actual_ids & remove_ids:
        ok = False
    if any(u.get('display_name') in remove_names for u in data.get('users', [])):
        ok = False

    report = appmod.report_data(2026, 8)
    grand = next(r for r in report['rows'] if r.get('is_grand'))
    numeric_checks = [
        (grand['ytd'], 9417886063),
        (grand['first'], 1643693152),
        (grand['second'], 1772844502.6230001),
        (grand['third_confirmed'], 1176386384),
        (grand['third_forecast'], 1483709990),
        (grand['next_first'], 1784250384),
    ]
    if not all(abs(float(a) - float(b)) < 0.01 for a, b in numeric_checks):
        ok = False
    if len(data.get('entries', [])) != 87 or len(data.get('actuals', {})) != 84:
        ok = False

    print('USER_SELFTEST=' + ('PASS' if ok else 'FAIL') + ' users=' + str(len(actual_ids)))
    if not ok:
        raise RuntimeError('USER_SELFTEST_FAILED')
