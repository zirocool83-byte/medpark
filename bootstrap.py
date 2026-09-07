import base64
import gzip
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('DATA_DIR', '/app/user_data')
DATA_FILE = os.path.join(DATA_DIR, 'performance_data.json')
APP_FILE = os.path.join(BASE_DIR, 'app.py')

# Admin rights do not automatically widen the ordinary input scope.
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
