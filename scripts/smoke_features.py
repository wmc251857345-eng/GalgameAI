# -*- coding: utf-8 -*-
"""后端冒烟：makers 锚定逻辑 + db 迁移 + steam provider + 封面裁剪。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import makers
from backend.db import Database


def t_makers():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    db.init()
    try:
        # 1) 同一厂商不同写法 → 归一
        assert makers.canonical(db, "Miel (ミエル)") == "Miel (ミエル)"
        assert makers.canonical(db, "Miel") == "Miel (ミエル)", "Miel 应归一"
        assert makers.canonical(db, "ミエル") == "Miel (ミエル)", "ミエル 应归一"
        # 2) 汉字写法
        assert makers.canonical(db, "柚子社") == "柚子社"
        # 汉字 vs 罗马音无法纯靠名字推断（柚子社≠YUZUSOFT 不自动合并，走 VNDB 别名/手动合并）
        # 3) 纯假名 vs 罗马音（kana→romaji + difflib）
        assert makers.canonical(db, "アリスソフト") == "アリスソフト"
        assert makers.canonical(db, "Alicesoft") in ("アリスソフト", "Alicesoft")
        # 4) 同一 vndb_id 强制合并
        makers.canonical(db, "Key")
        makers.canonical(db, "ビジュアルアーツ", "pa999")
        assert makers.canonical(db, "Key", "pa999") == "Key", "同 vndb_id 应合并到先锚定的"
        # 5) sync_all 回写 games.maker
        db.execute("INSERT INTO games (title, maker, status) VALUES ('A1','Miel',2)")
        db.execute("INSERT INTO games (title, maker, status) VALUES ('A2','Miel (ミエル)',2)")
        db.execute("INSERT INTO games (title, maker, status) VALUES ('B1','ミエル',2)")
        makers.sync_all(db)
        rows = db.query("SELECT DISTINCT maker FROM games")
        makers_set = {r["maker"] for r in rows}
        assert makers_set == {"Miel (ミエル)"}, f"sync_all 后应只剩一个写法: {makers_set}"
        # 6) merge：把「柚子社」并入新规范名「YUZUSOFT」
        db.execute("INSERT INTO games (title, maker, status) VALUES ('C1','柚子社',2)")
        ok, canon, err = makers.merge_makers(db, "柚子社", "YUZUSOFT")
        assert ok and canon == "YUZUSOFT", (canon, err)
        assert db.query_one("SELECT maker FROM games WHERE title='C1'")["maker"] == "YUZUSOFT"
        # 合并后反向写入也归一
        assert makers.canonical(db, "柚子社") == "YUZUSOFT"
        # 7) 别名集合
        lm = makers.list_makers(db)
        by_name = {m["name"]: m for m in lm}
        assert by_name["Miel (ミエル)"]["count"] == 3
        # 8) 冲突场景：两条别名 + follows/producer_map 同时指向别名 → sync_all 不得撞 UNIQUE。
        #    display_name 回写规则：最后一次更正（updated_at 较新）生效 → 规范名被更正为 ミエル
        db.execute("INSERT INTO games (title, maker, status) VALUES ('D1','Miel',2)")
        db.execute("INSERT INTO maker_follows (maker_name, created_at) VALUES ('Miel', '2026-01-01')")
        db.execute("INSERT INTO maker_follows (maker_name, created_at) VALUES ('ミエル', '2026-01-01')")
        db.execute("INSERT INTO producer_map (maker_name, vndb_id, display_name, updated_at)"
                   " VALUES ('Miel','p1','Miel','2026-01-01')")
        db.execute("INSERT INTO producer_map (maker_name, vndb_id, display_name, updated_at)"
                   " VALUES ('ミエル','p1','ミエル','2026-01-02')")
        makers.sync_all(db)  # 不抛异常即通过
        assert db.query_one("SELECT COUNT(*) c FROM maker_follows")["c"] == 1
        assert db.query_one("SELECT maker_name FROM maker_follows")["maker_name"] == "ミエル"
        # Miel 组的 pm 行只剩一条（step6 merge 的 YUZUSOFT 行不算）
        assert db.query_one(
            "SELECT COUNT(*) c FROM producer_map WHERE maker_name='ミエル'")["c"] == 1
        assert db.query_one("SELECT vndb_id FROM producer_map WHERE maker_name='ミエル'")["vndb_id"] == "p1"
        assert db.query_one("SELECT maker FROM games WHERE title='D1'")["maker"] == "ミエル"
        # 原规范名写法降级为别名，仍归一
        assert makers.canonical(db, "Miel (ミエル)") == "ミエル"
        print("makers OK:", [m["name"] for m in lm])
    finally:
        db.close()
        os.remove(path)


def t_crop():
    from backend import paths
    from PIL import Image
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tmp = tempfile.mkdtemp()
    old_covers, old_base = paths.COVERS_DIR, paths.BASE
    paths.COVERS_DIR = os.path.join(tmp, "covers")
    paths.BASE = tmp
    os.makedirs(paths.COVERS_DIR, exist_ok=True)
    db = Database(path)
    db.init()
    from backend.api import JsApi
    from backend.config import Config
    api = JsApi(db, Config())
    try:
        gid = db.execute(
            "INSERT INTO games (title, maker, status) VALUES ('T','K',2)")
        # 造一张 600x400 测试图
        src = os.path.join(tmp, "covers", f"{gid}.jpg")
        Image.new("RGB", (600, 400), (200, 60, 60)).save(src)
        db.execute("UPDATE games SET cover_path=? WHERE id=?",
                   (os.path.relpath(src, tmp).replace("\\", "/"), gid))
        r = api.set_cover_crop(gid, 0, 0, 0.5, 0.5)
        assert r.get("ok"), r
        g = db.query_one("SELECT * FROM games WHERE id=?", (gid,))
        assert g["cover_orig_path"], "应记录原图"
        assert g["cover_path"].endswith("_crop.jpg"), g["cover_path"]
        img = Image.open(os.path.join(tmp, g["cover_path"].replace("/", os.sep)))
        assert img.size == (300, 200), img.size
        # 重置
        r2 = api.clear_cover_crop(gid)
        assert r2.get("ok"), r2
        g2 = db.query_one("SELECT cover_path, cover_orig_path FROM games WHERE id=?", (gid,))
        assert g2["cover_path"] == g["cover_orig_path"]
        assert g2["cover_orig_path"] is None
        print("crop OK:", img.size)
    finally:
        db.close()
        os.remove(path)
        paths.COVERS_DIR, paths.BASE = old_covers, old_base


def t_steam():
    from backend.config import Config
    from backend.providers import steam
    cfg = Config()
    cands = steam.search(cfg, "summer pockets", limit=3)
    print("steam search:", [(c["title"], c["external_id"], c.get("maker"),
                             c.get("released")) for c in cands])
    assert cands, "Steam 搜索应有结果"
    assert all(c["provider"] == "steam" for c in cands)
    assert all(c["cover_url"].endswith("library_600x900.jpg") for c in cands)
    c2, err = steam.get(cfg, cands[0]["external_id"])
    assert c2 and not err, (c2, err)
    print("steam get OK:", c2["title"], "|", c2.get("maker"))


if __name__ == "__main__":
    t_makers()
    t_crop()
    t_steam()
    print("ALL BACKEND SMOKE PASS")
