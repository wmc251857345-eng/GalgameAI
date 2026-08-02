"""JsApi：pywebview 暴露给前端的方法（window.pywebview.api.*）。
每个方法在 pywebview 独立线程调用，DB/Config 自带锁。
"""
import json
import logging
import os
import sqlite3
import threading
import time

from . import launcher, paths
from .utils import normalize, now_iso

VERSION = "0.2.0"
BASE_URL = "http://127.0.0.1:0"  # app.py 启动 HTTP 服务后写入

_scan_thread = None
_analyze_thread = None


def _cover_url(path):
    """绝对/相对路径 → http URL（前端可 <img> 直接加载）。"""
    if not path:
        return None
    p = str(path).replace("\\", "/")
    if p.startswith("http://") or p.startswith("https://"):
        return p
    if os.path.isabs(path):
        try:
            rel = os.path.relpath(path, paths.BASE).replace("\\", "/")
            # Use urllib.parse.quote to handle spaces in paths
            import urllib.parse
            return f"{BASE_URL}/{urllib.parse.quote(rel, safe=':/')}"
        except ValueError:
            return None
    import urllib.parse
    return f"{BASE_URL}/{urllib.parse.quote(p, safe=':/')}"


def _do_backup(db, out_dir):
    """执行备份：library.db（sqlite 在线备份）+ config.json。返回 out_dir。"""
    import shutil
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, "library.db")
    conn = db.connect()
    with db._lock:
        target = sqlite3.connect(dest)
        try:
            conn.backup(target)
        finally:
            target.close()
    try:
        shutil.copyfile(paths.CONFIG_FILE, os.path.join(out_dir, "config.json"))
    except OSError:
        pass
    return out_dir


def maybe_auto_backup(cfg, db):
    """启动时按间隔自动备份（database/backup/auto_*，保留最近 10 份）。"""
    if not cfg.get("backup.auto_enabled", True):
        return
    interval = max(1, int(cfg.get("backup.interval_days", 7)))
    last = db.query_one("SELECT value FROM settings WHERE key='last_backup'")
    now = time.time()
    if last and last.get("value"):
        try:
            if now - float(last["value"]) < interval * 86400:
                return
        except ValueError:
            pass
    try:
        ts = time.strftime("%Y%m%d_%H%M%S")
        _do_backup(db, os.path.join(paths.BASE, "database", "backup", "auto_" + ts))
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_backup', ?)",
                   (str(now),))
        auto_dirs = sorted(
            d for d in os.listdir(os.path.join(paths.BASE, "database", "backup"))
            if d.startswith("auto_"))
        for old in auto_dirs[:-10]:
            import shutil as _sh
            _sh.rmtree(os.path.join(paths.BASE, "database", "backup", old), ignore_errors=True)
        print(f"[GALA] 自动备份完成")
    except Exception as e:
        print(f"[GALA] 自动备份失败: {e}")


def _rating_disp(r):
    """VNDB 原始评分是 0-100 制，展示统一转 10 分制（<=20 视为已是 10 分制）。"""
    if isinstance(r, (int, float)) and r > 20:
        return round(r / 10, 1)
    return r


# exe 存在性 TTL 缓存：避免每次列库都对 HDD 反复 stat
_exe_cache = {}
_EXE_TTL = 30


def _exe_exists(path):
    if not path:
        return False
    hit = _exe_cache.get(path)
    now = time.time()
    if hit and now - hit[1] < _EXE_TTL:
        return hit[0]
    v = os.path.exists(path)
    _exe_cache[path] = (v, now)
    if len(_exe_cache) > 2000:
        _exe_cache.clear()
    return v


def _tags(db, game_id):
    return db.query(
        "SELECT t.name FROM tags t JOIN game_tags gt ON t.id=gt.tag_id"
        " WHERE gt.game_id=? ORDER BY gt.rowid", (game_id,))


def _game_row(g, db, with_extra=False):
    row = dict(g)
    # 封面：本地文件优先；没有本地文件但有远程 URL 时直接显示远程图
    row["cover_url"] = (_cover_url(g.get("cover_path"))
                        or (g.get("cover_url")
                            if str(g.get("cover_url") or "").startswith("http") else None))
    row["cover_orig_url"] = _cover_url(g.get("cover_orig_path"))  # 裁剪编辑器用原图
    row["rating_disp"] = _rating_disp(g.get("rating"))
    row["score"] = row["rating_disp"]            # 网格卡片 hover 用
    row["hue"] = (int(g["id"] or 0) * 47) % 360  # 无封面时占位渐变主色
    row["exe_exists"] = _exe_exists(g.get("exe_path"))
    row["playtime_hours"] = round((g.get("playtime_seconds") or 0) / 3600, 1)
    if with_extra:
        row["tags"] = [t["name"] for t in _tags(db, g["id"])]
    return row


# 厂商/系列档案 TTL 缓存（1 小时）
_maker_cache = {}
_series_cache = {}

# 新作推荐：后台抓取状态 + 结果
_NEW_STATE = {"running": False, "stage": "", "done": 0, "total": 0, "error": None}
_NEW_RELEASES = []
_new_lock = threading.Lock()

# 作品中文翻译任务（单槽）
_TRANSLATE_JOB = {"running": False, "vndb_id": None, "done": False, "error": None}

# 标签批量翻译任务（单槽）
_TAG_JOB = {"running": False, "pending": [], "done": 0, "error": None}

# 作品标题批量翻译任务（单槽）：{vndb_id: {title, title_jp}}
_WORK_JOB = {"running": False, "pending": {}, "done": 0, "error": None}

# 已放弃的翻译条目（LLM 反复译不出的标签/标题；进程内记忆，避免每次刷新档案都重复触发翻译任务
# → 前端 watch 循环刷新 → UI 卡死）。重启后清空，给一次重试机会。
_TAG_GAVE_UP = set()
_WORK_GAVE_UP = set()


