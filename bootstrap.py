import base64
import gzip
import json
import os
import shutil
from datetime import datetime

DATA_DIR = os.environ.get("DATA_DIR", "/app/user_data")
DATA_FILE = os.path.join(DATA_DIR, "performance_data.json")


def read_current():
    if not os.path.exists(DATA_FILE):
        return None
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def needs_auto_seed(data):
    if not isinstance(data, dict):
        return True
    if not data.get("meta", {}).get("initialized"):
        return True
    if not data.get("users"):
        return True
    return False


def write_atomic(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


current = read_current()
if needs_auto_seed(current):
    packed = os.environ.get("AUTO_SEED_GZ", "").strip()
    if not packed:
        raise RuntimeError("AUTO_SEED_GZ is required when performance data is missing")

    raw = gzip.decompress(base64.b64decode(packed)).decode("utf-8")
    seed = json.loads(raw)
    if not isinstance(seed, dict):
        raise RuntimeError("Invalid auto seed payload")
    if len(seed.get("users", [])) != 10:
        raise RuntimeError("Invalid auto seed users")
    if len(seed.get("actuals", {})) != 84:
        raise RuntimeError("Invalid auto seed actuals")
    if len(seed.get("entries", [])) != 87:
        raise RuntimeError("Invalid auto seed entries")

    seed.setdefault("meta", {})
    seed["meta"]["initialized"] = True
    seed["meta"]["auto_seeded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if os.path.exists(DATA_FILE):
        backup = DATA_FILE + ".before_autoseed." + datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy2(DATA_FILE, backup)

    write_atomic(seed)
    print("Performance data auto-seeded: 10 users / 84 actuals / 87 entries")
else:
    print("Existing initialized performance data kept.")
