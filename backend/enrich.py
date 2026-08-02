"""分析流水线：匹配 → 自动确认/待确认 → 封面下载 → AI 中文简介/标签。
全局进度 STATE 供前端轮询；可断点续跑（status 0/1 的游戏重跑即可）。
"""
import json
import os
import re
import shutil
import threading
import time

from . import paths
from .utils import download_file, http_session, now_iso

STATE = {
    "running": False, "stage": "", "total": 0, "done": 0,
    "current": "", "error": None, "log": [],
}
_lock = threading.Lock()

# 已放弃的 AI 识别条目（LLM 识别不出的游戏；进程内记忆，避免 analyze_all/扫描自动分析
# 反复对同一批游戏烧 token 调 LLM）。重启后清空，每会话给一次重试机会。
# 注意：只影响 LLM 识别步骤，bgm/vndb 免费候选仍会跑；match_cache 记忆命中优先不受影响。
_ANALYZE_GAVE_UP = set()

# 单游戏后台任务（重新分析用）：前端轮询 get_job_status
ONE_JOB = {"running": False, "game_id": None, "stage": "", "result": None, "error": None}

ENRICH_SYSTEM = (
    "你是 Galgame 资料库整理助手。只输出合法 JSON，不要任何多余文字。"
)

ENRICH_USER = """根据给定信息识别并整理这部 Galgame，输出 JSON：
{{"title_zh": "中文常用译名(没有就空字符串)", "summary_zh": "80-150字中文简介", "tags_zh": ["3-6个中文题材标签，如 纯爱/废萌/母系/悬疑/实用/催泪"]}}
信息：
目录名: {folder}
{extra}"""


def _set(**kw):
    with _lock:
        STATE.update(kw)


def _log(msg):
    with _lock:
        STATE["log"].append(msg)
        STATE["log"] = STATE["log"][-200:]


def _cover_dest(game_id, url):
    ext = ".png" if (url or "").lower().endswith(".png") else ".jpg"
    return os.path.join(paths.COVERS_DIR, f"{game_id}{ext}")


def download_cover(cfg, game_id, url, fallback_local=None):
    """下载封面到 cache/covers/，返回相对路径；失败用本地图兜底。"""
    if url:
        dest = _cover_dest(game_id, url)
        s = http_session(cfg, proxy_ok=True)
        if download_file(s, url, dest):
            return os.path.relpath(dest, paths.BASE).replace("\\", "/")
    if fallback_local and os.path.exists(fallback_local):
        dest = os.path.join(paths.COVERS_DIR, f"{game_id}_local.jpg")
        try:
            shutil.copyfile(fallback_local, dest)
            return os.path.relpath(dest, paths.BASE).replace("\\", "/")
        except OSError:
            pass
    return None


def _apply_match(cfg, db, game, cand, async_enrich=False):
    """把候选应用到 game：填字段、下载封面。async_enrich=True 时 AI 润色后台执行
    （用于桥接线程内的确认操作，避免同步等 LLM 卡死界面）。"""
    from . import makers
    cover_path = download_cover(cfg, game["id"], cand.get("cover_url"),
                                game.get("cover_local"))
    bgm_id = int(cand["external_id"]) if cand["provider"] == "bgm" and cand["external_id"].isdigit() else None
    vndb_id = cand["external_id"] if cand["provider"] == "vndb" else None
    steam_id = cand["external_id"] if cand["provider"] == "steam" else None
    rating = cand.get("rating")
    if isinstance(rating, (int, float)) and rating > 20:  # VNDB 0-100 → 统一 10 分制
        rating = round(rating / 10, 2)
    # 制作组名自动锚定：中/英/日文写法统一到规范名（数据库级合并，不再各写各的）
    maker = makers.canonical(db, cand.get("maker") or "")
    db.execute(
        """UPDATE games SET title=?, title_en=?, title_jp=?, maker=?, released=?,
           rating=?, description=?, cover_path=?, cover_url=?, vndb_id=?, bgm_id=?,
           steam_id=?, length_level=?, length_minutes=?, status=2, match_confidence=?, source=?
           WHERE id=?""",
        (cand.get("title") or game["title"],
         cand.get("title") or "", cand.get("title_orig") or "",
         maker, cand.get("released") or "",
         rating, cand.get("summary") or "",
         cover_path, cand.get("cover_url") or "",
         vndb_id, bgm_id, steam_id,
         cand.get("length_level"), cand.get("length_minutes"),
         cand["score"], cand["provider"], game["id"]))
    if async_enrich:
        threading.Thread(target=_enrich_ai, args=(cfg, db, game, cand), daemon=True).start()
    else:
        _enrich_ai(cfg, db, game, cand)