class JsApi:
    def __init__(self, db, config):
        self._db = db
        self._cfg = config
        self._agent = None
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

    def get_stats(self):
        """统计页完整数据：总览 + 厂商 TOP + 标签云 + 年份分布 + 时长榜 + 数据源分布。"""
        def q(sql, *a):
            return self._db.query(sql, *a)
        def one(sql, *a):
            return self._db.query_one(sql, *a)

        # 总览
        overview = {
            "total": one("SELECT COUNT(*) c FROM games")["c"],
            "confirmed": one("SELECT COUNT(*) c FROM games WHERE status=2")["c"],
            "pending": one("SELECT COUNT(*) c FROM games WHERE status=1")["c"],
            "skipped": one("SELECT COUNT(*) c FROM games WHERE status=3")["c"],
            "favorites": one("SELECT COUNT(*) c FROM games WHERE favorite=1")["c"],
            "hanhua": one("SELECT COUNT(*) c FROM games WHERE hanhua=1")["c"],
            "playtime_hours": round(one("SELECT COALESCE(SUM(playtime_seconds),0) s FROM games")["s"] / 3600, 1),
            "played_count": one("SELECT COUNT(*) c FROM games WHERE playtime_seconds>0")["c"],
            "total_size_gb": round(one("SELECT COALESCE(SUM(size_bytes),0) s FROM games")["s"] / (1024**3), 1),
        }

        # 厂商 TOP（游戏数，近似名合并：Miel/Miel (ミエル)/miel → 一家；取前 12）
        import difflib
        mrows = q(
            "SELECT maker, COUNT(*) c, COALESCE(AVG(rating),0) avg_rating,"
            " COALESCE(SUM(playtime_seconds),0) pt FROM games"
            " WHERE maker IS NOT NULL AND maker!='' AND status IN (1,2)"
            " GROUP BY maker")
        mgroups = []  # [{"names": [...], "keys": [...], "count", "rating_sum", "pt"}]
        for r in mrows:
            key = self._maker_key(r["maker"])
            if not key:
                continue
            for g in mgroups:
                if any(difflib.SequenceMatcher(None, key, k).ratio() >= 0.8 for k in g["keys"]):
                    g["names"].append(r["maker"])
                    g["keys"].append(key)
                    g["count"] += r["c"]
                    g["rating_sum"] += (r["avg_rating"] or 0) * r["c"]
                    g["pt"] += r["pt"] or 0
                    break
            else:
                mgroups.append({
                    "names": [r["maker"]], "keys": [key], "count": r["c"],
                    "rating_sum": (r["avg_rating"] or 0) * r["c"], "pt": r["pt"] or 0,
                })
        makers = []
        for g in sorted(mgroups, key=lambda x: (-x["count"], x["names"][0]))[:12]:
            name_counts = {}
            for n in g["names"]:
                name_counts[n] = name_counts.get(n, 0) + 1
            makers.append({
                "name": max(name_counts, key=name_counts.get),
                "aliases": [n for n in g["names"] if n != max(name_counts, key=name_counts.get)][:3],
                "count": g["count"],
                "avg_rating": round(g["rating_sum"] / g["count"], 1) if g["count"] else 0,
                "playtime_hours": round(g["pt"] / 3600, 1),
            })

        # 标签云（前 20）
        tags = []
        for r in q(
                "SELECT t.name, COUNT(*) c FROM game_tags gt JOIN tags t ON t.id=gt.tag_id"
                " GROUP BY t.name ORDER BY c DESC, t.name LIMIT 20"):
            tags.append({"name": r["name"], "count": r["c"]})

        # 年份分布（前 12 年，含未知）
        years = []
        for r in q(
                "SELECT substr(released,1,4) y, COUNT(*) c FROM games"
                " WHERE status IN (1,2) GROUP BY y ORDER BY y DESC LIMIT 12"):
            years.append({"year": r["y"] or "未知", "count": r["c"]})

        # 时长榜（玩最多的前 10）
        top_played = []
        for r in q(
                "SELECT id, title, playtime_seconds, last_played FROM games"
                " WHERE playtime_seconds>0 ORDER BY playtime_seconds DESC LIMIT 10"):
            top_played.append({
                "id": r["id"], "title": r["title"],
                "hours": round((r["playtime_seconds"] or 0) / 3600, 1),
                "last_played": r["last_played"],
            })

        # 数据源分布
        sources = {}
        for r in q("SELECT source, COUNT(*) c FROM games GROUP BY source"):
            sources[r["source"] or "local"] = r["c"]

        return {
            "overview": overview,
            "makers": makers,
            "tags": tags,
            "years": years,
            "top_played": top_played,
            "sources": sources,
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
        rows = self._db.query(sql, params)
        # 一次性取所有标签并挂到对应游戏上（避免 N+1 查询）
        tag_map = {}
        for t in self._db.query(
                "SELECT gt.game_id, t.name FROM game_tags gt JOIN tags t ON t.id=gt.tag_id"
                " ORDER BY gt.rowid"):
            tag_map.setdefault(t["game_id"], []).append(t["name"])
        out = []
        for g in rows:
            row = _game_row(g, self._db)
            row["tags"] = tag_map.get(g["id"], [])
            out.append(row)
        return out

    def get_library_facets(self):
        """筛选维度：标签 / 厂商 / 年份（含计数，供前端 chips/下拉）。"""
        tags = self._db.query(
            "SELECT t.name, COUNT(*) c FROM tags t JOIN game_tags gt ON t.id=gt.tag_id"
            " GROUP BY t.id ORDER BY c DESC, t.name LIMIT 40")
        makers = self._db.query(
            "SELECT maker, COUNT(*) c FROM games WHERE maker IS NOT NULL AND maker != ''"
            " GROUP BY maker ORDER BY c DESC LIMIT 40")
        years = self._db.query(
            "SELECT substr(released,1,4) y, COUNT(*) c FROM games"
            " WHERE released IS NOT NULL AND released != ''"
            " GROUP BY y ORDER BY y DESC")
        return {"tags": tags, "makers": makers, "years": years}

    def toggle_favorite(self, game_id):
        gid = int(game_id)
        g = self._db.query_one("SELECT favorite FROM games WHERE id=?", (gid,))
        if not g:
            return {"ok": False, "error": "游戏不存在"}
        nv = 0 if g["favorite"] else 1
        self._db.execute("UPDATE games SET favorite=? WHERE id=?", (nv, gid))
        return {"ok": True, "favorite": nv}

    def get_game(self, game_id):
        g = self._db.query_one("SELECT * FROM games WHERE id=?", (int(game_id),))
        if not g:
            return None
        row = _game_row(g, self._db, with_extra=True)
        row["candidates"] = self._candidates(game_id)  # 详情页编辑封面时可从候选选图
        row["running"] = game_id in launcher.running_ids()
        return row

    def _tags(self, game_id):
        return _tags(self._db, game_id)

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
            row = _game_row(g, self._db)
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
        # AI 润色后台执行：确认操作不在桥接线程里同步等 LLM（避免卡死界面）
        enrich._apply_match(self._cfg, self._db, game, cand, async_enrich=True)
        # 写入匹配记忆：用户确认过 → 下次重扫同一文件夹直接命中
        fk = normalize(os.path.basename(game.get("path") or ""))
        if fk:
            self._db.execute(
                "INSERT OR REPLACE INTO match_cache"
                " (folder_key, vndb_id, provider, confidence, chosen_by_user, updated_at)"
                " VALUES (?,?,?,?,1,?)",
                (fk, external_id, provider, c["score"], now_iso()))
        return {"ok": True}

    def mark_unmatched(self, game_id):
        self._db.execute("UPDATE games SET status=3, source='manual' WHERE id=?", (int(game_id),))
        return {"ok": True}

    def cancel_task(self):
        """取消进行中的扫描/AI分析/补封面任务（下个循环点生效）。"""
        from . import enrich
        enrich.STATE["cancel_requested"] = True
        return {"ok": True}

    def test_connection(self):
        """连接自检：BGM 直连 / VNDB(有token) / LLM(有key)，逐项返回耗时。"""
        from .providers import bgm, llm, vndb
        res = {}

        t0 = time.time()
        try:
            cands = bgm.search(self._cfg, "summer pockets", limit=1)
            res["bgm"] = {"ok": len(cands) > 0, "ms": int((time.time() - t0) * 1000)}
        except Exception as e:
            res["bgm"] = {"ok": False, "ms": int((time.time() - t0) * 1000), "error": str(e)}

        if self._cfg.get("vndb_token"):
            t0 = time.time()
            try:
                cands, err = vndb.search(self._cfg, "summer pockets", limit=1)
                res["vndb"] = {"ok": len(cands) > 0, "ms": int((time.time() - t0) * 1000),
                               "error": err}
            except Exception as e:
                res["vndb"] = {"ok": False, "ms": int((time.time() - t0) * 1000), "error": str(e)}
        else:
            res["vndb"] = {"ok": None, "note": "未配置 VNDB token"}

        if self._cfg.get("provider.api_key"):
            t0 = time.time()
            try:
                resp, err = llm.chat(self._cfg,
                                     [{"role": "user", "content": "只回复: pong"}],
                                     json_mode=False, timeout=30)
                res["llm"] = {"ok": resp is not None, "ms": int((time.time() - t0) * 1000),
                              "model": self._cfg.get("provider.model"), "error": err}
            except Exception as e:
                res["llm"] = {"ok": False, "ms": int((time.time() - t0) * 1000), "error": str(e)}
        else:
            res["llm"] = {"ok": None, "note": "未配置 AI API Key"}

        t0 = time.time()
        try:
            from .providers import steam
            cands = steam.search(self._cfg, "summer pockets", limit=1)
            res["steam"] = {"ok": len(cands) > 0, "ms": int((time.time() - t0) * 1000)}
        except Exception as e:
            res["steam"] = {"ok": False, "ms": int((time.time() - t0) * 1000), "error": str(e)}

        return res

    # ---------- 失效路径 / 重定位 ----------
    def get_missing_paths(self):
        """返回 exe 或目录已失效的游戏列表（供重定位）。"""
        out = []
        for g in self._db.query("SELECT id, title, path, exe_path FROM games"):
            row = {"id": g["id"], "title": g["title"], "path": g["path"],
                   "exe_path": g["exe_path"]}
            row["path_exists"] = bool(g["path"]) and os.path.isdir(g["path"])
            row["exe_exists"] = _exe_exists(g["exe_path"])
            if not row["exe_exists"]:
                out.append(row)
        return out

    def relocate_game(self, game_id):
        """重新定位游戏目录：弹目录选择框 → 更新 path / exe / workdir。"""
        import webview
        gid = int(game_id)
        g = self._db.query_one("SELECT * FROM games WHERE id=?", (gid,))
        if not g:
            return {"ok": False, "error": "游戏不存在"}
        win = getattr(self, "_window", None)
        if not win:
            return {"ok": False, "error": "窗口未就绪"}
        try:
            result = win.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception as e:
            return {"ok": False, "error": f"目录选择失败: {e}"}
        if not result:
            return {"ok": False, "error": "未选择目录"}
        new_dir = os.path.abspath(result[0])
        exe = None
        if os.path.isdir(new_dir):
            exes = [f for f in os.listdir(new_dir) if f.lower().endswith(".exe")]
            if exes:
                from .scanner import guess_main_exe
                exe = os.path.join(new_dir, guess_main_exe(new_dir, os.path.basename(new_dir), exes))
        self._db.execute(
            "UPDATE games SET path=?, exe_path=?, workdir=?, source='manual' WHERE id=?",
            (new_dir, exe, new_dir, gid))
        return {"ok": True, "path": new_dir, "exe_path": exe}

    def reanalyze_game(self, game_id):
        """已入库(2)：从 VNDB 刷新 + AI 重新润色；未确认(0/1)：完整重新识别。
        改为后台任务执行（ONE_JOB），前端轮询 get_job_status，不阻塞桥接线程。"""
        from . import enrich
        gid = int(game_id)
        game = self._db.query_one("SELECT * FROM games WHERE id=?", (gid,))
        if not game:
            return {"ok": False, "error": "游戏不存在"}
        if enrich.ONE_JOB["running"]:
            return {"ok": False, "error": "已有分析任务在进行中"}
        t = threading.Thread(target=enrich._run_one_job,
                             args=(self._cfg, self._db, game), daemon=True)
        t.start()
        return {"ok": True, "started": True, "game_id": gid}

    def get_job_status(self):
        """单游戏后台任务状态（reanalyze 轮询用）。"""
        from . import enrich
        with enrich._lock:
            return dict(enrich.ONE_JOB)

    @staticmethod
    def _refresh_game(cfg, db, game):
        """已入库游戏刷新（被 reanalyze 后台任务调用）：
        - 有 vndb_id → VNDB 精确刷新；有 steam_id → Steam 精确刷新
        - 都没有（纯 AI 识别）→ 完整重新识别（AI 可能认错）
        """
        from . import enrich
        from .providers import steam, vndb
        if not game.get("vndb_id") and not game.get("steam_id"):
            db.execute("UPDATE games SET status=0 WHERE id=?", (game["id"],))
            return enrich._analyze_one(cfg, db, game)
        cand, err = (vndb.get(cfg, game["vndb_id"]) if game.get("vndb_id")
                     else steam.get(cfg, game["steam_id"]))
        if cand:
            cand["score"] = 1.0
            enrich._apply_match(cfg, db, game, cand)
            return {"status": 2, "refreshed_from": "vndb" if game.get("vndb_id") else "steam"}
        enrich._enrich_ai(cfg, db, game, {
            "title": game["title"], "title_orig": game.get("title_jp"),
            "maker": game.get("maker"), "released": game.get("released"),
            "summary": game.get("description"), "tags": [],
            "score": game.get("match_confidence") or 0.5})
        return {"status": 2, "refreshed_from": "ai"}

    # ---------- 手动编辑 ----------
    EDITABLE = {
        "title", "title_jp", "title_en", "title_zh", "maker", "brand",
        "released", "rating", "length_minutes", "length_level", "description",
        "exe_path", "workdir", "launch_args", "use_locale_emu", "hanhua", "status",
        "favorite", "vndb_id", "steam_id",
    }

    def update_game(self, game_id, fields):
        gid = int(game_id)
        game = self._db.query_one("SELECT * FROM games WHERE id=?", (gid,))
        if not game:
            return {"ok": False, "error": "游戏不存在"}
        clean = {}
        for k, v in (fields or {}).items():
            if k not in self.EDITABLE:
                continue
            if isinstance(v, str):
                v = v.strip()
                if v == "":
                    v = None
            if k == "hanhua":
                v = 1 if v else 0
            clean[k] = v
        if not clean:
            return {"ok": False, "error": "没有可更新的字段"}
        clean.setdefault("status", 2)  # 手动编辑即视为用户确认入库
        # 制作组名自动锚定：手动改名也统一到规范名（同一厂商不再出现多写法）
        if clean.get("maker"):
            from . import makers
            clean["maker"] = makers.canonical(self._db, clean["maker"])
        sets = ", ".join(f"{k}=?" for k in clean)
        params = list(clean.values()) + [gid]
        self._db.execute(f"UPDATE games SET {sets}, source='manual' WHERE id=?", params)
        # 用户手动指定/改了 vndb_id → 写入匹配记忆（下次重扫直接命中）
        if clean.get("vndb_id") and game.get("path"):
            fk = normalize(os.path.basename(game["path"]))
            if fk:
                self._db.execute(
                    "INSERT OR REPLACE INTO match_cache"
                    " (folder_key, vndb_id, provider, confidence, chosen_by_user, updated_at)"
                    " VALUES (?,?,?,?,1,?)",
                    (fk, clean["vndb_id"], "vndb", 1.0, now_iso()))
        return {"ok": True, "game": _game_row(self._db.query_one("SELECT * FROM games WHERE id=?", (gid,)), self._db)}

    def update_tags(self, game_id, tags):
        gid = int(game_id)
        self._db.execute("DELETE FROM game_tags WHERE game_id=?", (gid,))
        for t in (tags or []):
            t = str(t).strip()
            if not t:
                continue
            self._db.execute("INSERT OR IGNORE INTO tags (name, category) VALUES (?, 'manual')", (t,))
            row = self._db.query_one("SELECT id FROM tags WHERE name=?", (t,))
            if row:
                self._db.execute(
                    "INSERT OR IGNORE INTO game_tags (game_id, tag_id, source) VALUES (?,?,'manual')",
                    (gid, row["id"]))
        return {"ok": True, "tags": [t["name"] for t in self._tags(gid)]}

    def choose_cover(self, game_id):
        """弹系统文件对话框选本地图片作为封面。"""
        import shutil
        gid = int(game_id)
        game = self._db.query_one("SELECT * FROM games WHERE id=?", (gid,))
        if not game:
            return {"ok": False, "error": "游戏不存在"}
        win = getattr(self, "_window", None)
        if not win:
            return {"ok": False, "error": "窗口未就绪"}
        try:
            result = win.create_file_dialog(
                file_types=("图片文件 (*.jpg;*.jpeg;*.png;*.webp;*.bmp)",))
        except Exception as e:
            return {"ok": False, "error": f"文件对话框失败: {e}"}
        if not result:
            return {"ok": False, "error": "未选择文件"}
        src = result[0]
        ext = os.path.splitext(src)[1].lower() or ".jpg"
        dest = os.path.join(paths.COVERS_DIR, f"{gid}_manual{ext}")
        try:
            shutil.copyfile(src, dest)
        except OSError as e:
            return {"ok": False, "error": f"复制失败: {e}"}
        rel = os.path.relpath(dest, paths.BASE).replace("\\", "/")
        self._db.execute("UPDATE games SET cover_path=?, cover_url=NULL, source='manual' WHERE id=?", (rel, gid))
        return {"ok": True, "cover_url": _cover_url(rel)}

    def set_cover_url(self, game_id, url):
        """从 URL 下载封面（带具体错误信息 + 内容校验，避免"没反应"）。"""
        gid = int(game_id)
        url = (url or "").strip()
        if not url.startswith("http"):
            return {"ok": False, "error": "URL 无效"}
        from . import enrich
        from .utils import http_session
        dest = enrich._cover_dest(gid, url)
        os.makedirs(paths.COVERS_DIR, exist_ok=True)
        s = http_session(self._cfg, proxy_ok=True)
        try:
            r = s.get(url, timeout=30)
            if r.status_code != 200:
                return {"ok": False, "error": f"下载失败：HTTP {r.status_code}"}
            if not r.content or len(r.content) < 100:
                return {"ok": False, "error": "下载内容为空或非有效图片"}
            with open(dest, "wb") as f:
                f.write(r.content)
        except Exception as e:
            return {"ok": False, "error": f"下载失败：{str(e)[:100]}"}
        rel = os.path.relpath(dest, paths.BASE).replace("\\", "/")
        self._db.execute(
            "UPDATE games SET cover_path=?, cover_url=?, source='manual' WHERE id=?",
            (rel, url, gid))
        return {"ok": True, "cover_url": _cover_url(rel)}

    # ---------- 封面裁剪（自定义截取区域 + 重置自动适配） ----------
    @staticmethod
    def _cover_abs(p):
        """cover_path（相对 BASE 或绝对）→ 绝对路径；不存在返回 None。"""
        if not p:
            return None
        abs_p = os.path.join(paths.BASE, str(p).replace("/", os.sep)) if not os.path.isabs(p) else p
        return abs_p if os.path.exists(abs_p) else None

    def _ensure_cover_file(self, game):
        """确保有本地封面文件：cover_path 优先；只有远程 URL 时先下载。
        返回 (绝对路径, 是否新下载)。"""
        p = self._cover_abs(game.get("cover_path")) or self._cover_abs(game.get("cover_orig_path"))
        if p:
            return p, False
        url = (game.get("cover_url") or "").strip()
        if not url.startswith("http"):
            return None, False
        dest = os.path.join(paths.COVERS_DIR, f"{game['id']}_orig_src.jpg")
        from .utils import http_session
        try:
            s = http_session(self._cfg, proxy_ok=True)
            r = s.get(url, timeout=30)
            if r.status_code == 200 and len(r.content or b"") > 100:
                os.makedirs(paths.COVERS_DIR, exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(r.content)
                self._db.execute(
                    "UPDATE games SET cover_orig_path=?, cover_path=?, cover_url=? WHERE id=?",
                    (os.path.relpath(dest, paths.BASE).replace("\\", "/"),
                     os.path.relpath(dest, paths.BASE).replace("\\", "/"), None, game["id"]))
                return dest, True
        except Exception:
            pass
        return None, False

    def set_cover_crop(self, game_id, x, y, w, h):
        """按比例裁剪封面（x/y/w/h 均为原图 0~1 小数）：原图存 cover_orig_path，
        裁好的存 {id}_crop.jpg 并作为新 cover_path（所有视图统一生效）。
        w/h 可传 0 表示"自动适配"（清空手动裁剪）。"""
        gid = int(game_id)
        game = self._db.query_one("SELECT * FROM games WHERE id=?", (gid,))
        if not game:
            return {"ok": False, "error": "游戏不存在"}
        try:
            x, y, w, h = float(x or 0), float(y or 0), float(w or 0), float(h or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "裁剪参数无效"}
        if w <= 0 or h <= 0 or w > 1 or h > 1:
            return {"ok": False, "error": "裁剪区域无效"}
        src, _ = self._ensure_cover_file(game)
        if not src:
            return {"ok": False, "error": "没有可裁剪的封面（先选本地图片或下载封面）"}
        try:
            from PIL import Image
            img = Image.open(src)
            W, H = img.size
            if W < 4 or H < 4:
                return {"ok": False, "error": "图片尺寸过小，无法裁剪"}
            box = (round(x * W), round(y * H), round((x + w) * W), round((y + h) * H))
            # 边界夹紧 + 最小 8px 保护
            box = (max(0, box[0]), max(0, box[1]),
                   min(W, max(box[0] + 8, box[2])), min(H, max(box[1] + 8, box[3])))
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                return {"ok": False, "error": "裁剪区域过小"}
            crop = img.crop(box)
            if crop.mode in ("RGBA", "LA", "P"):
                crop = crop.convert("RGBA")
                bg = Image.new("RGB", crop.size, (255, 255, 255))
                bg.paste(crop, mask=crop.split()[-1])
                crop = bg
            elif crop.mode != "RGB":
                crop = crop.convert("RGB")
            os.makedirs(paths.COVERS_DIR, exist_ok=True)
            dest = os.path.join(paths.COVERS_DIR, f"{gid}_crop.jpg")
            crop.save(dest, "JPEG", quality=92)
        except Exception as e:
            return {"ok": False, "error": f"裁剪失败: {str(e)[:120]}"}
        rel = os.path.relpath(dest, paths.BASE).replace("\\", "/")
        # 首次裁剪：记下原图路径（用于重置/重新裁剪）
        orig = game.get("cover_orig_path") or game.get("cover_path") or rel
        if not game.get("cover_orig_path"):
            self._db.execute("UPDATE games SET cover_orig_path=? WHERE id=?", (orig, gid))
        self._db.execute(
            "UPDATE games SET cover_path=?, cover_url=NULL, source='manual' WHERE id=?",
            (rel, gid))
        return {"ok": True, "cover_url": _cover_url(rel)}

    def clear_cover_crop(self, game_id):
        """重置为自动适配：恢复裁剪前的原图（删掉手动裁剪文件）。"""
        gid = int(game_id)
        game = self._db.query_one("SELECT cover_path, cover_orig_path FROM games WHERE id=?",
                                  (gid,))
        if not game:
            return {"ok": False, "error": "游戏不存在"}
        orig = game.get("cover_orig_path")
        crop_p = self._cover_abs(game.get("cover_path"))
        if crop_p and os.path.basename(crop_p) == f"{gid}_crop.jpg":
            try:
                os.remove(crop_p)
            except OSError:
                pass
        if orig:
            self._db.execute(
                "UPDATE games SET cover_path=?, cover_orig_path=NULL, source='manual' WHERE id=?",
                (orig, gid))
            return {"ok": True, "cover_url": _cover_url(orig)}
        return {"ok": False, "error": "没有手动裁剪记录"}

    def remove_game(self, game_id):
        gid = int(game_id)
        g = self._db.query_one("SELECT cover_path FROM games WHERE id=?", (gid,))
        for t in ("match_candidates", "game_tags", "sessions", "staff",
                  "screenshots", "analysis_jobs"):
            self._db.execute(f"DELETE FROM {t} WHERE game_id=?", (gid,))
        self._db.execute("DELETE FROM games WHERE id=?", (gid,))
        # 删除该游戏的封面缓存文件（仅限 cache/covers 内）
        if g and g.get("cover_path"):
            p = os.path.join(paths.BASE, g["cover_path"].replace("/", os.sep))
            try:
                if os.path.dirname(p) == paths.COVERS_DIR and os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        return {"ok": True}

    # ---------- 手动导入 / AI 补全 ----------
    def search_candidates(self, keyword):
        """导入弹窗用：按关键词搜 VNDB + Bangumi 候选（标题/厂商/年份/封面/简介）。"""
        kw = (keyword or "").strip()
        if not kw:
            return {"ok": False, "error": "关键词为空"}
        from .enrich import _expand_keys
        from .providers import bgm, steam, vndb
        keys = []
        for v in _expand_keys(kw):
            if v and v not in keys:
                keys.append(v)
        out = []
        for k in keys[:5]:
            try:
                cands, verr = vndb.search(self._cfg, k, limit=4)  # 返回 (list, err)
                for c in cands or []:
                    out.append({"provider": "vndb", "external_id": c["external_id"],
                                "title": c.get("title"), "title_orig": c.get("title_orig"),
                                "maker": c.get("maker"), "released": c.get("released"),
                                "rating": c.get("rating"), "cover_url": c.get("cover_url"),
                                "summary": (c.get("summary") or "")[:200],
                                "tags": c.get("tags", [])[:8]})
            except Exception:
                pass
            try:
                for c in bgm.search(self._cfg, k, limit=4) or []:
                    out.append({"provider": "bgm", "external_id": c["external_id"],
                                "title": c.get("title"), "title_orig": c.get("title_orig"),
                                "maker": c.get("maker"), "released": c.get("released"),
                                "rating": c.get("rating"), "cover_url": c.get("cover_url"),
                                "summary": (c.get("summary") or "")[:200],
                                "tags": c.get("tags", [])[:8]})
            except Exception:
                pass
            try:
                for c in steam.search(self._cfg, k, limit=4) or []:
                    out.append({"provider": "steam", "external_id": c["external_id"],
                                "title": c.get("title"), "title_orig": c.get("title_orig"),
                                "maker": c.get("maker"), "released": c.get("released"),
                                "rating": c.get("rating"), "cover_url": c.get("cover_url"),
                                "summary": (c.get("summary") or "")[:200],
                                "tags": c.get("tags", [])[:8]})
            except Exception:
                pass
            if out:
                break  # 展开的第一个有结果的关键词即可（与管家搜索策略一致）
        seen, dedup = set(), []
        for c in out:
            key = (c["provider"], c["external_id"])
            if key not in seen:
                seen.add(key)
                dedup.append(c)
        return {"ok": True, "candidates": dedup[:12]}

    def add_game_manual(self, fields):
        """手动创建游戏条目（status=2 已入库）。title 必填；带 http cover_url 时后台下载封面。"""
        fields = fields or {}
        title = (fields.get("title") or "").strip()
        if not title:
            return {"ok": False, "error": "标题不能为空"}
        dup = self._db.query_one(
            "SELECT id, title FROM games WHERE title=? COLLATE NOCASE", (title,))
        if dup:
            return {"ok": False,
                    "error": f"库中已有《{dup['title']}》（id={dup['id']}），请勿重复导入，可直接在详情页修正"}
        rating = fields.get("rating")
        if isinstance(rating, (int, float)) and rating > 20:
            rating = round(rating / 10, 1)  # VNDB 0-100 → 10 分制
        now = now_iso()
        # 制作组名自动锚定（中/英/日文写法统一到规范名）
        from . import makers
        maker = makers.canonical(self._db, fields.get("maker") or "")
        gid = self._db.execute(
            """INSERT INTO games (title, title_jp, title_en, title_zh, maker, brand, released,
                                  rating, length_minutes, length_level, description,
                                  vndb_id, bgm_id, steam_id, path, exe_path, cover_url,
                                  status, source, added_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,2,'manual',?)""",
            (title, (fields.get("title_jp") or "").strip(),
             (fields.get("title_en") or "").strip(), (fields.get("title_zh") or "").strip(),
             maker, (fields.get("brand") or "").strip(),
             (fields.get("released") or "").strip(), rating,
             fields.get("length_minutes"), fields.get("length_level"),
             (fields.get("description") or "").strip()[:3000],
             (fields.get("vndb_id") or "").strip(),
             fields.get("bgm_id"), str(fields.get("steam_id") or "").strip(),
             (fields.get("path") or "").strip(),
             (fields.get("exe_path") or "").strip(),
             (fields.get("cover_url") or "").strip(), now))
        tags = [str(t).strip() for t in (fields.get("tags") or []) if str(t).strip()]
        if tags:
            for t in tags:
                self._db.execute(
                    "INSERT OR IGNORE INTO tags (name, category) VALUES (?, 'manual')", (t,))
                tid = self._db.query_one("SELECT id FROM tags WHERE name=?", (t,))["id"]
                self._db.execute(
                    "INSERT OR IGNORE INTO game_tags (game_id, tag_id, source) VALUES (?,?, 'manual')",
                    (gid, tid))
        url = (fields.get("cover_url") or "").strip()
        if url.startswith("http"):
            threading.Thread(target=self._download_cover_bg, args=(gid, url), daemon=True).start()
        return {"ok": True, "id": gid, "game": self.get_game(gid)}

    def _download_cover_bg(self, gid, url):
        """后台下载封面（不阻塞导入流程；失败静默，可之后手动补）。"""
        try:
            self.set_cover_url(gid, url)
        except Exception:
            pass

    # ---------- 本地导入：exe/文件夹 + 备注 → AI 提取 → 匹配 → 录入 ----------
    def pick_game_path(self, kind="exe"):
        """弹系统对话框选择本地游戏 exe 或文件夹（导入用）。"""
        import webview
        win = getattr(self, "_window", None)
        if not win:
            return {"ok": False, "error": "窗口未就绪"}
        try:
            if kind == "folder":
                result = win.create_file_dialog(webview.FOLDER_DIALOG)
            else:
                result = win.create_file_dialog(file_types=("程序 (*.exe)",))
        except Exception as e:
            return {"ok": False, "error": f"文件对话框失败: {e}"}
        if not result:
            return {"ok": False, "error": "未选择文件"}
        p = os.path.abspath(result[0])
        if kind == "exe":
            folder = os.path.dirname(p)
            title = os.path.basename(folder) or os.path.splitext(os.path.basename(p))[0]
        else:
            folder = p
            title = os.path.basename(p.rstrip("\\/"))
        return {"ok": True, "path": p, "folder": folder, "title": title}

    def _extract_game_info(self, folder_name, note, parent_dir=""):
        """LLM 从 文件夹名+上级目录(厂商线索)+备注 提取结构化信息（标题/厂商/年份/标签/简介）。"""
        from .providers import llm
        system = ("你是 Galgame 资料整理助手。根据用户提供的游戏文件夹名和简短备注，"
                  "提取结构化信息。只输出 JSON {\"title\":\"游戏名\",\"maker\":\"厂商（不知道就空字符串）\","
                  "\"year\":\"YYYY（不知道就空字符串）\",\"tags\":[\"类型标签，如 纯爱/拔作/悬疑\"],"
                  "\"description\":\"一句话中文简介\"}。title 优先用玩家常用名"
                  "（备注里提到的名字优先于文件夹名）。")
        user = f"文件夹名: {folder_name}\n备注: {note or '(无)'}"
        if parent_dir:
            # 两层目录结构 GalGame/厂商/作品名：上级目录通常是厂商，作为强线索
            user += f"\n上级目录名（通常是制作公司/品牌，请据此确认 maker）: {parent_dir}"
        try:
            result, err = llm.chat_json(self._cfg, system, user, timeout=45)
            if result:
                return {
                    "title": (result.get("title") or "").strip(),
                    "maker": (result.get("maker") or "").strip(),
                    "year": (result.get("year") or "").strip()[:4],
                    "tags": [str(t).strip() for t in (result.get("tags") or [])
                             if str(t).strip()][:8],
                    "description": (result.get("description") or "").strip()[:500],
                }
        except Exception:
            pass
        return {"title": "", "maker": "", "year": "", "tags": [], "description": ""}

    @staticmethod
    def _pick_best_candidate(cands, title, maker):
        """从候选里选最佳：标题精确 > 标题包含 > 厂商匹配 > 第一个。"""
        tl = (title or "").lower()
        ml = (maker or "").lower()
        for c in cands:
            if (c.get("title") or "").lower() == tl:
                return c
        for c in cands:
            if tl and tl in (c.get("title") or "").lower():
                return c
        if ml:
            for c in cands:
                if ml in str(c.get("maker") or "").lower():
                    return c
        return cands[0]

    def import_local_game(self, fields):
        """本地导入主流程：选好的 exe/文件夹 + 简短备注 →
        LLM 提取信息 → 搜外部候选 → 选最佳建条目 → 后台补全资料/封面/中文名。
        返回备选列表，前端可「换用」其他候选资料（reimport_game_source）。"""
        fields = fields or {}
        exe_path = (fields.get("exe_path") or "").strip()
        folder = (fields.get("folder") or "").strip()
        note = (fields.get("note") or "").strip()
        if not folder and exe_path:
            folder = os.path.dirname(exe_path)
        if not folder:
            return {"ok": False, "error": "请先选择游戏 exe 或文件夹"}
        if not os.path.isdir(folder):
            return {"ok": False, "error": f"目录不存在: {folder}"}
        folder_name = os.path.basename(folder.rstrip("\\/")) or folder
        # 两层目录结构 GalGame/厂商/作品名：上级目录名作厂商线索
        parent_dir = os.path.basename(os.path.dirname(folder.rstrip("\\/"))) or ""
        if parent_dir and os.path.normpath(os.path.dirname(folder.rstrip("\\/"))) == os.path.normpath(folder):
            parent_dir = ""
        # 1) AI 提取
        info = self._extract_game_info(folder_name, note, parent_dir)
        title = (info.get("title") or "").strip() or folder_name
        # 2) 搜候选
        cands = []
        try:
            r = self.search_candidates(title)
            cands = (r.get("candidates") or []) if r.get("ok") else []
        except Exception:
            cands = []
        # 3) 选最佳
        best = self._pick_best_candidate(cands, title, info.get("maker") or "") if cands else None
        # 4) 建条目（用户给的路径/信息优先，候选补齐其余）
        base = {
            "title": title, "maker": info.get("maker"), "released": info.get("year"),
            "tags": info.get("tags") or [], "description": info.get("description") or note,
            "path": folder, "exe_path": exe_path or None, "workdir": folder,
        }
        if best:
            merged = dict(best)
            merged.update({k: v for k, v in base.items() if v})  # 用户信息覆盖候选
            r2 = self.import_game_candidate(merged)
        else:
            r2 = self.add_game_manual(base)
        if not r2.get("ok"):
            return r2
        # 确保 path/exe/workdir 落库（候选导入路径也可能没带）
        if folder or exe_path:
            self._db.execute(
                "UPDATE games SET path=?, exe_path=?, workdir=? WHERE id=?",
                (folder or None, exe_path or None, folder or None, r2["id"]))
        alternates = [c for c in cands if c is not best][:5]
        return {"ok": True, "id": r2["id"], "title": title,
                "matched": (best or {}).get("title") or "",
                "provider": (best or {}).get("provider") or "manual",
                "alternates": alternates}

    def reimport_game_source(self, game_id, candidate):
        """导入后用备选候选的资料覆盖该条目（换来源/换资料）。"""
        gid = int(game_id)
        if not self._db.query_one("SELECT id FROM games WHERE id=?", (gid,)):
            return {"ok": False, "error": "游戏不存在"}
        cand = candidate or {}
        provider = (cand.get("provider") or "").lower()
        ext_id = str(cand.get("external_id") or cand.get("id") or "").strip()
        rating = cand.get("rating")
        if isinstance(rating, (int, float)) and rating > 20:
            rating = round(rating / 10, 1)
        upd = {"title": (cand.get("title") or "").strip()[:200],
               "title_jp": (cand.get("title_orig") or "").strip()[:200],
               "maker": (cand.get("maker") or "").strip()[:100],
               "released": (cand.get("released") or "").strip()[:10],
               "rating": rating,
               "description": (cand.get("summary") or "").strip()[:3000]}
        if provider == "vndb":
            upd["vndb_id"] = ext_id
        elif provider == "bgm":
            upd["bgm_id"] = ext_id
        elif provider == "steam":
            upd["steam_id"] = ext_id
        upd = {k: v for k, v in upd.items() if v is not None}
        # 制作组名自动锚定：换资料时也统一写法
        if upd.get("maker"):
            from . import makers
            upd["maker"] = makers.canonical(self._db, upd["maker"])
        if upd:
            set_sql = ", ".join(f"{k}=?" for k in upd)
            self._db.execute(f"UPDATE games SET {set_sql} WHERE id=?", (*upd.values(), gid))
        url = (cand.get("cover_url") or "").strip()
        if url.startswith("http"):
            threading.Thread(target=self._download_cover_bg, args=(gid, url), daemon=True).start()
        vndb_id = upd.get("vndb_id") or ""
        threading.Thread(target=self._enrich_imported, args=(gid, vndb_id), daemon=True).start()
        return {"ok": True, "id": gid}

    def import_game_candidate(self, candidate):
        """导入一个外部候选（VNDB/BGM 搜索结果）：建条目 → 后台拉全量资料 + AI 翻译中文名/简介。"""
        cand = candidate or {}
        provider = (cand.get("provider") or "").lower()
        ext_id = str(cand.get("external_id") or cand.get("id") or "").strip()
        title = (cand.get("title") or "").strip()
        if not title:
            return {"ok": False, "error": "候选缺少标题"}
        if ext_id:
            col = {"vndb": "vndb_id", "bgm": "bgm_id", "steam": "steam_id"}.get(provider)
            if col:
                dup = self._db.query_one(f"SELECT id, title FROM games WHERE {col}=?", (ext_id,))
                if dup:
                    return {"ok": False,
                            "error": f"库中已有《{dup['title']}》（id={dup['id']}），无需重复导入"}
        fields = {
            "title": title,
            "title_jp": cand.get("title_orig"),
            "maker": cand.get("maker"),
            "released": cand.get("released"),
            "rating": cand.get("rating"),
            "length_minutes": cand.get("length_minutes"),
            "length_level": cand.get("length_level"),
            "description": cand.get("summary"),
            "cover_url": cand.get("cover_url"),
            "tags": cand.get("tags"),
        }
        if provider == "vndb":
            fields["vndb_id"] = ext_id
        elif provider == "bgm":
            fields["bgm_id"] = ext_id
        elif provider == "steam":
            fields["steam_id"] = ext_id
        r = self.add_game_manual(fields)
        if r.get("ok"):
            # AI 补全：后台拉 VNDB 全量详情（更全简介/时长/别名）+ 中文标题/简介翻译
            threading.Thread(target=self._enrich_imported,
                             args=(r["id"], fields.get("vndb_id") or ""), daemon=True).start()
        return r

    def _enrich_imported(self, gid, vndb_id):
        """导入后补全：VNDB 全量详情 + AI 翻译中文名/简介，写入 games。"""
        try:
            from .providers import llm, vndb
            game = self._db.query_one("SELECT * FROM games WHERE id=?", (gid,))
            if not game:
                return
            cand, err = (vndb.get(self._cfg, vndb_id), None) if vndb_id else (None, None)
            upd = {}
            if cand:
                if cand.get("length_minutes") and not game.get("length_minutes"):
                    upd["length_minutes"] = cand["length_minutes"]
                if cand.get("length_level") and not game.get("length_level"):
                    upd["length_level"] = cand["length_level"]
                desc = (cand.get("description") or "").strip()[:3000]
                if len(desc) > len(game.get("description") or ""):
                    upd["description"] = desc
            if upd:
                set_sql = ", ".join(f"{k}=?" for k in upd)
                self._db.execute(f"UPDATE games SET {set_sql} WHERE id=?", (*upd.values(), gid))
            # AI 中文翻译：标题 + 简介
            if not (game.get("title_zh") or "").strip() and (game.get("title") or "").strip():
                system = ("你是 Galgame 中文本地化翻译。把作品标题翻译成简体中文（用玩家常用译名，"
                          "如 Summer Pockets→夏日口袋；没有通用译名就直译），简介翻译成通顺简体中文。"
                          "只输出 JSON {\"zh_title\":\"...\",\"zh_summary\":\"...\"}")
                user = f"标题: {game.get('title')}\n日文名: {game.get('title_jp') or ''}\n简介:\n{(game.get('description') or '')[:1200]}"
                result, terr = llm.chat_json(self._cfg, system, user, timeout=60)
                if result:
                    zh_t = (result.get("zh_title") or "").strip()[:200]
                    zh_s = (result.get("zh_summary") or "").strip()[:3000]
                    if zh_t:
                        self._db.execute("UPDATE games SET title_zh=? WHERE id=?", (zh_t, gid))
                    if zh_s:
                        self._db.execute("UPDATE games SET description=? WHERE id=?", (zh_s, gid))
        except Exception as e:
            logging.error("导入补全(%s) 失败: %s", gid, e)

    # ---------- 封面维护 ----------
    def refresh_cover(self, game_id):
        """单个游戏补封面：vndb_id 精确 → bgm_id 精确 → 标题链搜索（同批量逻辑）。"""
        from . import enrich
        gid = int(game_id)
        g = self._db.query_one("SELECT * FROM games WHERE id=?", (gid,))
        if not g:
            return {"ok": False, "error": "游戏不存在"}
        url = enrich._find_cover_url(self._cfg, g, self._db)
        if not url:
            return {"ok": False, "error": "没有可用封面来源（vndb/bgm 都搜不到封面）"}
        rel = enrich.download_cover(self._cfg, gid, url)
        if not rel:
            return {"ok": False, "error": "封面下载失败"}
        self._db.execute("UPDATE games SET cover_path=?, cover_url=? WHERE id=?",
                         (rel, url, gid))
        return {"ok": True, "cover_url": _cover_url(rel)}

    def fill_missing_covers(self):
        """后台线程：为所有已入库但缺封面的游戏批量补封面。"""
        global _scan_thread
        from . import enrich
        if enrich.STATE["running"]:
            return {"ok": False, "error": "已有任务在运行"}
        t = threading.Thread(target=enrich.fill_covers_all,
                             args=(self._cfg, self._db), daemon=True)
        _scan_thread = t
        t.start()
        return {"ok": True}

    # ---------- 导出 / 备份 ----------
    def export_games(self):
        """导出全部游戏（含标签）为 JSON 到 database/export/。"""
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.join(paths.BASE, "database", "export")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"games_{ts}.json")
        data = []
        for g in self._db.query("SELECT * FROM games ORDER BY id"):
            row = _game_row(g, self._db, with_extra=True)
            row.pop("cover_url", None)  # 含端口信息，导出时去掉
            data.append(row)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"ok": True, "path": out, "count": len(data)}

    def backup_db(self):
        """在线备份 library.db + config.json 到 database/backup/<时间戳>/。"""
        ts = time.strftime("%Y%m%d_%H%M%S")
        out = _do_backup(self._db, os.path.join(paths.BASE, "database", "backup", ts))
        return {"ok": True, "path": out}

    # ---------- 多提供商管理 ----------
    def list_providers(self):
        return {"active": self._cfg.get("provider", {}),
                "providers": self._cfg.get("providers", [])}

    def set_active_provider(self, name):
        """把池中的某个提供商设为当前活动提供商（后续调用优先用它）。"""
        provs = self._cfg.get("providers", [])
        p = next((x for x in provs if x.get("name") == name), None)
        if not p:
            return {"ok": False, "error": "提供商不存在"}
        active = {
            "name": p.get("name", ""), "model": p.get("model", ""),
            "api_key": p.get("api_key", ""), "base_url": p.get("base_url", ""),
            "vision": bool(p.get("vision")), "search": bool(p.get("search")),
        }
        self._cfg.set("provider", active)
        return {"ok": True, "provider": active}

    def test_provider(self, provider):
        """测试单个提供商连通性（直接请求，不修改配置）。"""
        from .providers import llm
        import time as _t
        t0 = _t.time()
        try:
            resp, err = llm.chat_provider(
                provider, [{"role": "user", "content": "只回复: pong"}],
                json_mode=False, timeout=25, cfg=self._cfg)
            return {"ok": resp is not None, "ms": int((_t.time() - t0) * 1000),
                    "error": str(err) if err else None}
        except Exception as e:
            return {"ok": False, "ms": int((_t.time() - t0) * 1000), "error": str(e)}

    # ---------- 厂商 / 系列追踪 ----------
    def _owned_vndb_set(self):
        return {r["vndb_id"]: r["id"] for r in self._db.query(
            "SELECT vndb_id, id FROM games WHERE vndb_id IS NOT NULL AND vndb_id!=''")}

    def _mark_owned(self, works):
        """给作品打 owned 标记 + 本地游戏 id 映射（点封面可跳回本地详情）。"""
        idmap = self._owned_vndb_set()
        for w in works:
            w["owned"] = w["id"] in idmap
            w["local_id"] = idmap.get(w["id"])

    def get_series_profile(self, series_id):
        """系列档案：以锚点 VN 收集同系列（relation='ser'）全部作品，含已拥有标记。"""
        from .providers import vndb
        import time as _t
        sid = (series_id or "").strip()
        if not sid:
            return {"ok": False, "error": "系列 ID 为空"}
        now = _t.time()
        hit = _series_cache.get(sid)
        if hit and now - hit[0] < 3600:
            return hit[1]
        works, name, werr = vndb.get_series(self._cfg, sid)
        if werr:
            return {"ok": False, "error": werr}
        self._mark_owned(works)
        self._apply_zh(works)
        result = {"ok": True, "series": {"id": sid, "name": name},
                  "works": works,
                  "owned_count": sum(1 for w in works if w["owned"]),
                  "total_count": len(works)}
        _series_cache[sid] = (now, result)
        return result

    # ---------- 厂商墙 / 新作推荐 / 作品详情 ----------
    @staticmethod
    def _maker_key(name):
        """厂商归一化键：假名→罗马音 + 小写去符号（Miel/ミエル/miel → 同一键），
        用于统计页/厂商墙的近似名合并。纯汉字名回退汉字键。"""
        from . import makers
        _, roma, hanzi = makers.keys_of(name)
        return roma or hanzi

    def get_makers_wall(self):
        """厂商墙：本地库聚合的厂商列表（本地游戏数 + 代表作封面），近似名自动合并。"""
        import difflib
        rows = self._db.query(
            "SELECT maker, COUNT(*) c FROM games"
            " WHERE maker IS NOT NULL AND maker!='' GROUP BY maker")
        groups = []  # [{"names": [...], "keys": [...]}]
        for r in rows:
            maker = r["maker"]
            key = self._maker_key(maker)
            if not key:
                continue
            for g in groups:
                if any(difflib.SequenceMatcher(None, key, k).ratio() >= 0.8 for k in g["keys"]):
                    g["names"].append(maker)
                    g["keys"].append(key)
                    g["count"] += r["c"]
                    break
            else:
                groups.append({"names": [maker], "keys": [key], "count": r["c"]})
        wall = []
        for g in groups:
            # 用出现最多的写法做展示名
            name_counts = {}
            for n in g["names"]:
                name_counts[n] = name_counts.get(n, 0) + 1
            display = max(name_counts, key=name_counts.get)
            names = g["names"]
            placeholders = ",".join("?" * len(names))
            games = self._db.query(
                f"SELECT id, title, cover_path FROM games WHERE maker IN ({placeholders})"
                " ORDER BY favorite DESC, playtime_seconds DESC LIMIT 6", names)
            covers = [x["cover_path"] for x in games if x["cover_path"]]
            wall.append({
                "maker": display,
                "local_count": g["count"],
                "covers": covers,
                "sample_title": games[0]["title"] if games else "",
            })
        wall.sort(key=lambda x: -x["local_count"])
        return {"ok": True, "makers": wall}

    def refresh_new_releases(self):
        """后台抓取所有本地厂商的新作（近 24 个月），完成后刷新 get_new_releases。"""
        global _NEW_RELEASES
        with _new_lock:
            if _NEW_STATE["running"]:
                return {"ok": True, "started": False, "running": True}
            _NEW_STATE.update(running=True, stage="准备", done=0,
                              total=0, error=None)
        threading.Thread(target=self._fetch_new_releases, daemon=True).start()
        return {"ok": True, "started": True}

    def _fetch_new_releases(self):
        from .providers import vndb
        global _NEW_RELEASES
        import datetime
        cutoff = (datetime.date.today() - datetime.timedelta(days=730)).isoformat()
        # 本地厂商 ∪ 关注厂商（关注的可带 vndb_id，直接精确拉取）
        maker_rows = self._db.query(
            "SELECT DISTINCT maker FROM games WHERE maker IS NOT NULL AND maker!=''")
        follow_rows = self._db.query(
            "SELECT maker_name, vndb_id FROM maker_follows WHERE maker_name!=''")
        targets = []
        for r in maker_rows:
            targets.append({"name": r["maker"], "vndb_id": ""})
        for r in follow_rows:
            if not any(t["name"] == r["maker_name"] for t in targets):
                targets.append({"name": r["maker_name"], "vndb_id": r.get("vndb_id") or ""})
        with _new_lock:
            _NEW_STATE.update(stage="查询厂商", total=len(targets))
        collected = {}
        for i, t in enumerate(targets):
            with _new_lock:
                _NEW_STATE.update(stage=t["name"], done=i + 1)
            try:
                if t["vndb_id"]:
                    prod = {"id": t["vndb_id"], "name": t["name"]}
                else:
                    prod, err = vndb.get_producer(self._cfg, t["name"])
                if not prod:
                    continue
                works, werr = vndb.get_producer_vns(self._cfg, prod["id"])
                for w in works:
                    if w.get("released") and w["released"] >= cutoff:
                        w["maker"] = t["name"]  # 标注所属厂商（新作卡片/角标用）
                        collected[w["id"]] = w
            except Exception:
                pass
            time.sleep(0.25)  # 节流
        owned = self._owned_vndb_set()
        lst = sorted(collected.values(),
                     key=lambda x: (x.get("released") or "", x.get("title") or ""),
                     reverse=True)[:40]
        for w in lst:
            w["owned"] = w["id"] in owned
            w["local_id"] = owned.get(w["id"])
            if w["local_id"]:
                g = self._db.query_one("SELECT title FROM games WHERE id=?", (w["local_id"],))
                if g:
                    w["local_title"] = g["title"]
        self._apply_zh(lst)
        with _new_lock:
            _NEW_RELEASES = lst
            _NEW_STATE.update(running=False, stage="完成", error=None)

    def get_new_releases(self):
        with _new_lock:
            state = dict(_NEW_STATE)
            items = list(_NEW_RELEASES)
        return {"ok": True, "state": state, "releases": items}

    def get_work_detail(self, vndb_id):
        """单作品详情：VNDB 全量字段 + 本地匹配 + 中文翻译缓存（vndb.get 带 6h TTL）。"""
        from .providers import vndb
        vid = (vndb_id or "").strip()
        if not vid:
            return {"ok": False, "error": "缺少作品 ID"}
        try:
            cand, err = vndb.get(self._cfg, vid)
        except Exception as e:
            logging.error("get_work_detail(%s) 异常: %s", vid, e)
            return {"ok": False, "error": f"VNDB 请求异常: {e}"}
        if err or not cand:
            return {"ok": False, "error": err or "VNDB 无此作品"}
        owned = self._owned_vndb_set()
        cand["owned"] = vid in owned
        cand["local_id"] = owned.get(vid)
        cand["local_title"] = None
        if cand["local_id"]:
            g = self._db.query_one("SELECT title FROM games WHERE id=?", (cand["local_id"],))
            if g:
                cand["local_title"] = g["title"]
        c = self._db.query_one(
            "SELECT zh_title, zh_summary FROM vndb_work_cache WHERE vndb_id=?", (vid,))
        if c:
            cand["zh_title"] = c["zh_title"]
            cand["zh_summary"] = c["zh_summary"]
        # 中文标签
        if cand.get("tags"):
            zh = self.zh_tags(cand["tags"])
            cand["tags_zh"] = [zh.get(t, t) for t in cand["tags"]]
            self.translate_tags_async(cand["tags"])
        return {"ok": True, "work": cand}

    def translate_work_async(self, vndb_id):
        """后台翻译作品标题+简介为中文（单槽任务，结果落 vndb_work_cache）。"""
        vid = (vndb_id or "").strip()
        if not vid:
            return {"ok": False, "error": "缺少作品 ID"}
        with _new_lock:
            if _TRANSLATE_JOB["running"] and _TRANSLATE_JOB["vndb_id"] == vid:
                return {"ok": True, "running": True}
        threading.Thread(target=self._run_translate, args=(vid,), daemon=True).start()
        return {"ok": True, "running": True}

    def _run_translate(self, vid):
        from .providers import llm, vndb
        with _new_lock:
            _TRANSLATE_JOB.update(running=True, vndb_id=vid, done=False, error=None)
        try:
            cand, err = vndb.get(self._cfg, vid)
            if not cand:
                raise RuntimeError(err or "无数据")
            system = ("你是 Galgame 中文本地化翻译。把作品标题翻译成简体中文（用玩家常用译名，"
                      "如 Summer Pockets→夏日口袋），简介翻译成通顺的简体中文，"
                      "只输出 JSON {\"zh_title\":\"...\",\"zh_summary\":\"...\"}")
            user = f"标题: {cand.get('title')}\n日文名: {cand.get('title_orig') or ''}\n简介:\n{(cand.get('summary') or '')[:1500]}"
            result, terr = llm.chat_json(self._cfg, system, user, timeout=60)
            if not result:
                raise RuntimeError(terr or "翻译失败")
            zh_title = (result.get("zh_title") or "").strip()[:200]
            zh_summary = (result.get("zh_summary") or "").strip()[:3000]
            if not zh_title and not zh_summary:
                raise RuntimeError("翻译结果为空")
            self._db.execute(
                "INSERT OR REPLACE INTO vndb_work_cache (vndb_id, zh_title, zh_summary, fetched_at)"
                " VALUES (?,?,?,?)", (vid, zh_title, zh_summary, now_iso()))
            with _new_lock:
                _TRANSLATE_JOB.update(done=True, error=None)
        except Exception as e:
            with _new_lock:
                _TRANSLATE_JOB.update(done=True, error=str(e)[:200])
        finally:
            with _new_lock:
                _TRANSLATE_JOB["running"] = False

    def get_translate_status(self):
        with _new_lock:
            return dict(_TRANSLATE_JOB)

    # ---------- 日志 ----------
    def log_error(self, message):
        """前端错误上报（JS 异常/超时等），写入 logs/app.log 便于排查卡死。"""
        msg = str(message or "")[:500]
        if msg:
            logging.error("[前端] %s", msg)
        return {"ok": True}

    def get_log_tail(self, lines=200):
        """返回 logs/app.log 尾部（UI 查看日志用）。"""
        lines = max(10, min(int(lines or 200), 1000))
        try:
            with open(os.path.join(paths.LOGS_DIR, "app.log"), "r", encoding="utf-8",
                      errors="replace") as f:
                tail = f.readlines()[-lines:]
            return {"ok": True, "log": "".join(tail)}
        except FileNotFoundError:
            return {"ok": True, "log": "（暂无日志文件）"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _apply_zh(self, works):
        """给作品实时应用最新中文标签 + 中文标题（后台翻译完成后刷新缓存命中）。"""
        ids = [w.get("id") for w in works if w.get("id")]
        if not ids:
            return
        all_tags = sorted({t for w in works for t in (w.get("tags") or [])})
        zh_tags = self.zh_tags(all_tags) if all_tags else {}
        zh_titles = self.zh_work_titles(ids)
        for w in works:
            if zh_tags:
                w["tags_zh"] = [zh_tags.get(t, t) for t in (w.get("tags") or [])]
            if zh_titles:
                w["zh_title"] = zh_titles.get(w["id"])
        # 触发未翻译的（标签 + 标题）批量翻译
        if all_tags:
            self.translate_tags_async(all_tags)
        self.translate_works_async(works)

    def get_maker_profile(self, maker):
        """厂商档案：介绍 + 全部作品（含已拥有标记）。匹配记忆 producer_map 优先，
        找不到/歧义时返回候选列表让用户更正。"""
        from .providers import vndb
        import time as _t
        key = (maker or "").strip()
        if not key:
            return {"ok": False, "error": "厂商名为空"}
        now = _t.time()
        hit = _maker_cache.get(key)
        if hit and now - hit[0] < 3600:
            result = hit[1]
            # 实时应用最新中文标签 + 中文标题（后台翻译可能刚完成）
            self._apply_zh(result.get("works", []))
            return result
        # 1) 记忆命中 → 直接用 vndb_id（显示名回退本地名，避免空/旧名误导）
        memo = self._db.query_one(
            "SELECT vndb_id, display_name FROM producer_map WHERE maker_name=?", (key,))
        prod = None
        if memo and memo["vndb_id"]:
            prod = {"id": memo["vndb_id"],
                    "name": (memo["display_name"] or "").strip() or key,
                    "aliases": [], "description": "", "type": ""}
        # 2) 否则展开搜索（智能匹配，不再粗暴整串丢进去）
        if not prod:
            prod, perr = vndb.get_producer(self._cfg, key)
            if perr:
                return {"ok": False, "error": perr}
            if prod:
                self._db.execute(
                    "INSERT OR REPLACE INTO producer_map (maker_name, vndb_id, display_name, updated_at)"
                    " VALUES (?,?,?,?)", (key, prod["id"], prod["name"], now_iso()))
        if not prod:
            return {"ok": False, "error": f"VNDB 没找到厂商「{key}」",
                    "not_found": True, "maker": key}
        # 把 VNDB 官方别名（常含中/英/日写法）登记进锚定表 → 之后任何写法都归一到同一厂商
        from . import makers
        makers.register_aliases(self._db, key, prod.get("aliases") or [], "vndb")
        works, werr = vndb.get_producer_vns(self._cfg, prod["id"])
        if werr:
            return {"ok": False, "error": werr}
        self._mark_owned(works)
        self._apply_zh(works)
        result = {"ok": True, "producer": prod, "works": works,
                  "mapped": bool(memo),
                  "owned_count": sum(1 for w in works if w["owned"]),
                  "total_count": len(works)}
        _maker_cache[key] = (now, result)
        return result

    def search_producers(self, keyword):
        """搜索 VNDB 厂商候选列表（用户手动更正用）。"""
        from .providers import vndb
        kw = (keyword or "").strip()
        if not kw:
            return {"ok": False, "error": "关键词为空"}
        cands, err = vndb.search_producers(self._cfg, kw)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "candidates": cands}
    def set_maker_mapping(self, maker_name, vndb_id, display_name=""):
        """用户手动指定 本地厂商名 → VNDB producer，写记忆表并清缓存。
        同时更新锚定表 makers/maker_aliases，让该写法成为规范名（或别名）。"""
        from . import makers
        maker = (maker_name or "").strip()
        vid = (vndb_id or "").strip()
        if not maker or not vid:
            return {"ok": False, "error": "参数不完整"}
        # 手动更正时显示名默认用本地厂商名（用户认知一致：更正成什么就显示什么），
        # 前端也可显式传 VNDB 官方名；空值一律回退本地名，避免空白显示。
        disp = (display_name or "").strip() or maker
        self._db.execute(
            "INSERT OR REPLACE INTO producer_map (maker_name, vndb_id, display_name, updated_at)"
            " VALUES (?,?,?,?)", (maker, vid, disp, now_iso()))
        # 锚定：把用户确认的写法登记为规范名/别名（下次任何来源写这个厂商都会归一到 disp）
        if disp and not makers.is_blank(disp):
            if makers.canonical(self._db, disp, vid) != disp:
                pass  # canonical 已存在同名 → 已统一
            _reg = self._db.query_one(
                "SELECT m.* FROM maker_aliases a JOIN makers m ON m.id=a.maker_id"
                " WHERE a.alias=?", (maker,))
            if _reg and _reg["name"] != disp:
                makers._rename(self._db, _reg["id"], disp)
        _maker_cache.pop(maker, None)
        _maker_cache.pop(disp, None)
        return {"ok": True, "display_name": disp, "vndb_id": vid}

    def list_makers(self):
        """全部规范厂商（合并 UI 用）：游戏数 + 别名 + vndb_id，按游戏数降序。"""
        from . import makers
        return {"ok": True, "makers": makers.list_makers(self._db)}

    def merge_makers(self, src, dst):
        """手动合并厂商：src 的所有游戏/关注/别名并入 dst（dst 不存在则新建）。
        返回合并后的规范名；前端随后刷新库列表/厂商墙。"""
        from . import makers
        ok, canon, err = makers.merge_makers(self._db, src, dst)
        if not ok:
            return {"ok": False, "error": err}
        _maker_cache.pop(src, None)
        _maker_cache.pop(canon, None)
        return {"ok": True, "canonical": canon}

    def translate_tags_async(self, tags):
        """批量翻译标签为中文（缺失的才译），结果落 tag_cache。单槽后台任务。"""
        tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        if not tags:
            return {"ok": False, "error": "没有可翻译的标签"}
        tags = [t for t in tags if t not in _TAG_GAVE_UP]  # 已放弃的跳过（防刷新死循环）
        if not tags:
            return {"ok": True, "translated": 0}
        have = {r["en_name"] for r in self._db.query(
            "SELECT en_name FROM tag_cache WHERE en_name IN (%s)" % ",".join("?" * len(tags)), tags)}
        missing = [t for t in tags if t not in have][:30]
        if not missing:
            return {"ok": True, "translated": 0}
        with _new_lock:
            if _TAG_JOB.get("running"):
                # 合并进正在进行的任务
                _TAG_JOB["pending"] = sorted(set(_TAG_JOB.get("pending", [])) | set(missing))
                return {"ok": True, "running": True}
            _TAG_JOB.update(running=True, pending=missing, done=0, error=None)
        threading.Thread(target=self._run_tag_translate, daemon=True).start()
        return {"ok": True, "running": True}

    def _run_tag_translate(self):
        from .providers import llm
        # 核心防御：pending 必须单调递减（尝试过的标签无论成败都移出，失败的限 2 次重试），
        # 轮数上限 + 节流——避免 LLM 持续失败时无限空转死循环打爆 API / 卡死 UI
        attempts = {}
        try:
            for _round in range(12):
                with _new_lock:
                    pending = list(_TAG_JOB.get("pending", []))
                if not pending:
                    break
                batch = pending[:20]
                system = ("你是 Galgame 标签中文本地化。把以下英文标签翻译成简体中文（游戏题材/剧情/玩法常用译名，"
                          "如 Romance→恋爱喜剧可简作恋爱）。严格输出 JSON {\"tags\":[{\"en\":\"原文\",\"zh\":\"中文\"},...]}，"
                          "en 必须与输入完全一致。")
                user = "\n".join(f"- {t}" for t in batch)
                result, terr = llm.chat_json(self._cfg, system, user, timeout=60)
                rows = []
                if result and isinstance(result.get("tags"), list):
                    for item in result["tags"]:
                        en = (item.get("en") or "").strip()
                        zh = (item.get("zh") or "").strip()
                        if en and zh:
                            rows.append((en, zh))
                ok_en = {r[0] for r in rows}
                if rows:
                    with _new_lock:
                        for en, zh in rows:
                            self._db.execute(
                                "INSERT OR REPLACE INTO tag_cache (en_name, zh_name) VALUES (?,?)",
                                (en, zh))
                        _TAG_JOB["done"] += len(rows)
                # 尝试过的移出 pending；失败的（LLM 没返回对应 en）最多再试 2 次
                still_missing = []
                for t in batch:
                    if t in ok_en:
                        continue
                    attempts[t] = attempts.get(t, 0) + 1
                    if attempts[t] < 2:
                        still_missing.append(t)
                    else:
                        _TAG_GAVE_UP.add(t)  # 反复失败 → 放弃，防下次刷新重复触发
                with _new_lock:
                    cur = set(_TAG_JOB.get("pending", []))
                    cur.difference_update(batch)
                    cur.update(still_missing)
                    _TAG_JOB["pending"] = sorted(cur)
                if not rows:
                    time.sleep(2)  # LLM 失败时放慢节奏，避免空转
        except Exception as e:
            with _new_lock:
                _TAG_JOB["error"] = str(e)[:200]
        finally:
            with _new_lock:
                _TAG_JOB["running"] = False
                _TAG_JOB["pending"] = []

    def get_tag_translate_status(self):
        with _new_lock:
            return dict(_TAG_JOB)

    # ---------- 作品标题批量翻译（中文名优先展示） ----------
    def translate_works_async(self, works):
        """批量翻译作品标题为中文（只译缺失的），落 vndb_work_cache.zh_title。
        works: [{id, title, title_jp}]；与标签任务同套防御：单调递减+重试限次+轮数上限。"""
        items = {}
        for w in works or []:
            vid = str(w.get("id") or "").strip()
            if vid and w.get("title") and vid not in _WORK_GAVE_UP:  # 已放弃的跳过
                items[vid] = {"title": w["title"], "title_jp": w.get("title_jp") or ""}
        if not items:
            return {"ok": True, "translated": 0}
        have = {r["vndb_id"] for r in self._db.query(
            "SELECT vndb_id FROM vndb_work_cache WHERE vndb_id IN (%s)"
            % ",".join("?" * len(items)), list(items))}
        missing = {k: v for k, v in items.items() if k not in have}
        if not missing:
            return {"ok": True, "translated": 0}
        with _new_lock:
            if _WORK_JOB.get("running"):
                _WORK_JOB["pending"].update(missing)
                return {"ok": True, "running": True}
            _WORK_JOB.update(running=True, pending=missing, done=0, error=None)
        threading.Thread(target=self._run_work_translate, daemon=True).start()
        return {"ok": True, "running": True}

    def _run_work_translate(self):
        from .providers import llm
        attempts = {}
        try:
            for _round in range(10):
                with _new_lock:
                    pending = dict(_WORK_JOB.get("pending", {}))
                if not pending:
                    break
                batch = dict(list(pending.items())[:12])
                lines = "\n".join(f"- id={vid}: {v['title']}" + (f"（{v['title_jp']}）" if v.get("title_jp") else "")
                                 for vid, v in batch.items())
                system = ("你是 Galgame 中文本地化翻译。把以下作品标题翻译成简体中文（用玩家常用译名，"
                          "如 Summer Pockets→夏日口袋；没有通用译名就直译）。严格输出 JSON "
                          "{\"works\":[{\"id\":\"原样id\",\"zh_title\":\"中文\"},...]}，id 必须与输入完全一致。")
                user = lines
                result, terr = llm.chat_json(self._cfg, system, user, timeout=60)
                got = {}
                if result and isinstance(result.get("works"), list):
                    for item in result["works"]:
                        vid = str(item.get("id") or "").strip()
                        zh = (item.get("zh_title") or "").strip()
                        if vid and zh:
                            got[vid] = zh
                if got:
                    with _new_lock:
                        for vid, zh in got.items():
                            self._db.execute(
                                "INSERT INTO vndb_work_cache (vndb_id, zh_title, fetched_at)"
                                " VALUES (?,?,?) ON CONFLICT(vndb_id) DO UPDATE SET zh_title=excluded.zh_title",
                                (vid, zh, now_iso()))
                        _WORK_JOB["done"] += len(got)
                # 单调递减：尝试过的移出；失败的限 2 次重试
                still = {}
                for vid, v in batch.items():
                    if vid in got:
                        continue
                    attempts[vid] = attempts.get(vid, 0) + 1
                    if attempts[vid] < 2:
                        still[vid] = v
                    else:
                        _WORK_GAVE_UP.add(vid)  # 反复失败 → 放弃，防刷新死循环
                with _new_lock:
                    cur = dict(_WORK_JOB.get("pending", {}))
                    for vid in batch:
                        cur.pop(vid, None)
                    cur.update(still)
                    _WORK_JOB["pending"] = cur
                if not got:
                    time.sleep(2)
        except Exception as e:
            with _new_lock:
                _WORK_JOB["error"] = str(e)[:200]
        finally:
            with _new_lock:
                _WORK_JOB["running"] = False
                _WORK_JOB["pending"] = {}

    def get_work_translate_status(self):
        with _new_lock:
            return dict(_WORK_JOB)

    def zh_work_titles(self, vndb_ids):
        """批量查作品中文标题缓存。返回 {vndb_id: zh_title}。"""
        ids = [str(i) for i in (vndb_ids or []) if i]
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        rows = self._db.query(
            f"SELECT vndb_id, zh_title FROM vndb_work_cache WHERE vndb_id IN ({placeholders})", ids)
        return {r["vndb_id"]: r["zh_title"] for r in rows if r["zh_title"]}

    def zh_tags(self, tags):
        """把英文标签列表映射为中文（查缓存，未命中的返回原文）。"""
        if not tags:
            return {}
        placeholders = ",".join("?" * len(tags))
        rows = self._db.query(
            f"SELECT en_name, zh_name FROM tag_cache WHERE en_name IN ({placeholders})", tags)
        m = {r["en_name"]: r["zh_name"] for r in rows}
        return {t: m.get(t, t) for t in tags}

    # ---------- 关注厂商 ----------
    def follow_maker(self, maker_name, vndb_id="", display_name=""):
        name = (maker_name or "").strip()
        if not name:
            return {"ok": False, "error": "厂商名为空"}
        if vndb_id:
            self._db.execute(
                "INSERT OR REPLACE INTO maker_follows (maker_name, vndb_id, display_name, created_at)"
                " VALUES (?,?,?,?)", (name, vndb_id, display_name or name, now_iso()))
        else:
            self._db.execute(
                "INSERT OR IGNORE INTO maker_follows (maker_name, vndb_id, display_name, created_at)"
                " VALUES (?,?,?,?)", (name, "", display_name or name, now_iso()))
        return {"ok": True}

    def unfollow_maker(self, maker_name):
        self._db.execute("DELETE FROM maker_follows WHERE maker_name=?", ((maker_name or "").strip(),))
        return {"ok": True}

    def list_follows(self):
        rows = self._db.query("SELECT * FROM maker_follows ORDER BY created_at DESC")
        return {"ok": True, "follows": rows}

    # ---------- AI 管家对话 ----------
    def chat_send(self, message, context_game_id=None):
        """发送一条消息给 AI 管家（工具调用式），返回回复+动作记录。"""
        message = (message or "").strip()
        if not message:
            return {"ok": False, "error": "消息为空"}
        if self._agent is None:
            from .agent import AgentService
            self._agent = AgentService(self._db, self._cfg)
        self._db.execute(
            "INSERT INTO chat_messages (role, content, created_at) VALUES ('user',?,?)",
            (message, now_iso()))
        history = [{"role": r["role"], "content": r["content"]} for r in self._db.query(
            "SELECT role, content FROM chat_messages ORDER BY id DESC LIMIT 12")][::-1]
        result = self._agent.chat(message, context_game_id=context_game_id, history=history)
        reply = (result.get("reply") or "").strip()
        self._db.execute(
            "INSERT INTO chat_messages (role, content, created_at) VALUES ('assistant',?,?)",
            (reply or "(空回复)", now_iso()))
        return {"ok": True, "reply": reply, "actions": result.get("actions", [])}

    def chat_history(self, limit=30):
        rows = self._db.query(
            "SELECT role, content, created_at FROM chat_messages ORDER BY id DESC LIMIT ?",
            (int(limit),))
        return list(reversed(rows))

    def chat_clear(self):
        self._db.execute("DELETE FROM chat_messages")
        return {"ok": True}

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
