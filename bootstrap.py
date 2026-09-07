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