def _enrich_ai(cfg, db, game, cand):
    """Gemini(中转) 生成中文简介/标签 + 视觉辅助。失败不影响入库。"""
    from .providers import llm
    extra = []
    if cand.get("title_orig"):
        extra.append(f"日文名: {cand['title_orig']}")
    if cand.get("title"):
        extra.append(f"英文/中文名: {cand['title']}")
    if cand.get("maker"):
        extra.append(f"厂商: {cand['maker']}")
    if cand.get("released"):
        extra.append(f"发售: {cand['released']}")
    if cand.get("summary"):
        extra.append(f"现有简介: {cand['summary'][:300]}")
    if cand.get("tags"):
        extra.append(f"现有标签: {', '.join(cand['tags'][:8])}")
    user = ENRICH_USER.format(folder=game["title"],
                              extra="\n".join(extra))
    vision = None
    if game.get("cover_local") and os.path.exists(game["cover_local"]):
        vision = llm.image_to_b64(game["cover_local"])
    if vision is None and cand.get("cover_url"):
        vision = None  # 网络图不下载给 AI，省流量
    res, err = llm.chat_json(cfg, ENRICH_SYSTEM, user, vision_image=vision)
    if err or not res:
        _log(f"    AI 简介失败: {err}")
        return
    title_zh = (res.get("title_zh") or "").strip()
    summary = (res.get("summary_zh") or "").strip()
    tags = [t.strip() for t in (res.get("tags_zh") or []) if t.strip()][:8]
    if title_zh or summary:
        db.execute("UPDATE games SET title_zh=?, description=? WHERE id=?",
                   (title_zh or None, summary or None, game["id"]))
    for t in tags:
        db.execute("INSERT OR IGNORE INTO tags (name, category) VALUES (?, 'ai')", (t,))
        row = db.query_one("SELECT id FROM tags WHERE name=?", (t,))
        if row:
            db.execute(
                "INSERT OR IGNORE INTO game_tags (game_id, tag_id, source) VALUES (?,?,'ai')",
                (game["id"], row["id"]))


AI_IDENTIFY_SYSTEM = (
    "你是 Galgame 数据库专家，熟悉日系视觉小说全目录。"
    "只输出合法 JSON，不要任何多余文字。"
)

AI_IDENTIFY_USER = """根据已知信息识别这部 Galgame，输出 JSON：
{{"title_jp": "日文原名", "title_en": "英文/罗马音名(无则空)", "title_zh": "中文常用译名(无则空)",
  "maker": "制作公司", "released": "YYYY-MM-DD(不确定给年份即可,不知道给空)",
  "tags_zh": ["3-6个中文题材标签，如 纯爱/废萌/母系/悬疑/实用/催泪"],
  "summary_zh": "80-150字中文简介", "vndb_id": "VNDB条目ID(形如v12345,不知道给空)",
  "confidence": 0到1的匹配置信度}}
已知信息：
目录名: {folder}
{extra}
如果这些信息不足以确定是哪个游戏，confidence 给低于 0.3，并尽量给出最可能的推测。"""


def _parent_hint(game):
    """从路径取上级目录名作为厂商/品牌线索（GalGame/厂商/作品名 两层结构）。

    平铺布局（父目录=库根）、根目录自身、隐藏目录、明显非厂商的归类目录
    （Uncategorized 等）一律返回空，避免把噪音当厂商。
    """
    p = (game.get("path") or "").strip()
    if not p:
        return ""
    parent = os.path.basename(os.path.dirname(p.rstrip("\\/")))
    if not parent or parent.startswith((".", "$")):
        return ""
    root = (game.get("root") or "").strip()
    if root and os.path.normpath(os.path.dirname(p)) == os.path.normpath(root):
        return ""  # 平铺布局：上级就是库根，没有厂商层
    if parent.lower() in ("uncategorized", "unclassified", "misc", "other", "未分类", "其他"):
        return ""
    return parent


