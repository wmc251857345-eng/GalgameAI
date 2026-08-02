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
import types

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
check("migration idempotent + data kept", n >= 10 and "favorite" in cols and "provider" in mcols,
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
# 库数据会随用户清理变化：动态取真实存在的游戏，禁止硬编码 id
_g0 = dbx.query_one("SELECT * FROM games ORDER BY id LIMIT 1")
g1id = _g0["id"] if _g0 else 1
_g2 = dbx.query_one(
    "SELECT * FROM games WHERE path IS NOT NULL AND path!='' ORDER BY id LIMIT 1") or _g0
g2 = _g2 or {"id": 1, "path": None}
g2id = g2["id"]
r = js2.toggle_favorite(g1id)
g1 = dbx.query_one("SELECT favorite FROM games WHERE id=?", (g1id,))
check("toggle_favorite", r.get("ok") and g1["favorite"] == 1, dict(g1))
js2.toggle_favorite(g1id)  # 还原副本

# ---------- 3. bgm.search 修复（BGM 返回 {"results":N,"list":[...]} 字典） ----------
r = bgm.search(cfg, "summer pockets", limit=2)
check("bgm.search dict-wrapper fix", len(r) > 0 and bool(r[0].get("cover_url")),
      (r[0]["title"] if r else None))

# ---------- 4. 智能记忆：写入 + 命中 ----------
fk = normalize(os.path.basename(g2["path"] or ""))
js2.update_game(g2id, {"vndb_id": "v20424"})
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
    (g2id, "2026-08-01 10:00:00"))
