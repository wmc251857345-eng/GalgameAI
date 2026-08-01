"""JsApi：pywebview 暴露给前端的方法（window.pywebview.api.*）。
每个方法在 pywebview 独立线程调用，DB/Config 自带锁。
"""
import json
import os
import threading

from . import launcher, paths
from .utils import now_iso

VERSION = "0.2.0"
BASE_URL = "http://127.0.0.1:0"  # app.py 启动 HTTP 服务后写入

_scan_thread = None
_analyze_thread = None


def _cover_url(path):
    """绝对/相对路径 → http URL（前端可 <img> 直接加载）。"""
    if not path:
        return None
    p = str(path).replace("\\", "/")
    if p.startswith("http"):
        return p
    if os.path.isabs(path):
        try:
            rel = os.path.relpath(path, paths.BASE).replace("\\", "/")
            return f"{BASE_URL}/{rel}"
        except ValueError:
            return None
    return f"{BASE_URL}/{p}"


def _game_row(g, with_extra=False):
    row = dict(g)
    row["cover_url"] = _cover_url(g.get("cover_path"))
    row["playtime_hours"] = round((g.get("playtime_seconds") or 0) / 3600, 1)
    if with_extra:
        row["tags"] = [t["name"] for t in _tags(g["id"])]
    return row


class JsApi:
    def __init__(self, db, config):
        self._db = db
        self._cfg = config

    # ---------- 基础 ----------
    def ping(self):
        return "pong"

    def get_app_info(self):
        return {
            "name": "GALA", "version": VERSION,
            "python": __import__("sys").version.split()[0],
            "platform": __import__("platform").system(),
            "db_path": self._db.path,
            "base_url": BASE_URL,
        }

    # ---------- 配置 ----------
    def get_config(self):
        return self._cfg.as_dict()

    def set_config(self, key, value):
        self._cfg.set(key, value)
        return self._cfg.as_dict()

    # ---------- 库 ----------
    def get_library_summary(self):
        def one(sql):
            return self._db.query_one(sql)
        return {
            "total": one("SELECT COUNT(*) c FROM games")["c"],
            "pending": one("SELECT COUNT(*) c FROM games WHERE status=1")["c"],
            "confirmed": one("SELECT COUNT(*) c FROM games WHERE status=2")["c"],
            "playtime_hours": round(one("SELECT COALESCE(SUM(playtime_seconds),0) s FROM games")["s"] / 3600, 1),
            "makers": one("SELECT COUNT(DISTINCT maker) c FROM games WHERE maker IS NOT NULL AND maker!=''")["c"],
        }

    def list_games(self, limit=1000, offset=0, sort="title", query=""):
        allowed = {"title", "released", "rating", "playtime_seconds", "last_played"}
        order = sort if sort in allowed else "title"
        sql = "SELECT * FROM games"
        params = []
        if query:
            sql += " WHERE title LIKE ? OR title_en LIKE ? OR title_jp LIKE ? OR maker LIKE ?"
            params = [f"%{query}%"] * 4
        sql += f" ORDER BY {order} LIMIT ? OFFSET ?"
        params += [int(limit), int(offset)]
        return [_game_row(g) for g in self._db.query(sql, params)]

    def get_game(self, game_id):
        g = self._db.query_one("SELECT * FROM games WHERE id=?", (int(game_id),))
        if not g:
            return None
        row = _game_row(g, with_extra=True)
        row["candidates"] = self._candidates(game_id) if g["status"] == 1 else []
        row["running"] = game_id in launcher.running_ids()
        return row

    def _tags(self, game_id):
        return self._db.query(
            "SELECT t.name FROM tags t JOIN game_tags gt ON t.id=gt.tag_id"
            " WHERE gt.game_id=? ORDER BY gt.rowid", (game_id,))

    def _candidates(self, game_id):
        out = []
        for c in self._db.query(
                "SELECT * FROM match_candidates WHERE game_id=? ORDER BY score DESC",
                (game_id,)):
            try:
                payload = json.loads(c["payload"])
            except Exception:
                payload = {}
            payload["score"] = c["score"]
            payload["provider"] = c["provider"]
            payload["external_id"] = c["external_id"]
            out.append(payload)
        return out

    # ---------- 扫描 / 分析 ----------
    def list_library_roots(self):
        return self._cfg.get("library_roots", [])

    def add_library_root(self, path):
        path = (path or "").strip()
        if not path or not os.path.isdir(path):
            return {"ok": False, "error": f"目录不存在: {path}"}
        roots = list(self._cfg.get("library_roots", []))
        if path not in roots:
            roots.append(path)
            self._cfg.set("library_roots", roots)
        return {"ok": True, "roots": roots}

    def remove_library_root(self, path):
        roots = [r for r in self._cfg.get("library_roots", []) if r != path]
        self._cfg.set("library_roots", roots)
        return {"ok": True, "roots": roots}

    def scan_library(self):
        global _scan_thread
        from . import enrich
        if enrich.STATE["running"]:
            return {"ok": False, "error": "已有任务在运行"}
        t = threading.Thread(target=enrich.scan_all, args=(self._cfg, self._db), daemon=True)
        _scan_thread = t
        t.start()
        return {"ok": True}

    def analyze_pending(self):
        global _analyze_thread
        from . import enrich
        if enrich.STATE["running"]:
            return {"ok": False, "error": "已有任务在运行"}
        t = threading.Thread(target=enrich.analyze_all, args=(self._cfg, self._db), daemon=True)
        _analyze_thread = t
        t.start()
        return {"ok": True}

    def get_scan_progress(self):
        from . import enrich
        return dict(enrich.STATE)

    def get_pending(self):
        rows = []
        for g in self._db.query("SELECT * FROM games WHERE status=1 ORDER BY id"):
            row = _game_row(g)
            row["candidates"] = self._candidates(g["id"])
            rows.append(row)
        return rows

    def confirm_match(self, game_id, provider, external_id):
        c = self._db.query_one(
            "SELECT * FROM match_candidates WHERE game_id=? AND provider=? AND external_id=?",
            (int(game_id), provider, external_id))
        if not c:
            return {"ok": False, "error": "候选不存在"}
        from . import enrich
        game = self._db.query_one("SELECT * FROM games WHERE id=?", (int(game_id),))
        cand = json.loads(c["payload"])
        cand["score"] = c["score"]
        cand["provider"] = c["provider"]
        cand["external_id"] = c["external_id"]
        enrich._apply_match(self._cfg, self._db, game, cand)
        return {"ok": True}

    def mark_unmatched(self, game_id):
        self._db.execute("UPDATE games SET status=3, source='manual' WHERE id=?", (int(game_id),))
        return {"ok": True}

    def reanalyze_game(self, game_id):
        from . import enrich
        gid = int(game_id)
        self._db.execute("UPDATE games SET status=0 WHERE id=?", (gid,))
        game = self._db.query_one("SELECT * FROM games WHERE id=?", (gid,))
        try:
            r = enrich._analyze_one(self._cfg, self._db, game)
            return {"ok": True, "result": r}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------- 启动 / 时长 ----------
    def launch_game(self, game_id):
        g = self._db.query_one("SELECT * FROM games WHERE id=?", (int(game_id),))
        if not g:
            return {"ok": False, "error": "游戏不存在"}
        return launcher.launch(self._db, g)

    def stop_game(self, game_id):
        return launcher.stop(int(game_id))

    def get_running(self):
        return launcher.running_ids()

    def set_locale_emu(self, game_id, enabled):
        self._db.execute("UPDATE games SET use_locale_emu=? WHERE id=?",
                         (1 if enabled else 0, int(game_id)))
        return {"ok": True}
