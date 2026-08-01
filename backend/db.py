"""SQLite 数据库：schema v2、线程安全、行字典返回。
开发阶段：版本不一致时直接重建（正式版需迁移框架）。"""
import os
import sqlite3
import threading

from . import paths

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT, root TEXT,
    vndb_id TEXT, bgm_id INTEGER,
    title TEXT, title_en TEXT, title_jp TEXT, title_zh TEXT,
    aliases TEXT, maker TEXT, brand TEXT, released TEXT,
    rating REAL, length_level INTEGER, length_minutes INTEGER,
    description TEXT,
    cover_path TEXT, cover_url TEXT, cover_local TEXT,
    exe_path TEXT, workdir TEXT, launch_args TEXT,
    use_locale_emu INTEGER DEFAULT 0,
    hanhua INTEGER DEFAULT 0, text_sample TEXT, size_bytes INTEGER DEFAULT 0,
    playtime_seconds INTEGER DEFAULT 0, last_played TEXT, added_at TEXT,
    status INTEGER DEFAULT 0,            -- 0扫描到 1待确认 2已入库 3手动/跳过
    match_confidence REAL, source TEXT   -- vndb|bgm|ai|manual
);
CREATE INDEX IF NOT EXISTS idx_games_path ON games(path);
CREATE INDEX IF NOT EXISTS idx_games_status ON games(status);
CREATE INDEX IF NOT EXISTS idx_games_vndb ON games(vndb_id);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER, started_at TEXT, ended_at TEXT, seconds INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sessions_game ON sessions(game_id);

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
CREATE TABLE IF NOT EXISTS match_candidates (
    game_id INTEGER, provider TEXT, external_id TEXT,
    title TEXT, score REAL, payload TEXT,
    PRIMARY KEY (game_id, provider, external_id)
);
CREATE INDEX IF NOT EXISTS idx_candidates_game ON match_candidates(game_id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT, content TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS vndb_work_cache (
    vndb_id TEXT PRIMARY KEY,
    zh_title TEXT, zh_summary TEXT,
    fetched_at TEXT
);
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
        with self._lock:
            conn = self.connect()
            v = conn.execute("PRAGMA user_version").fetchone()[0]
            if v != SCHEMA_VERSION:
                tables = [r["name"] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
                for t in tables:
                    conn.execute(f'DROP TABLE IF EXISTS "{t}"')
                conn.execute("PRAGMA user_version = 0")
                conn.commit()
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._migrate(conn)
            conn.commit()

    @staticmethod
    def _migrate(conn):
        """无损迁移：已有库补新列（不重建表、不丢数据）。"""
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(games)")}
        if "favorite" not in cols:
            conn.execute("ALTER TABLE games ADD COLUMN favorite INTEGER DEFAULT 0")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(match_cache)")}
        if "provider" not in cols:
            conn.execute("ALTER TABLE match_cache ADD COLUMN provider TEXT DEFAULT 'vndb'")

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
