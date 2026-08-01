"""config.json 管理：默认值、点路径读写、线程安全、自动建文件。"""
import json
import os
import threading

from . import paths

DEFAULTS = {
    "provider": {
        "name": "deepseek",
        "model": "deepseek-chat",
        "api_key": "",
        "base_url": "",
        "vision": False,
        "search": False,
    },
    "providers": [],  # 提供商池（多 AI 轮询）：[{name, model, api_key, base_url, enabled, vision, search}]
    "proxy": {"enabled": False, "url": "http://127.0.0.1:7897"},
    "vndb_token": "",
    "library_roots": [],
    "ui": {"theme": "dark", "language": "zh-CN"},
    "analysis": {"auto_confirm_threshold": 0.9, "concurrency": 2},
    "backup": {"auto_enabled": True, "interval_days": 7},
}


def _deep_merge(base, override):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


class Config:
    def __init__(self, path=None):
        self._lock = threading.Lock()
        self.path = path or paths.CONFIG_FILE
        self._data = json.loads(json.dumps(DEFAULTS))  # 深拷贝默认值
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self._data = _deep_merge(json.loads(json.dumps(DEFAULTS)), loaded)
        except FileNotFoundError:
            self.save()

    def get(self, key, default=None):
        node = self._data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key, value):
        with self._lock:
            parts = key.split(".")
            node = self._data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
            self._save()

    def as_dict(self):
        return json.loads(json.dumps(self._data))

    def save(self):
        with self._lock:
            self._save()

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    c = Config()
    print("config OK:", c.path)
    print(json.dumps(c.as_dict(), ensure_ascii=False, indent=2))
