"""utils/storage.py — JSON read/write helpers"""
import os, json, uuid
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE  = os.path.join(BASE_DIR, "..", "storage")

def storage_path(*parts):
    return os.path.join(STORAGE, *parts) if parts else STORAGE

def read_json(path, default=None):
    if default is None: default = []
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def new_id():
    return uuid.uuid4().hex[:12]