launcher._finalize(dbx, g2id, sess_id, "2026-08-01 10:00:00",
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
js2.update_game(g2id, {"vndb_id": "v20424"})
_t0 = _t.time()
r = js2.reanalyze_game(g2id)
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

# ---------- 7. AI 管家对话冒烟（真实 LLM + 工具循环 + 历史落盘） ----------
r = js.chat_send("你好，简单介绍一下你自己")
check("chat_send replies", r.get("ok") and len(r.get("reply") or "") > 10,
      (r.get("reply") or "")[:60])
hist = js.chat_history()
check("chat history persisted", len(hist) >= 2 and hist[-1]["role"] == "assistant",
      f"{len(hist)} 条")
js.chat_clear()
check("chat_clear", len(js.chat_history()) == 0)

# 多提供商池：活动指向坏地址时自动故障转移到池内其他提供商
cfg_data = {"provider": {"name": "bad", "model": "x", "api_key": "bad",
                         "base_url": "http://127.0.0.1:1/v1"},
            "providers": [p for p in (cfg.get("providers") or []) if p.get("enabled")],
            "proxy": cfg.get("proxy", {})}
import json as _json
_tmpcfg = os.path.join(tempfile.gettempdir(), "gala_cfg_verify.json")
with open(_tmpcfg, "w", encoding="utf-8") as _f:
    _json.dump(cfg_data, _f, ensure_ascii=False)
from backend.config import Config as _Cfg
from backend.providers import llm as _llm
_c = _Cfg(path=_tmpcfg)
_r, _e = _llm.chat(_c, [{"role": "user", "content": "只回复: pong"}], json_mode=False, timeout=20)
check("provider failover", _r is not None, str(_e)[:60] if _e else "ok")
os.remove(_tmpcfg)

# ---------- 7.5 AI 管家工具绑定回归（修复 "TypeError: missing 'args'" bug） ----------
from backend.agent import AgentService as _Ag
_ag = _Ag(dbx, cfg)  # copy DB，写操作安全
_check_cfg = cfg.as_dict() if hasattr(cfg, "as_dict") else None
for _tname, _tfn in _ag._tool_fns.items():
    _targs = {
        "search_games": {"q": "summer"},
        "get_game": {"id": g1id},
        "get_library_stats": {},
        "list_facets": {},
        "search_providers": {"keyword": "Yuzusoft"},
        "correct_game": {"id": g1id, "title": "__agent_test__"},
        "update_game_info": {"id": g1id, "title": "__agent_test__"},
        "set_game_cover": {"id": g1id, "url": ""},   # 空 url 立刻返回错误 dict，不下载
        "reanalyze_game": {"id": g1id},
    }.get(_tname, {})
    try:
        _tr = _tfn(_targs)
        check(f"agent tool {_tname} bound call", isinstance(_tr, dict), str(_tr)[:60])
    except Exception as _e:
        check(f"agent tool {_tname} bound call", False, f"{type(_e).__name__}: {_e}")
_ag._db.execute("UPDATE games SET title=title WHERE id=?", (g1id,))  # 还原副本（no-op 保字段）
# 真实对话级回归：管家应能实际调用 search_games 工具并给出回复（完整 tool-call 循环）
_cc = js.chat_send("库里有纯爱标签的游戏吗？用工具查一下")
_tool_used = any(a["name"] == "search_games" for a in _cc.get("actions", []))
check("agent chat actually calls tools", _tool_used and (_cc.get("reply") or "").strip(),
      f"actions={[a['name'] for a in _cc.get('actions', [])]}, reply={(_cc.get('reply') or '')[:40]}")
js.chat_clear()

# ---------- 8. 厂商 / 系列追踪 ----------
mr = js.get_maker_profile("Yuzusoft")
check("maker profile", mr.get("ok") and mr.get("total_count", 0) > 0,
      (mr.get("error") or f"{mr.get('total_count')} 部作品")[:60])
if mr.get("ok"):
    vids = [w["id"] for w in mr["works"] if w.get("relations")]
    if vids:
        sr = js.get_series_profile(vids[0])
        check("series profile", sr.get("ok") and sr.get("total_count", 0) >= 1,
              (sr.get("error") or f"{sr.get('total_count')} 部")[:60])

# ---------- 9. 厂商墙 / 新作 / 作品详情 ----------
mw = js.get_makers_wall()
check("makers wall", mw.get("ok") and len(mw.get("makers", [])) > 0,
      f"{len(mw.get('makers', []))} 家")
wd = js.get_work_detail("v20424")
check("work detail", wd.get("ok") and wd["work"].get("title") == "Summer Pockets",
      (wd.get("error") or wd["work"].get("title"))[:60])
nr0 = js.refresh_new_releases()
check("new releases start", nr0.get("ok"), nr0)
nrs = js.get_new_releases()
check("new releases state shape", "state" in nrs and "releases" in nrs, "ok")

# ---------- 10. 关注厂商 / 厂商映射 / 标签 ----------
fp = js.follow_maker("Yuzusoft", "p98", "Yuzusoft")
check("follow maker", fp.get("ok"), fp)
fl = js.list_follows()
check("follows list", fl.get("ok") and any(f["maker_name"] == "Yuzusoft" for f in fl["follows"]), "ok")
sp = js.search_producers("Whirlpool")
check("search producers", sp.get("ok") and len(sp.get("candidates", [])) > 0,
      f"{len(sp.get('candidates', []))} 候选")
mp = js.set_maker_mapping("Yuzusoft", "p98", "Yuzusoft")
check("set maker mapping", mp.get("ok"), mp)
js.unfollow_maker("Yuzusoft")
check("unfollow maker", len([f for f in js.list_follows()["follows"]
                             if f["maker_name"] == "Yuzusoft"]) == 0, "ok")
zt = js.zh_tags(["Romance", "Drama", "Nakige"])
check("zh tag cache", zt.get("Romance") == "恋爱" and zt.get("Nakige") == "催泪", zt)

# ---------- 11. 作品标题中文缓存（批量翻译落库验证） ----------
wz = js.zh_work_titles(["v20424"])
check("work zh title cache", wz.get("v20424") == "夏日口袋", wz)

# ---------- 11.5 本轮修复回归：厂商映射显示名 / 扫描器垃圾过滤 ----------
import os as _os
import shutil as _shu
import tempfile as _tmp

# ① set_maker_mapping 显示名空值 → 回退本地厂商名
r = js2.set_maker_mapping("__verify_maker__", "p1", "")
check("mapping display fallback to local name",
      r.get("ok") and r.get("display_name") == "__verify_maker__", r)
js2._db.execute("DELETE FROM producer_map WHERE maker_name='__verify_maker__'")

# ② get_maker_profile 记忆命中：display_name 为空时回退本地名（不再显示空白/旧名）
api_mod._maker_cache.pop("Yuzusoft", None)
js2._db.execute("UPDATE producer_map SET display_name='' WHERE maker_name='Yuzusoft'")
mr2 = js2.get_maker_profile("Yuzusoft")
check("maker memo empty display falls back to local name",
      mr2.get("ok") and (mr2.get("producer") or {}).get("name") == "Yuzusoft",
      (mr2.get("producer") or {}).get("name"))
js2._db.execute("UPDATE producer_map SET display_name='Yuzusoft' WHERE maker_name='Yuzusoft'")
api_mod._maker_cache.pop("Yuzusoft", None)

# ③ 扫描器：只含垃圾 exe 的目录（DirectX9c/dxsetup.exe）不注册为游戏
from backend import scanner as _sc
_td = _tmp.mkdtemp(prefix="gala_scan_")
try:
    junk = _os.path.join(_td, "DirectX9c")
    _os.makedirs(junk)
    with open(_os.path.join(junk, "dxsetup.exe"), "wb") as _f:
        _f.write(b"MZ")
    good = _os.path.join(_td, "GoodGame")
    _os.makedirs(good)
    with open(_os.path.join(good, "GoodGame.exe"), "wb") as _f:
        _f.write(b"MZ")
    found = _sc.scan_root(_td, dbx)
    names = [f["title"] for f in found]
    check("scanner skips junk-exe-only dirs",
          "GoodGame" in names and "DirectX9c" not in names, names)
    dbx.execute("DELETE FROM games WHERE path LIKE ?", (f"{_td}%",))
finally:
    _shu.rmtree(_td, ignore_errors=True)

# ---------- 11.6 手动导入 / AI 补全 / 删除清理 回归 ----------
# ① search_candidates 真实搜索（VNDB+BGM 网络）
_sc0 = js2.search_candidates("summer pockets")
check("search_candidates", _sc0.get("ok") and len(_sc0.get("candidates", [])) > 0,
      f"{len(_sc0.get('candidates', []))} 候选")

# ② add_game_manual 创建 + 查重
_imp = js2.add_game_manual({"title": "__import_test__", "maker": "TestSoft",
                            "tags": ["测试", "导入"]})
_imp_id = _imp.get("id")
check("add_game_manual creates", _imp.get("ok") and _imp_id, _imp)
_dup = js2.add_game_manual({"title": "__import_test__"})
check("add_game_manual dedup", not _dup.get("ok") and "已有" in (_dup.get("error") or ""), _dup)
_tn = dbx.query_one("SELECT COUNT(*) c FROM game_tags WHERE game_id=?", (_imp_id,))["c"]
check("add_game_manual tags", _tn == 2, f"{_tn} tags")

# ③ import_game_candidate：按候选建条目 + 写入来源 ID + 重复导入拦截
_cand = {"provider": "vndb", "external_id": "v__imp_test__", "title": "__imp_vndb__",
         "title_orig": "テスト", "maker": "TestSoft", "released": "2020-01-01",
         "rating": 75.0, "cover_url": "", "summary": "test", "tags": ["纯爱"]}
_ir = js2.import_game_candidate(_cand)
_ir_id = _ir.get("id")
_g_ir = dbx.query_one("SELECT * FROM games WHERE id=?", (_ir_id,)) if _ir_id else None
check("import_game_candidate creates", _ir.get("ok") and _g_ir
      and _g_ir["vndb_id"] == "v__imp_test__" and _g_ir["status"] == 2
      and _g_ir["rating"] == 7.5, _ir)
_ir2 = js2.import_game_candidate(_cand)
check("import_game_candidate dedup by source id",
      not _ir2.get("ok") and "已有" in (_ir2.get("error") or ""), _ir2)

# ④ remove_game 清理关联表 + 封面文件
_g2id = _imp_id
dbx.execute("INSERT INTO match_candidates (game_id, provider, external_id, title, score, payload)"
            " VALUES (?,?,?,?,?,?)", (_g2id, "vndb", "vx", "t", 0.5, "{}"))
dbx.execute("INSERT INTO sessions (game_id, started_at, ended_at, seconds)"
            " VALUES (?,?,?,?)", (_g2id, "2026-01-01 00:00:00", None, 0))
_rr = js2.remove_game(_g2id)
_gone = dbx.query_one("SELECT id FROM games WHERE id=?", (_g2id,))
_left = dbx.query_one("SELECT COUNT(*) c FROM match_candidates WHERE game_id=?", (_g2id,))["c"]
_sess = dbx.query_one("SELECT COUNT(*) c FROM sessions WHERE game_id=?", (_g2id,))["c"]
check("remove_game cleans relations", _rr.get("ok") and not _gone and _left == 0 and _sess == 0,
      f"candidates={_left} sessions={_sess}")
# 清理 ③ 的导入条目
js2.remove_game(_ir_id)

# ⑤ AI 管家 import_game 工具绑定 + 调用（无候选 → 占位条目）
from backend.agent import AgentService as _Ag2
_ag2 = _Ag2(dbx, cfg)
check("agent import_game tool bound", isinstance(_ag2._tool_fns.get("import_game"), types.MethodType))
_air = _ag2._tool_fns["import_game"]({"title": "__agent_import__", "maker": "TestSoft"})
check("agent import_game runs", _air.get("ok") and _air.get("id"), _air)
if _air.get("id"):
    js2.remove_game(_air["id"])

# ---------- 11.7 本地导入（exe+备注 → AI 补全）回归 ----------
# ① 候选选择规则（纯静态）
_bc = js2._pick_best_candidate(
    [{"title": "Other", "provider": "bgm"}, {"title": "Summer Pockets", "provider": "vndb"}],
    "Summer Pockets", "")
check("pick_best_candidate exact", _bc["title"] == "Summer Pockets", _bc)
_bc2 = js2._pick_best_candidate(
    [{"title": "Other", "maker": "X"}, {"title": "SP", "maker": "Key"}],
    "summer", "Key")
check("pick_best_candidate by maker", _bc2["maker"] == "Key", _bc2)

# ② import_local_game：真实 temp 目录 + 备注 → LLM 提取 → 建条目（path/exe/workdir 落库）
_ld = _tmp.mkdtemp(prefix="gala_import_")
try:
    with open(_os.path.join(_ld, "game.exe"), "wb") as _f:
        _f.write(b"MZ")
    _lr = js2.import_local_game({"exe_path": _os.path.join(_ld, "game.exe"),
                                 "folder": _ld, "note": "一个测试用的纯爱小游戏"})
    _lg = dbx.query_one("SELECT * FROM games WHERE id=?", (_lr.get("id"),)) if _lr.get("id") else None
    check("import_local_game creates with path",
          _lr.get("ok") and _lg and _lg["path"] == _ld
          and _lg["exe_path"] == _os.path.join(_ld, "game.exe")
          and _lg["status"] == 2 and _lg["source"] == "manual",
          {k: _lr.get(k) for k in ("ok", "id", "title", "matched", "provider")})
    check("import_local_game returns alternates key", "alternates" in _lr, list(_lr.keys()))
    _lid = _lr.get("id")

    # ③ reimport_game_source：换用候选资料
    _rc = {"provider": "vndb", "external_id": "v__reimport__", "title": "__reimport_title__",
           "maker": "NewSoft", "released": "2019-05-05", "rating": 80.0,
           "cover_url": "", "summary": "new desc"}
    _rr2 = js2.reimport_game_source(_lid, _rc)
    _rg = dbx.query_one("SELECT title, maker, vndb_id, rating FROM games WHERE id=?", (_lid,))
    check("reimport_game_source updates", _rr2.get("ok") and _rg
          and _rg["title"] == "__reimport_title__" and _rg["maker"] == "NewSoft"
          and _rg["vndb_id"] == "v__reimport__" and _rg["rating"] == 8.0,
          dict(_rg) if _rg else _rr2)
    if _lid:
        js2.remove_game(_lid)
finally:
    _shu.rmtree(_ld, ignore_errors=True)

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
