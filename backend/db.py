"""SQLite 数据库：schema v1、线程安全连接、行字典返回。"""
import os
import sqlite3
import threading

from . import paths

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vndb_id TEXT, bgm_id INTEGER,
    title TEXT, title_en TEXT, title_jp TEXT, title_zh TEXT,
    aliases TEXT, maker TEXT, brand TEXT, released TEXT,
    rating REAL, length_level INTEGER, length_minutes INTEGER,
    description TEXT, cover_path TEXT,
    exe_path TEXT, workdir TEXT, launch_args TEXT,
    use_locale_emu INTEGER DEFAULT 0,
    playtime_seconds INTEGER DEFAULT 0, last_played TEXT, added_at TEXT,
    status INTEGER DEFAULT 0,            -- 0扫描到 1待确认 2已入库 3手动
    match_confidence REAL, source TEXT   -- vndb|bgm|ai|manual
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER, started_at TEXT, ended_at TEXT, seconds INTEGER
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE, category TEXT
);
CREATE TABLE IF NOT EXISTS game_tags (
    game_id INTEGER, tag_id INTEGER,
    spoiler_level INTEGER DEFAULT 0, source TEXT,
    PRIMARY KEY (game_id, tag_id)
);
CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER, role TEXT, name TEXT, vndb_staff_id TEXT
);
CREATE TABLE IF NOT EXISTS screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER, path TEXT, source TEXT, ord INTEGER
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS match_cache (
    folder_key TEXT PRIMARY KEY,
    vndb_id TEXT, confidence REAL, chosen_by_user INTEGER DEFAULT 0, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER, stage TEXT, status TEXT,
    attempts INTEGER DEFAULT 0, error TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_games_status ON games(status);
CREATE INDEX IF NOT EXISTS idx_games_vndb ON games(vndb_id);
CREATE INDEX IF NOT EXISTS idx_sessions_game ON sessions(game_id);
"""


class Database:
    def __init__(self, path=None):
        self._lock = threading.RLock()
        self.path = path or paths.DB_FILE
        self._conn = None

    def connect(self):
        with self._lock:
            if self._conn is None:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                self._conn = sqlite3.connect(self.path, check_same_thread=False)
                self._conn.row_factory = sqlite3.Row
            return self._conn

    def init(self):
        conn = self.connect()
        with self._lock:
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()

    def query(self, sql, params=()):
        with self._lock:
            cur = self.connect().execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def query_one(self, sql, params=()):
        with self._lock:
            cur = self.connect().execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None

    def execute(self, sql, params=()):
        with self._lock:
            conn = self.connect()
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


if __name__ == "__main__":
    db = Database()
    db.init()
    v = db.query_one("PRAGMA user_version")["user_version"]
    tables = [r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print(f"DB OK: {db.path} (user_version={v})")
    print("tables:", ", ".join(tables))
