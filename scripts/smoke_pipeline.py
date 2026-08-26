"""冒烟测试: 三方互证流水线 + 扫描历史 + 自动整理引擎 (sandbox, 不碰真实文件/真实库)

1) 整理计划 build_plan: 对真实 D:\\Games_HDD\\GalGame 目录做只读 dry-run,
   验证"学习用户习惯"的桶映射 (Atelier_Kaguya 品牌家族桶) 与预期移动项。
2) apply_plan: 在临时目录 + 沙箱 DB 上真实执行移动, 验证 DB 路径同步 + 历史记录。
3) 三方对账决策逻辑: mock provider 验证 AI 孤证不自动入库 / AI+DB 印证入库。
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

from backend import organizer
from backend.config import Config
from backend.db import Database

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILS.append(name)


# ---------- 1) 整理计划 (只读 dry-run, 真实目录) ----------
print("\n=== 1. build_plan dry-run (真实目录只读) ===")
cfg = Config()
REAL_ROOT = r"D:\Games_HDD\GalGame"
sandbox_db = os.path.join(tempfile.mkdtemp(prefix="gala_smoke_"), "sandbox.db")
shutil.copy2(os.path.join(PROJ, "database", "library.db"), sandbox_db)
db = Database(sandbox_db)
db.init()

if os.path.isdir(REAL_ROOT) and os.path.isdir(
        os.path.join(REAL_ROOT, "SummerClover")):
    # 仅在原始开发机数据集上运行数据绑定断言（预期移动项与那台机器的库一一对应）
    cfg.set("library_roots", [REAL_ROOT])
    plan = organizer.build_plan(cfg, db)
    items = plan["items"]
    print(f"计划项数: {plan.get('total')}")
    for it in items:
        print(f"  [{it['maker'] or '?'}] {it['title']:<28} {it['reason']:<12} {it['from']}  →  {it['to']}")

    by_from = {it["from"]: it for it in items}
    exp = [
        (r"D:\Games_HDD\GalGame\SummerClover", "Connection"),
        (r"D:\Games_HDD\GalGame\与恶魔三姐妹的认真对决", "Whisp"),
        (r"D:\Games_HDD\GalGame\【PC】Love×Holic魅惑少女与白液之奏", "Atelier_Kaguya"),
        (r"D:\Games_HDD\GalGame\【PC】Hakoniwa\Hakoniwa -ハコニワ-", "Atelier_Kaguya"),
        (r"D:\Games_HDD\GalGame\【PC】Pure×Holic纯洁少女与婚姻关系\Pure×Holic ～純潔乙女と婚姻カンケイ！？～", "Atelier_Kaguya"),
        (r"D:\Games_HDD\GalGame\おっぱいスパイ学園\おっぱいスパイ学園", "Uncategorized"),
        (r"D:\Games_HDD\GalGame\Independent_RPG_SLG\后宫绮梦\后宫绮梦", "后宫绮梦"),       # 平铺
        (r"D:\Games_HDD\GalGame\Independent_RPG_SLG\风流公子\1", "风流公子"),           # 平铺
        (r"D:\Games_HDD\GalGame\Uncategorized\Arisa\1", "Arisa"),                     # 平铺
    ]
    for from_path, expect_segment in exp:
        it = by_from.get(from_path)
        check(f"计划含: {os.path.basename(from_path)}", it is not None)
        if it:
            check(f"  → 目标含 {expect_segment}", expect_segment in it["to"], it["to"])

    # 有意义的双层结构保留不动（桶内包装层，内外层都有效）
    for keep in [r"\Liquid\Enjou_Gakuen_2\艶嬢", r"\Uncategorized\Oppai_Bunny_Gakuen\もっと",
                 r"\Uncategorized\Yukan_Fujin_Club\有閑"]:
        check(f"有意义双层保留: {os.path.basename(keep.rstrip(chr(92)))}",
              not any(keep in it["from"] for it in items))

    # 直接挂在桶下的游戏绝不能被提议移动
    buckets_now = organizer._detect_buckets(db, REAL_ROOT)
    for g in db.query("SELECT path FROM games WHERE status=2"):
        p = g["path"] or ""
        parent = os.path.basename(os.path.dirname(p.rstrip("\\/")))
        if parent.lower() in buckets_now:
            check(f"已入桶不动: {os.path.basename(p)}", p not in by_from, p)

    # status=0 的不进计划
    check("status=0 游戏不进计划",
          not any("和龙女妈妈" in it["from"] for it in items))
else:
    print(f"SKIP: 第 1 节断言绑定原开发机数据集（{REAL_ROOT}\\SummerClover 不存在），"
          "本机只验证 build_plan 可运行")
    cfg.set("library_roots", [REAL_ROOT] if os.path.isdir(REAL_ROOT) else [])
    plan = organizer.build_plan(cfg, db)
    check("build_plan 可运行（任意数据集）", isinstance(plan.get("items"), list))

# ---------- 2) apply_plan 沙箱执行 (临时目录) ----------
print("\n=== 2. apply_plan 真实移动 (沙箱临时目录) ===")
tmp = tempfile.mkdtemp(prefix="gala_apply_")
try:
    # 造一个模拟库: root/新游戏A(散落) + root/品牌桶/旧游戏
    os.makedirs(os.path.join(tmp, "BrandHouse", "OldGame"))
    os.makedirs(os.path.join(tmp, "NewGame"))
    with open(os.path.join(tmp, "NewGame", "game.exe"), "w") as f:
        f.write("x")
    with open(os.path.join(tmp, "NewGame", "cover.jpg"), "w") as f:
        f.write("img")
    with open(os.path.join(tmp, "BrandHouse", "OldGame", "old.exe"), "w") as f:
        f.write("x")

    db2 = Database(os.path.join(tmp, "sandbox2.db"))
    db2.init()
    gid = db2.execute(
        "INSERT INTO games (path, root, title, exe_path, workdir, cover_local, status, maker, added_at)"
        " VALUES (?,?,?,?,?,?,2,?,datetime('now'))",
        (os.path.join(tmp, "NewGame"), tmp, "NewGame",
         os.path.join(tmp, "NewGame", "game.exe"), os.path.join(tmp, "NewGame"),
         os.path.join(tmp, "NewGame", "cover.jpg"), "TestMaker"))

    cfg2 = Config()
    cfg2.set("library_roots", [tmp])
    plan2 = organizer.build_plan(cfg2, db2)
    check("沙箱计划含新游戏", len(plan2["items"]) == 1, str(plan2["items"]))
    to = plan2["items"][0]["to"]
    r = organizer.apply_plan(cfg2, db2, [{"game_id": gid, "to": to}])
    res = r["results"][0]
    check("移动成功", res["ok"] and res.get("moved"), str(res))
    check("目标存在", os.path.isdir(os.path.join(tmp, "TestMaker", "NewGame")))
    g = db2.query_one("SELECT * FROM games WHERE id=?", (gid,))
    check("DB path 已更新", g["path"] == os.path.join(tmp, "TestMaker", "NewGame"),
          g["path"])
    check("DB exe_path 已更新",
          g["exe_path"] == os.path.join(tmp, "TestMaker", "NewGame", "game.exe"),
          str(g["exe_path"]))
    check("DB cover_local 已更新",
          g["cover_local"] == os.path.join(tmp, "TestMaker", "NewGame", "cover.jpg"),
          str(g["cover_local"]))
    h = db2.query_one("SELECT * FROM organize_history")
    check("历史记录已写", h is not None and h["ok"] == 1)
    # 重复执行幂等: 已入桶 → 计划为空
    plan3 = organizer.build_plan(cfg2, db2)
    check("已整理后计划为空", len(plan3["items"]) == 0, str(plan3["items"]))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---------- 3) 三方对账决策逻辑 (mock, 无网络) ----------
print("\n=== 3. 三方对账决策逻辑 (mock) ===")
from unittest.mock import patch as mock_patch

tmp3 = tempfile.mkdtemp(prefix="gala_corr_")
try:
    db3 = Database(os.path.join(tmp3, "corr.db"))
    db3.init()
    gid = db3.execute(
        "INSERT INTO games (path, root, title, status, added_at) VALUES (?,?,?,0,datetime('now'))",
        (r"D:\fake\新游戏", r"D:\fake", "新游戏"))

    def mk_ai(conf, vndb_id=None, title="新游戏", title_jp="Original JP"):
        return {"provider": "ai", "external_id": "ai", "title": title,
                "title_orig": title_jp, "aliases": [], "maker": "TestMaker",
                "released": "", "rating": None, "cover_url": "", "summary": "简介",
                "tags": ["纯爱"], "score": conf, "vndb_id": vndb_id,
                "search_queries": ["Original JP"], "is_indie": False}

    from backend import enrich

    # 3a) AI 孤证高分 (0.95) + 双库无结果 → 必须待确认, 不得自动入库
    with mock_patch.object(enrich, "_ai_identify", return_value=mk_ai(0.95)), \
            mock_patch("backend.matcher.match_ai", return_value=[]), \
            mock_patch("backend.providers.vndb.get", return_value=(None, "no token")):
        r = enrich._analyze_one(cfg, db3, db3.query_one("SELECT * FROM games WHERE id=?", (gid,)))
        check("AI 孤证不进库 (待确认)", r["status"] == 1, str(r))
        check("AI 孤证原因", r.get("reason") == "no_strong_match", str(r))

    # 3b) AI 高分 + 数据库印证 (VNDB 高分命中) → 自动入库, AI 字段合并
    vndb_cand = {"provider": "vndb", "external_id": "v123", "title": "Original JP",
                 "title_orig": "Original JP", "aliases": [], "maker": "TestMaker",
                 "released": "2020-01-01", "rating": 78, "cover_url": "",
                 "summary": "en desc", "tags": ["romance"], "length_minutes": 300}
    with mock_patch.object(enrich, "_ai_identify", return_value=mk_ai(0.95)), \
            mock_patch("backend.matcher.match_ai",
                       return_value=[{**vndb_cand, "score": 0.97, "matched_key": "Original JP"}]):
        r = enrich._analyze_one(cfg, db3, db3.query_one("SELECT * FROM games WHERE id=?", (gid,)))
        check("AI+DB 印证入库", r["status"] == 2, str(r))
        g = db3.query_one("SELECT * FROM games WHERE id=?", (gid,))
        check("vndb_id 已填", g["vndb_id"] == "v123")
        check("source=vndb+ai", g["source"] == "vndb+ai", str(g["source"]))
        check("评分已填(10分制)", g["rating"] == 7.8, str(g["rating"]))
        check("AI 中文简介已合并", g["description"] == "简介", str(g["description"]))
        check("status=2", g["status"] == 2)

    # 3c) AI 声称 vndb_id + VNDB 条目对得上 → 强印证入库
    db3.execute("UPDATE games SET status=0, vndb_id=NULL WHERE id=?", (gid,))
    with mock_patch.object(enrich, "_ai_identify", return_value=mk_ai(0.9, vndb_id="v999")), \
            mock_patch("backend.matcher.match_ai", return_value=[]), \
            mock_patch("backend.providers.vndb.get",
                       return_value=({**vndb_cand, "external_id": "v999"}, None)):
        r = enrich._analyze_one(cfg, db3, db3.query_one("SELECT * FROM games WHERE id=?", (gid,)))
        check("AI声称ID+VNDB印证入库", r["status"] == 2, str(r))
        g = db3.query_one("SELECT * FROM games WHERE id=?", (gid,))
        check("vndb_id=v999", g["vndb_id"] == "v999", str(g["vndb_id"]))

    # 3d) match_cache 记忆命中 → 直接入库不再问 AI
    from backend.utils import normalize
    fk = normalize("新游戏")
    db3.execute("INSERT OR REPLACE INTO match_cache (folder_key, vndb_id, provider, confidence, chosen_by_user, updated_at)"
                " VALUES (?,?,?,1,1,datetime('now'))", (fk, "v555", "vndb"))
    db3.execute("UPDATE games SET status=0, vndb_id=NULL WHERE id=?", (gid,))
    with mock_patch.object(enrich, "_ai_identify", return_value=mk_ai(0.1)), \
            mock_patch("backend.providers.vndb.get",
                       return_value=({**vndb_cand, "external_id": "v555"}, None)):
        r = enrich._analyze_one(cfg, db3, db3.query_one("SELECT * FROM games WHERE id=?", (gid,)))
        check("记忆命中直接入库", r["status"] == 2 and r.get("from_cache"), str(r))
finally:
    shutil.rmtree(tmp3, ignore_errors=True)

print("\n" + ("=" * 30))
print("RESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
