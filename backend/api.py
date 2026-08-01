"""JsApi：pywebview 暴露给前端的方法（window.pywebview.api.*）。
每个方法在 pywebview 独立线程调用，DB/Config 自带锁。
"""
import json
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
    if p.startswith("http"):
        return p
    if os.path.isabs(path):
        try:
            rel = os.path.relpath(path, paths.BASE).replace("\\", "/")
            return f"{BASE_URL}/{rel}"
        except ValueError:
            return None
    return f"{BASE_URL}/{p}"


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
        - 有 vndb_id → VNDB 精确刷新（封面/评分/时长/简介）+ AI 润色
        - 无 vndb_id（纯 AI 识别）→ 完整重新识别（AI 可能认错）
        """
        from . import enrich
        from .providers import vndb
        if not game.get("vndb_id"):
            db.execute("UPDATE games SET status=0 WHERE id=?", (game["id"],))
            return enrich._analyze_one(cfg, db, game)
        cand, _ = vndb.get(cfg, game["vndb_id"])
        if cand:
            cand["score"] = 1.0
            enrich._apply_match(cfg, db, game, cand)
            return {"status": 2, "refreshed_from": "vndb"}
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
        "favorite", "vndb_id",
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
                file_types=("图片文件", "*.jpg;*.jpeg;*.png;*.webp;*.bmp"))
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
        """从 URL 下载封面。"""
        gid = int(game_id)
        url = (url or "").strip()
        if not url.startswith("http"):
            return {"ok": False, "error": "URL 无效"}
        from . import enrich
        rel = enrich.download_cover(self._cfg, gid, url)
        if not rel:
            return {"ok": False, "error": "下载失败"}
        self._db.execute("UPDATE games SET cover_path=?, cover_url=?, source='manual' WHERE id=?", (rel, url, gid))
        return {"ok": True, "cover_url": _cover_url(rel)}

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

    def get_maker_profile(self, maker):
        """厂商档案：介绍 + 全部作品（含已拥有标记）+ 系列归类。1 小时 TTL 缓存。"""
        from .providers import vndb
        import time as _t
        key = (maker or "").strip()
        if not key:
            return {"ok": False, "error": "厂商名为空"}
        now = _t.time()
        hit = _maker_cache.get(key)
        if hit and now - hit[0] < 3600:
            return hit[1]
        prod, err = vndb.get_producer(self._cfg, key)
        if err:
            return {"ok": False, "error": err}
        if not prod:
            return {"ok": False, "error": f"VNDB 没找到厂商「{key}」"}
        works, werr = vndb.get_producer_vns(self._cfg, prod["id"])
        if werr:
            return {"ok": False, "error": werr}
        owned = self._owned_vndb_set()
        for w in works:
            w["owned"] = w["id"] in owned
            w["local_id"] = owned.get(w["id"])
        result = {"ok": True, "producer": prod, "works": works,
                  "owned_count": sum(1 for w in works if w["owned"]),
                  "total_count": len(works)}
        _maker_cache[key] = (now, result)
        return result

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
        owned = self._owned_vndb_set()
        for w in works:
            w["owned"] = w["id"] in owned
            w["local_id"] = owned.get(w["id"])
        result = {"ok": True, "series": {"id": sid, "name": name},
                  "works": works,
                  "owned_count": sum(1 for w in works if w["owned"]),
                  "total_count": len(works)}
        _series_cache[sid] = (now, result)
        return result

    # ---------- 厂商墙 / 新作推荐 / 作品详情 ----------
    @staticmethod
    def _maker_key(name):
        """厂商归一化键：小写 + 去括号后缀（Miel (ミエル) → miel），用于合并同名异写。"""
        import re
        s = re.sub(r"[（(].*?[)）]", "", name).lower()
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", s)

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
        makers = [r["maker"] for r in self._db.query(
            "SELECT DISTINCT maker FROM games WHERE maker IS NOT NULL AND maker!=''")]
        with _new_lock:
            _NEW_STATE.update(stage="查询厂商", total=len(makers))
        collected = {}
        for i, mk in enumerate(makers):
            with _new_lock:
                _NEW_STATE.update(stage=mk, done=i + 1)
            try:
                prod, err = vndb.get_producer(self._cfg, mk)
                if not prod:
                    continue
                works, werr = vndb.get_producer_vns(self._cfg, prod["id"])
                for w in works:
                    if w.get("released") and w["released"] >= cutoff:
                        collected[w["id"]] = w
            except Exception:
                pass
            time.sleep(0.25)  # 节流
        owned = self._owned_vndb_set()
        lst = sorted(collected.values(), key=lambda x: x.get("released") or "", reverse=True)[:40]
        for w in lst:
            w["owned"] = w["id"] in owned
            w["local_id"] = owned.get(w["id"])
            if w["local_id"]:
                g = self._db.query_one("SELECT title FROM games WHERE id=?", (w["local_id"],))
                if g:
                    w["local_title"] = g["title"]
        with _new_lock:
            _NEW_RELEASES = lst
            _NEW_STATE.update(running=False, stage="完成", error=None)

    def get_new_releases(self):
        with _new_lock:
            state = dict(_NEW_STATE)
            items = list(_NEW_RELEASES)
        return {"ok": True, "state": state, "releases": items}

    def get_work_detail(self, vndb_id):
        """单作品详情：VNDB 全量字段 + 本地匹配 + 中文翻译缓存。"""
        from .providers import vndb
        vid = (vndb_id or "").strip()
        if not vid:
            return {"ok": False, "error": "缺少作品 ID"}
        cand, err = vndb.get(self._cfg, vid)
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
