"""JsApi：pywebview 暴露给前端的方法（前端 window.pywebview.api.*）。
每个方法被 pywebview 在独立线程调用，DB/Config 自带锁，安全。"""
import platform
import sys

VERSION = "0.1.0"


class JsApi:
    def __init__(self, db, config):
        self._db = db
        self._config = config

    # ---- 基础 ----
    def ping(self):
        return "pong"

    def get_app_info(self):
        return {
            "name": "GALA",
            "version": VERSION,
            "python": sys.version.split()[0],
            "platform": platform.system(),
            "db_path": self._db.path,
        }

    # ---- 配置 ----
    def get_config(self):
        return self._config.as_dict()

    def set_config(self, key, value):
        self._config.set(key, value)
        return self._config.as_dict()

    # ---- 库（Phase 1 起填充真数据）----
    def get_library_summary(self):
        try:
            def one(sql):
                return self._db.query_one(sql)
            total = one("SELECT COUNT(*) c FROM games")["c"]
            pending = one("SELECT COUNT(*) c FROM games WHERE status=1")["c"]
            confirmed = one("SELECT COUNT(*) c FROM games WHERE status>=2")["c"]
            play = one("SELECT COALESCE(SUM(playtime_seconds),0) s FROM games")["s"]
            makers = one("SELECT COUNT(DISTINCT maker) c FROM games WHERE maker IS NOT NULL AND maker!=''")["c"]
            return {
                "total": total, "pending": pending, "confirmed": confirmed,
                "playtime_hours": round(play / 3600, 1), "makers": makers,
            }
        except Exception as e:  # 前端需要兜底而非崩溃
            return {"error": str(e)}

    def list_games(self, limit=200, offset=0, sort="title", query=""):
        allowed = {"title", "released", "rating", "playtime_seconds", "last_played"}
        order = sort if sort in allowed else "title"
        sql = "SELECT * FROM games"
        params = []
        if query:
            sql += " WHERE title LIKE ? OR title_en LIKE ? OR title_jp LIKE ? OR maker LIKE ?"
            params = [f"%{query}%"] * 4
        sql += f" ORDER BY {order} LIMIT ? OFFSET ?"
        params += [int(limit), int(offset)]
        return self._db.query(sql, params)

    def get_game(self, game_id):
        return self._db.query_one("SELECT * FROM games WHERE id=?", (int(game_id),))
