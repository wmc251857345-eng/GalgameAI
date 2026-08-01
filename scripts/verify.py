# -*- coding: utf-8 -*-
"""GALA 规范验证脚本（canonical verify）。

覆盖：无损迁移幂等 / 库体验(facets·收藏·list_games字段) / bgm.search 修复 /
智能记忆(match_cache 写入+命中) / 稳定性(launcher 结算·reconcile·取消·测试连接·失效路径) /
前端构建新鲜度。

用法（项目根目录）:
  venv\\Scripts\\python.exe scripts/verify.py

写操作全部走 DB 副本，真实库只读；网络测试为真实请求。
"""
import os
import shutil
import subprocess
import sys
import tempfile

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(detail)) if detail else ""))
    if not cond:
        fails.append(name)


# ---------- 1. 导入 & 迁移幂等 ----------
from backend import api as api_mod  # noqa: E402
from backend import enrich, launcher  # noqa: E402
from backend.config import Config  # noqa: E402
from backend.db import Database  # noqa: E402
from backend.providers import bgm  # noqa: E402
from backend.utils import normalize  # noqa: E402
check("all backend imports", True)

tmp = os.path.join(tempfile.gettempdir(), "gala_verify_lib.db")
shutil.copyfile(os.path.join(PROJ, "database", "library.db"), tmp)
dbx = Database(path=tmp)
dbx.init()
dbx.init()  # 幂等：跑两次不报错
n = dbx.query_one("SELECT COUNT(*) c FROM games")["c"]
cols = {r["name"] for r in dbx.query("PRAGMA table_info(games)")}
mcols = {r["name"] for r in dbx.query("PRAGMA table_info(match_cache)")}
check("migration idempotent + data kept", n >= 40 and "favorite" in cols and "provider" in mcols,
      f"{n} games")

cfg = Config()
db = Database()
db.init()
js = api_mod.JsApi(db, cfg)

# ---------- 2. 库体验 ----------
f = js.get_library_facets()
check("facets", isinstance(f, dict) and len(f.get("makers", [])) > 0
      and len(f.get("years", [])) > 0, {k: len(v) for k, v in f.items()})

games = js.list_games()
check("list_games fields", bool(games) and all(
    "tags" in g and "exe_exists" in g and "favorite" in g and "hue" in g for g in games[:5]))

js2 = api_mod.JsApi(dbx, cfg)
r = js2.toggle_favorite(1)
g1 = dbx.query_one("SELECT favorite FROM games WHERE id=1")
check("toggle_favorite", r.get("ok") and g1["favorite"] == 1, dict(g1))
js2.toggle_favorite(1)  # 还原副本

# ---------- 3. bgm.search 修复（BGM 返回 {"results":N,"list":[...]} 字典） ----------
r = bgm.search(cfg, "summer pockets", limit=2)
check("bgm.search dict-wrapper fix", len(r) > 0 and bool(r[0].get("cover_url")),
      (r[0]["title"] if r else None))

# ---------- 4. 智能记忆：写入 + 命中 ----------
g2 = dbx.query_one("SELECT * FROM games WHERE id=2")
fk = normalize(os.path.basename(g2["path"]))
js2.update_game(2, {"vndb_id": "v20424"})
mc = dbx.query_one("SELECT * FROM match_cache WHERE folder_key=?", (fk,))
check("update_game writes match_cache", bool(mc and mc["vndb_id"] == "v20424"),
      dict(mc) if mc else None)

sid = dbx.execute("INSERT INTO games (path, title, status) VALUES (?,?,0)",
                  (g2["path"], "__cache_test__"))
res = enrich._analyze_one(cfg, dbx, dbx.query_one("SELECT * FROM games WHERE id=?", (sid,)))
check("analyze_one cache hit skips AI",
      res.get("from_cache") is True and res.get("status") == 2, res)
dbx.execute("DELETE FROM games WHERE id=?", (sid,))

# ---------- 5. 稳定性 ----------
sess_id = dbx.execute(
    "INSERT INTO sessions (game_id, started_at, ended_at, seconds) VALUES (?,?,NULL,0)",
    (2, "2026-08-01 10:00:00"))
launcher._finalize(dbx, 2, sess_id, "2026-08-01 10:00:00",
                   ended="2026-08-01 10:30:00", seconds=1800)
s = dbx.query_one("SELECT ended_at, seconds FROM sessions WHERE id=?", (sess_id,))
check("launcher finalize", s["ended_at"] == "2026-08-01 10:30:00" and s["seconds"] == 1800, dict(s))
launcher.reconcile(dbx)  # 无孤儿 session 时 no-op
check("reconcile no-op safe", True)

r = js2.cancel_task()
check("cancel_task flag", r.get("ok") and enrich.STATE.get("cancel_requested") is True)
enrich.STATE["cancel_requested"] = False

mp = js.get_missing_paths()
check("missing_paths shape", isinstance(mp, list) and all(
    "path_exists" in x and "exe_exists" in x for x in mp), f"{len(mp)} 条")

# ---------- 6. 异步重分析任务（防卡死核心修复） ----------
import time as _t
js2.update_game(2, {"vndb_id": "v20424"})
_t0 = _t.time()
r = js2.reanalyze_game(2)
check("reanalyze non-blocking", r.get("started") and _t.time() - _t0 < 3,
      f"{_t.time() - _t0:.1f}s")
st = None
deadline = _t.time() + 90
while _t.time() < deadline:
    st = js2.get_job_status()
    if not st.get("running"):
        break
    _t.sleep(1)
check("reanalyze job completes",
      bool(st and st.get("result") and st["result"].get("status") == 2), st)

t = js.test_connection()
check("test bgm", t.get("bgm", {}).get("ok") is True, t.get("bgm"))
check("test vndb", t.get("vndb", {}).get("ok") is True, t.get("vndb"))
check("test llm", t.get("llm", {}).get("ok") is True, str(t.get("llm"))[:80])

dbx.close()
os.remove(tmp)

# ---------- 6. 前端构建新鲜度 ----------
src_new = max(os.path.getmtime(os.path.join(r_, f_))
              for r_, _d, fs in os.walk(os.path.join(PROJ, "frontend", "src"))
              for f_ in fs)
dist_old = os.path.getmtime(os.path.join(PROJ, "frontend", "dist", "index.html"))
check("dist newer than sources", dist_old >= src_new, f"dist {dist_old:.0f} src {src_new:.0f}")

print("\n" + ("ALL PASS" if not fails else "FAILED: " + ", ".join(fails)))
sys.exit(0 if not fails else 1)
