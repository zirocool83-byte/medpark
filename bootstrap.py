import json
import os

DATA_DIR = os.environ.get('DATA_DIR', '/app/user_data')
DATA_FILE = os.path.join(DATA_DIR, 'performance_data.json')

if os.environ.get('APPLY_INITIAL_DATA') == '1':
    raw = os.environ.get('INITIAL_DATA', '').strip()
    if raw:
        data = json.loads(raw)
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = DATA_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)
        print('Initial performance data applied.')