def _ai_identify(cfg, db, game):
    """AI 主通道识别：目录名 + 上级目录(厂商线索) + readme + 本地封面(视觉)。返回候选 dict 或 None。"""
    from .providers import llm
    extra = []
    text = (game.get("text_sample") or "").strip()
    if text:
        extra.append(f"本地文件信息:\n{text[:800]}")
    parent = _parent_hint(game)
    if parent:
        extra.append(f"上级目录名（通常是制作公司/品牌，请用于辅助确认厂商）: {parent}")
    user = AI_IDENTIFY_USER.format(folder=game["title"],
                                   extra="\n".join(extra))
    vision = None
    if game.get("cover_local") and os.path.exists(game["cover_local"]):
        vision = llm.image_to_b64(game["cover_local"])
    res, err = llm.chat_json(cfg, AI_IDENTIFY_SYSTEM, user, vision_image=vision)
    if err:
        _log(f"    AI 识别失败: {err}")
        return None
    if not res or not isinstance(res, dict):
        return None
    title_jp = (res.get("title_jp") or "").strip()
    title_en = (res.get("title_en") or "").strip()
    title_zh = (res.get("title_zh") or "").strip()
    try:
        conf = float(res.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    if not title_jp and not title_en and not title_zh:
        return None
    cand = {
        "provider": "ai",
        "external_id": "ai",
        "title": title_zh or title_jp or title_en,
        "title_orig": title_jp or "",
        "aliases": [t for t in (title_en, title_jp) if t],
        "maker": (res.get("maker") or "").strip(),
        "released": (res.get("released") or "").strip(),
        "rating": None,
        "cover_url": "",
        "summary": (res.get("summary_zh") or "").strip(),
        "tags": [t.strip() for t in (res.get("tags_zh") or []) if t.strip()][:8],
        "score": round(min(max(conf, 0.0), 1.0), 3),
        "vndb_id": (res.get("vndb_id") or "").strip() or None,
    }
    return cand


def _analyze_one(cfg, db, game):
    """识别流程：用户纠正记忆(match_cache) → AI 识别 → bgm/vndb/steam 候选。"""
    from .matcher import match
    from .providers import bgm, steam, vndb
    from .utils import normalize
    thr = cfg.get("analysis.auto_confirm_threshold", 0.9)

    # 0) 记忆命中：用户以前确认/纠正过这个文件夹 → 直接精确获取，不再问 AI
    folder_key = normalize(os.path.basename(game.get("path") or ""))
    if folder_key:
        mc = db.query_one(
            "SELECT vndb_id, provider FROM match_cache WHERE folder_key=?", (folder_key,))
        if mc and mc.get("vndb_id"):
            cand = None
            if (mc.get("provider") or "vndb") == "bgm":
                cand = bgm.get(cfg, mc["vndb_id"])
            elif (mc.get("provider") or "") == "steam":
                cand, _ = steam.get(cfg, mc["vndb_id"])
            else:
                cand, _ = vndb.get(cfg, mc["vndb_id"])
            if cand:
                cand["score"] = 1.0
                cand["provider"] = mc.get("provider") or "vndb"
                cand["external_id"] = mc["vndb_id"]
                _apply_match(cfg, db, game, cand)
                return {"status": 2, "matched": cand.get("title"), "score": 1.0, "from_cache": True}

    # AI 识别：已在 _ANALYZE_GAVE_UP 里的游戏跳过 LLM 调用（防 analyze_all 反复烧 token，
    # 仍走免费的 bgm/vndb 候选；进程重启清空 → 每会话给一次重试机会）
    ai_cand = None
    if game["id"] not in _ANALYZE_GAVE_UP:
        ai_cand = _ai_identify(cfg, db, game)
        if ai_cand is None:
            _ANALYZE_GAVE_UP.add(game["id"])  # 识别不出 → 本会话不再问 AI
    web_cands = []
    try:
        web_cands = match(cfg, game["title"])
    except Exception:
        pass

    cands = ([ai_cand] if ai_cand else []) + web_cands
    db.execute("DELETE FROM match_candidates WHERE game_id=?", (game["id"],))
    for c in cands[:6]:
        db.execute(
            "INSERT INTO match_candidates (game_id, provider, external_id, title, score, payload)"
            " VALUES (?,?,?,?,?,?)",
            (game["id"], c["provider"], c["external_id"], c.get("title") or "",
             c["score"], json.dumps(c, ensure_ascii=False)))
    if not cands:
        db.execute("UPDATE games SET status=1 WHERE id=?", (game["id"],))
        return {"status": 1, "reason": "no_candidates"}

    best = cands[0]
    if best["score"] >= thr:
        _apply_match(cfg, db, game, best)
        return {"status": 2, "matched": best.get("title"), "score": best["score"]}
    db.execute("UPDATE games SET status=1 WHERE id=?", (game["id"],))
    return {"status": 1, "matched": best.get("title"), "score": best["score"]}


def _run_one_job(cfg, db, game):
    """后台执行单个游戏的重新分析（供 reanalyze_game 用）。
    已入库且有 vndb_id → 快速 VNDB 刷新；否则完整重新识别。"""
    with _lock:
        ONE_JOB.update(running=True, game_id=game["id"], stage="analyze",
                       result=None, error=None)
    try:
        # 用户手动触发重新分析 = 明确的重试意图：清掉放弃记忆，给一次完整 LLM 识别
        _ANALYZE_GAVE_UP.discard(game["id"])
        if game.get("status") == 2 and game.get("vndb_id"):
            from .api import JsApi
            r = JsApi._refresh_game(cfg, db, game)
        else:
            r = _analyze_one(cfg, db, game)
        with _lock:
            ONE_JOB.update(running=False, stage="idle", result=r)
    except Exception as e:
        with _lock:
            ONE_JOB.update(running=False, stage="idle", result=None, error=str(e))


def scan_all(cfg, db):
    if STATE["running"]:
        return
    _set(running=True, stage="scan", total=0, done=0, current="", error=None, cancel_requested=False)
    new_paths = []
    try:
        from .scanner import scan_root
        roots = cfg.get("library_roots", [])
        for root in roots:
            if STATE.get("cancel_requested"):
                _log("扫描已取消")
                break
            if not os.path.isdir(root):
                _log(f"跳过不存在的目录: {root}")
                continue
            _set(current=f"扫描 {root}")
            found = scan_root(root, db)
            new_paths.extend(i["path"] for i in found if i.get("path"))
            _log(f"扫描 {root}: 新增 {len(found)} 个游戏")
    except Exception as e:
        _set(error=str(e))
    finally:
        # 扫描到新游戏 → 自动启动 AI 识别/匹配（扫描即整理，无需手动再点分析）
        if new_paths and not STATE.get("cancel_requested"):
            _log(f"扫描完成，自动分析 {len(new_paths)} 个新增游戏…")
            _auto_analyze_new(cfg, db, new_paths)
        _set(running=False, stage="idle", current="")


def _auto_analyze_new(cfg, db, paths):
    """对扫描新增的游戏逐个跑完整识别：match_cache 记忆 → AI 识别 → bgm/vndb 候选。
    高分自动入库（status=2），低分进待确认（status=1）。同一 STATE 进度，前端无需新接口。
    """
    games = []
    for p in paths:
        g = db.query_one("SELECT * FROM games WHERE path=? ORDER BY id DESC LIMIT 1", (p,))
        if g and g.get("status") in (0, 1):
            games.append(g)
    _set(stage="analyze", total=len(games), done=0, current="")
    for i, g in enumerate(games, 1):
        if STATE.get("cancel_requested"):
            _log("自动分析已取消")
            break
        _set(current=g["title"], done=i - 1)
        try:
            r = _analyze_one(cfg, db, g)
            tag = "✓入库" if r.get("status") == 2 else ("待确认" if r.get("status") == 1 else "?")
            _log(f"[{i}/{len(games)}] {g['title']} → {tag}"
                 + (f" ({r.get('matched')} {r.get('score')})" if r.get("matched") else ""))
        except Exception as e:
            _log(f"[{i}/{len(games)}] {g['title']} 失败: {e}")
        time.sleep(0.3)


def analyze_all(cfg, db):
    if STATE["running"]:
        return
    _set(running=True, stage="analyze", total=0, done=0, current="", error=None, cancel_requested=False)
    try:
        games = db.query("SELECT * FROM games WHERE status IN (0,1) ORDER BY id")
        _set(total=len(games))
        for i, g in enumerate(games, 1):
            if not STATE["running"] or STATE.get("cancel_requested"):  # 允许停止/取消
                break
            _set(current=g["title"], done=i - 1)
            try:
                r = _analyze_one(cfg, db, g)
                tag = "✓入库" if r.get("status") == 2 else ("待确认" if r.get("status") == 1 else "?")
                _log(f"[{i}/{len(games)}] {g['title']} → {tag}"
                     + (f" ({r.get('matched')} {r.get('score')})" if r.get("matched") else ""))
            except Exception as e:
                _log(f"[{i}/{len(games)}] {g['title']} 失败: {e}")
            time.sleep(0.3)
    except Exception as e:
        _set(error=str(e))
    finally:
        _set(running=False, stage="idle", current="", done=STATE["total"])


def fill_covers_all(cfg, db):
    """批量补封面：status=2 且无本地封面的游戏。
    优先级: vndb_id 精确 → bgm_id 精确 → 标题链[日文名→英文名→中文名→文件夹名] 搜 vndb→bgm。
    """
    if STATE["running"]:
        return
    _set(running=True, stage="covers", total=0, done=0, current="", error=None, cancel_requested=False)
    try:
        games = db.query(
            "SELECT * FROM games WHERE status=2 AND (cover_path IS NULL OR cover_path='') ORDER BY id")
        _set(total=len(games))
        done = 0
        for g in games:
            if not STATE["running"] or STATE.get("cancel_requested"):
                break
            _set(current=g["title"], done=done)
            url = _find_cover_url(cfg, g, db)
            if url:
                rel = download_cover(cfg, g["id"], url)
                if rel:
                    db.execute("UPDATE games SET cover_path=?, cover_url=? WHERE id=?",
                               (rel, url, g["id"]))
                    _log(f"  封面 ✓ {g['title']}")
            done += 1
            _set(done=done)
            time.sleep(0.15)
        _log(f"补齐封面完成: 处理 {done} 个")
    except Exception as e:
        _set(error=str(e))
    finally:
        _set(running=False, stage="idle", current="", done=STATE["total"])


def _find_cover_url(cfg, g, db=None):
    """按优先级找一个封面 URL：vndb_id 精确 → bgm_id 精确 → steam_id 精确 → 标题链搜索 → 历史候选兜底。"""
    from .providers import bgm, steam, vndb
    if g.get("vndb_id"):
        cand, _ = vndb.get(cfg, g["vndb_id"])
        if cand and cand.get("cover_url"):
            return cand["cover_url"]
    if g.get("bgm_id"):
        cand = bgm.get(cfg, str(g["bgm_id"]))
        if cand and cand.get("cover_url"):
            return cand["cover_url"]
    if g.get("steam_id"):
        cand, _ = steam.get(cfg, g["steam_id"])
        if cand and cand.get("cover_url"):
            return cand["cover_url"]
    # 标题链：日文原名 → 英文名 → 中文名 → 文件夹名（每个都展开成多个搜索变体）
    keys = []
    for k in ("title_jp", "title_en", "title"):
        v = (g.get(k) or "").strip()
        if v and v not in keys:
            keys.append(v)
    folder = os.path.basename(g.get("path") or "").strip()
    if folder and folder not in keys:
        keys.append(folder)
    variants = []
    for key in keys:
        for v in _expand_keys(key):
            if v not in variants:
                variants.append(v)
    for kv in variants[:12]:
        try:
            cands, _ = vndb.search(cfg, kv, limit=4)
            for c in cands:
                if c.get("cover_url"):
                    return c["cover_url"]
        except Exception:
            pass
        try:
            cands = bgm.search(cfg, kv)
            for c in cands:
                if c.get("cover_url"):
                    return c["cover_url"]
        except Exception:
            pass
        try:
            for c in steam.search(cfg, kv, limit=3):
                if c.get("cover_url"):
                    return c["cover_url"]
        except Exception:
            pass
    # 兜底：历史匹配候选里的封面 URL（零成本，本地已有）
    if db:
        for row in db.query(
                "SELECT payload FROM match_candidates WHERE game_id=? ORDER BY score DESC",
                (g.get("id"),)):
            try:
                p = json.loads(row["payload"])
                if p.get("cover_url"):
                    return p["cover_url"]
            except Exception:
                continue
    return None


def _expand_keys(key):
    """搜索变体展开：下划线→空格、camelCase 拆词、去 ～副标题～、去版本号、截断长标题。"""
    out = [key]
    k = (key or "").strip()
    if not k:
        return out
    k = k.replace("_", " ")
    k = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", k)   # JerezArena → Jerez Arena
    variants = [k]
    variants.append(re.sub(r"[～〜~].*", "", k).strip())          # 去副标题
    variants.append(re.sub(r"[\s\-·•]*[vV]?\d+(\.\d+)*$", "", k).strip())  # 去版本号
    words = re.split(r"[\s\-·•]+", k)
    if len(words) > 2:
        variants.append(" ".join(words[:2]))
        variants.append(" ".join(words[:3]))
    for v in variants:
        v = v.strip()
        if v and v not in out:
            out.append(v)
    return out
