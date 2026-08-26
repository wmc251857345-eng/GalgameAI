"""SQLite 数据库：线程安全、行字典返回。
升级策略：只做无损迁移（CREATE IF NOT EXISTS + ALTER ADD COLUMN），
任何情况下都不 DROP 重建用户库（v1.1 起正式版铁律）。"""
import os
import sqlite3
import threading

from . import paths

SCHEMA_VERSION = 4

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
    match_confidence REAL, source TEXT,  -- vndb|bgm|ai|manual
    user_rating INTEGER DEFAULT 0,       -- 用户评分 0(未评)~5 星（v1.1）
    notes TEXT                           -- 个人笔记（v1.1）
);
CREATE INDEX IF NOT EXISTS idx_games_path ON games(path);
CREATE INDEX IF NOT EXISTS idx_games_status ON games(status);
CREATE INDEX IF NOT EXISTS idx_games_vndb ON games(vndb_id);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER, started_at TEXT, ended_at TEXT, seconds INTEGER,
    estimated INTEGER DEFAULT 0
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
CREATE TABLE IF NOT EXISTS producer_map (
    maker_name TEXT PRIMARY KEY,
    vndb_id TEXT, display_name TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS makers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,            -- 锚定后的规范名（唯一展示名）
    vndb_id TEXT,                -- 该厂商的 VNDB producer id（用于关联外部资料）
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS maker_aliases (
    alias TEXT PRIMARY KEY,      -- 一种写法（中/英/日文变体）
    maker_id INTEGER,            -- → makers.id
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_maker_aliases_maker ON maker_aliases(maker_id);
CREATE TABLE IF NOT EXISTS tag_cache (
    en_name TEXT PRIMARY KEY,
    zh_name TEXT
);
CREATE TABLE IF NOT EXISTS maker_follows (
    maker_name TEXT PRIMARY KEY,
    vndb_id TEXT, display_name TEXT,
    created_at TEXT
);

-- 想玩清单（v1.1）：还没入库/还没买，想玩的记录
CREATE TABLE IF NOT EXISTS wishlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    note TEXT,
    vndb_id TEXT,
    created_at TEXT
);

-- 存档备份：每款游戏的引擎映射 + 备份元数据
CREATE TABLE IF NOT EXISTS backup_history (
    game_id INTEGER PRIMARY KEY,     -- → games.id
    engine_name TEXT,                -- 引擎识别名（custom game 名）
    save_paths TEXT DEFAULT '[]',    -- JSON: 手动配置的存档路径列表（custom games files）
    last_backup_at TEXT,             -- 上次备份时间 ISO
    last_save_change_at TEXT,        -- 存档源最近变动时间 ISO（扫描时取 max mtime）
    total_bytes INTEGER DEFAULT 0,   -- 上次备份总大小
    backup_count INTEGER DEFAULT 0   -- 累计备份次数
);
CREATE TABLE IF NOT EXISTS backup_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER,                 -- → games.id
    backed_at TEXT,                  -- 备份时间 ISO
    engine_when TEXT,                -- 引擎报告的时间戳
    bytes INTEGER DEFAULT 0,
    status TEXT DEFAULT 'ok'         -- ok|failed
);
CREATE INDEX IF NOT EXISTS idx_backup_versions_game ON backup_versions(game_id);

-- 扫描历史：每次扫描的记录（新增游戏清单/总数/失效数），供前端展示"本次新增 N 款"
CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT, ended_at TEXT,
    roots TEXT DEFAULT '[]',             -- JSON: 本次扫描的根目录
    new_count INTEGER DEFAULT 0,         -- 本次新增游戏数
    total_count INTEGER DEFAULT 0,       -- 扫描后库内总数
    missing_count INTEGER DEFAULT 0,     -- exe 失效数
    new_games TEXT DEFAULT '[]'          -- JSON: [{id, title, path}]
);

-- 目录整理历史：自动整理引擎的移动记录
CREATE TABLE IF NOT EXISTS organize_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER, title TEXT,
    from_path TEXT, to_path TEXT,
    moved_at TEXT, ok INTEGER DEFAULT 1
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
                # 防数据毁灭（历史教训）：版本变化前先把旧库完整备份。
                # 备份用 sqlite3 在线备份 API（一致快照，无需关闭连接）。
                # v1.1 起不再 DROP 重建 —— 全部走无损迁移（CREATE IF NOT EXISTS +
                # ALTER ADD COLUMN），旧库数据原样保留，备份只是双保险。
                import time as _t
                bak_dir = os.path.join(os.path.dirname(self.path), "backup")
                try:
                    os.makedirs(bak_dir, exist_ok=True)
                    bak = os.path.join(
                        bak_dir,
                        f"pre_upgrade_v{v}_{_t.strftime('%Y%m%d_%H%M%S')}.db")
                    dest = sqlite3.connect(bak)
                    try:
                        with dest:
                            conn.backup(dest)
                    finally:
                        dest.close()
                    print(f"[GALA] 升级前旧库已备份: {bak}")
                except Exception as e:
                    # 备份失败也不再中止：无损迁移本身不动已有表/列，风险可控
                    print(f"[GALA] 旧库备份失败({e})，继续无损迁移")
            conn.executescript(_SCHEMA)
            self._migrate(conn)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()

    @staticmethod
    def _migrate(conn):
        """无损迁移：已有库补新列（不重建表、不丢数据）。"""
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(games)")}
        if "favorite" not in cols:
            conn.execute("ALTER TABLE games ADD COLUMN favorite INTEGER DEFAULT 0")
        if "steam_id" not in cols:
            conn.execute("ALTER TABLE games ADD COLUMN steam_id TEXT")
        if "cover_orig_path" not in cols:
            conn.execute("ALTER TABLE games ADD COLUMN cover_orig_path TEXT")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(match_cache)")}
        if "provider" not in cols:
            conn.execute("ALTER TABLE match_cache ADD COLUMN provider TEXT DEFAULT 'vndb'")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(chat_messages)")}
        if "image" not in cols:
            conn.execute("ALTER TABLE chat_messages ADD COLUMN image TEXT")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(backup_versions)")}
        if "kind" not in cols:
            # 快照类型：manual（手动/引擎备份）| auto（关游戏自动备份）
            conn.execute("ALTER TABLE backup_versions ADD COLUMN kind TEXT DEFAULT 'manual'")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
        if "estimated" not in cols:
            # 估算结算标记：孤儿会话由 reconcile 按估算补记时置 1（不计入总时长）
            conn.execute("ALTER TABLE sessions ADD COLUMN estimated INTEGER DEFAULT 0")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(games)")}
        if "play_state" not in cols:
            # 游玩进度：0 未开始 / 1 进行中 / 2 已通关（Galgame 库核心管理维度）
            conn.execute("ALTER TABLE games ADD COLUMN play_state INTEGER DEFAULT 0")
        if "user_rating" not in cols:
            # 用户评分：0(未评)~5 星，区别于 VNDB 外部评分 rating（v1.1）
            conn.execute("ALTER TABLE games ADD COLUMN user_rating INTEGER DEFAULT 0")
        if "notes" not in cols:
            # 个人笔记（v1.1）：自由文本，参与搜索
            conn.execute("ALTER TABLE games ADD COLUMN notes TEXT")

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
