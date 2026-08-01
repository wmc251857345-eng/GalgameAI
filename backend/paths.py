"""路径解析：开发模式（源码根）与 PyInstaller 冻结模式（exe 所在目录）通用。"""
import os
import sys


def is_frozen():
    return getattr(sys, "frozen", False)


def root_dir():
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure(p):
    os.makedirs(p, exist_ok=True)
    return p


BASE = root_dir()
CONFIG_DIR = _ensure(os.path.join(BASE, "config"))
DB_DIR = _ensure(os.path.join(BASE, "database"))
CACHE_DIR = _ensure(os.path.join(BASE, "cache"))
COVERS_DIR = _ensure(os.path.join(CACHE_DIR, "covers"))
THUMBS_DIR = _ensure(os.path.join(CACHE_DIR, "thumbs"))
AI_CACHE_DIR = _ensure(os.path.join(CACHE_DIR, "ai"))
PLUGINS_DIR = _ensure(os.path.join(BASE, "plugins"))
LOGS_DIR = _ensure(os.path.join(BASE, "logs"))

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DB_FILE = os.path.join(DB_DIR, "library.db")
