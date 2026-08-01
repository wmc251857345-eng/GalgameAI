# -*- coding: utf-8 -*-
"""端到端验证编辑链路: 模拟前端调用 JsApi 的每个编辑方法(用DB副本,不动真实数据)。"""
import os, sys, shutil, sqlite3, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 1. 复制真实 DB 到临时文件
tmp = os.path.join(os.environ.get("TEMP", "."), "gala_test_lib.db")
shutil.copyfile("database/library.db", tmp)

from backend.db import Database
from backend.config import Config
from backend.api import JsApi

db = Database(path=tmp)
db.init()
cfg = Config()
api = JsApi(db, cfg)

print("=== 0. 基线 ===")
g0 = db.query_one("SELECT id,title,maker,rating,status,source FROM games ORDER BY id LIMIT 1")
print("首个游戏:", g0)

gid = g0["id"]

print("\n=== 1. update_game(改标题/厂商/评分/简介/状态) ===")
r = api.update_game(gid, {
    "title": "测试标题XYZ", "maker": "测试厂商", "rating": 9.5,
    "released": "2020-01-01", "description": "测试简介内容", "length_minutes": 300,
    "exe_path": None,
})
print("返回:", {k: r[k] for k in ("ok",) } if isinstance(r, dict) else r, "| game keys:", list(r.get("game", {}).keys()) if isinstance(r, dict) else "")
g1 = db.query_one("SELECT id,title,maker,rating,released,description,length_minutes,status,source FROM games WHERE id=?", (gid,))
print("DB现在:", dict(g1))
assert g1["title"] == "测试标题XYZ" and g1["status"] == 2 and g1["source"] == "manual", "update_game 失败!"

print("\n=== 2. update_tags(手动标签) ===")
r = api.update_tags(gid, ["纯爱", "母系", "测试标签"])
print("返回 tags:", r.get("tags") if isinstance(r, dict) else r)
assert "纯爱" in r.get("tags", []), "update_tags 失败!"

print("\n=== 3. set_cover_url(从VNDB真实下载封面) ===")
r = api.set_cover_url(gid, "https://t.vndb.org/cv/30/85430.jpg")
print("返回:", r)
g2 = db.query_one("SELECT cover_path FROM games WHERE id=?", (gid,))
if g2 and g2["cover_path"]:
    full = os.path.join("G:/GalgameAI", g2["cover_path"].replace("/", "\\"))
    print("cover_path:", g2["cover_path"], "| 文件存在:", os.path.exists(full), "| 大小:", os.path.getsize(full) if os.path.exists(full) else 0)
    assert os.path.exists(full) and os.path.getsize(full) > 1000, "封面文件无效!"
else:
    print("cover_path 未设置! 下载失败")
    raise SystemExit("封面下载失败")

print("\n=== 4. remove_game(删除) ===")
# 新增一个垃圾游戏再删
garbage_id = db.execute("INSERT INTO games (title, status) VALUES (?,0)", ("__garbage__",))
r = api.remove_game(garbage_id)
gone = db.query_one("SELECT id FROM games WHERE id=?", (garbage_id,))
print("删除返回:", r, "| 行已删:", gone is None)
assert gone is None, "remove_game 失败!"

print("\n=== 5. 刷新链路: vndb.get + _apply_match (已入库游戏刷新) ===")
from backend.providers import vndb
from backend import enrich
cand, err = vndb.get(cfg, "v20424")
print("vndb.get:", "OK" if cand else f"FAIL {err}", "| title:", cand.get("title") if cand else None)
if cand:
    cand["score"] = 1.0
    enrich._apply_match(cfg, db, g0, cand)
    g3 = db.query_one("SELECT title,title_jp,maker,rating,length_minutes,cover_path,source,status FROM games WHERE id=?", (gid,))
    print("刷新后:", dict(g3))
    assert g3["cover_path"], "刷新未下载封面!"

print("\n=== ALL PASS ===")
os.remove(tmp)
