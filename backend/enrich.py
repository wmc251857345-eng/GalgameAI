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


def _apply_match(cfg, db, game, cand, async_enrich=False, ai_extra=None):
    """把候选应用到 game：填字段、下载封面。async_enrich=True 时 AI 润色后台执行
    （用于桥接线程内的确认操作，避免同步等 LLM 卡死界面）。
    ai_extra（可选）：三方互证中 AI 识别出的 {title_zh, summary, tags}，
    与数据库候选合并——DB 管评分/时长/封面，AI 管中文译名/简介/题材标签；
    有 ai_extra 时跳过重复的 AI 润色调用（省 token）。"""
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
    title_zh = (ai_extra or {}).get("title_zh") or None
    summary = (ai_extra or {}).get("summary") or cand.get("summary") or ""
    source = cand["provider"] + ("+ai" if ai_extra else "")
    db.execute(
        """UPDATE games SET title=?, title_en=?, title_jp=?, title_zh=?, maker=?, released=?,
           rating=?, description=?, cover_path=?, cover_url=?, vndb_id=?, bgm_id=?,
           steam_id=?, length_level=?, length_minutes=?, status=2, match_confidence=?, source=?
           WHERE id=?""",
        (cand.get("title") or game["title"],
         cand.get("title") or "", cand.get("title_orig") or "",
         title_zh, maker, cand.get("released") or "",
         rating, summary,
         cover_path, cand.get("cover_url") or "",
         vndb_id, bgm_id, steam_id,
         cand.get("length_level"), cand.get("length_minutes"),
         cand["score"], source, game["id"]))
    # AI 中文题材标签并入（DB 候选自带英文/日文标签，AI 标签是中文的，不冲突）
    for t in (ai_extra or {}).get("tags") or []:
        t = (t or "").strip()
        if not t:
            continue
        db.execute("INSERT OR IGNORE INTO tags (name, category) VALUES (?, 'ai')", (t,))
        row = db.query_one("SELECT id FROM tags WHERE name=?", (t,))
        if row:
            db.execute(
                "INSERT OR IGNORE INTO game_tags (game_id, tag_id, source) VALUES (?,?,'ai')",
                (game["id"], row["id"]))
    if ai_extra or cand.get("provider") == "ai":
        # AI 识别已产出中文简介/标签 → 不再重复调 LLM 润色（省 token、防卡死）
        return
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
    "你是 Galgame 数据库专家，熟悉日系视觉小说全目录，可联网搜索实时资料。"
    "只输出合法 JSON，不要任何多余文字。"
)

AI_IDENTIFY_USER = """根据已知信息识别这部 Galgame，输出 JSON：
{{"title_jp": "日文原名", "title_en": "英文/罗马音名(无则空)", "title_zh": "中文常用译名(无则空)",
  "maker": "制作公司", "released": "YYYY-MM-DD(不确定给年份即可,不知道给空)",
  "tags_zh": ["3-6个中文题材标签，如 纯爱/废萌/母系/悬疑/实用/催泪"],
  "summary_zh": "80-150字中文简介", "vndb_id": "VNDB条目ID(形如v12345,不知道给空)",
  "search_queries": ["2-4条用于在 VNDB/Bangumi 检索此游戏的关键词串，优先日文原名/罗马音名/官方英文名，便于数据库精确命中；汉化或译名目录时必须给出原名，如 后宫绮梦 → [\"Kōkyū Kiteki\", \"后宫绮梦\"]"],
  "is_indie": true或false,  "confidence": 0到1的匹配置信度}}
已知信息：
目录名: {folder}
{extra}
如果这些信息不足以确定是哪个游戏，confidence 给低于 0.3，并尽量给出最可能的推测。
你可以联网搜索确认资料（尤其汉化/译名目录的真实原名、独立游戏是否有收录）。"""


def _ai_search_enabled(cfg):
    """AI 识别是否启用联网搜索接地：活动 provider 或池中任一带 search 标志。"""
    if cfg.get("provider.search"):
        return True
    for p in cfg.get("providers", []) or []:
        if p.get("enabled", True) and p.get("search"):
            return True
    return False


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
    """AI 主通道识别：目录名 + 上级目录(厂商线索) + readme + 本地封面(视觉) + 联网搜索。
    返回候选 dict 或 None；候选带 search_queries（回查双库的检索串）与 is_indie 标记。"""
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
    res, err = llm.chat_json(cfg, AI_IDENTIFY_SYSTEM, user, vision_image=vision,
                             search=_ai_search_enabled(cfg))
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
    queries = [q for q in (res.get("search_queries") or []) if (q or "").strip()][:4]
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
        "search_queries": queries,
        "is_indie": bool(res.get("is_indie")),
    }
    return cand


def _analyze_one(cfg, db, game):
    """三方互证识别流程：记忆命中 → AI 主识别(联网+识图) → AI真名回查双库 → 对账评分。

    印证规则：
    - AI 声称的 vndb_id 拉取验证成功 → 强印证，直接入库（AI 定位 + VNDB 认证）
    - 数据库候选高分（目录名/AI真名命中）→ 入库，AI 的中文译名/简介/标签合并
    - AI 高分但双库无印证 → 一律待确认（防 AI 幻觉自动入库）
    """
    from .matcher import match_ai, score_candidate
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

    # 1) AI 主识别（侦察兵）：已在 _ANALYZE_GAVE_UP 里的游戏跳过 LLM 调用
    ai_cand = None
    if game["id"] not in _ANALYZE_GAVE_UP:
        ai_cand = _ai_identify(cfg, db, game)
        if ai_cand is None:
            _ANALYZE_GAVE_UP.add(game["id"])  # 识别不出 → 本会话不再问 AI

    # AI 真名/检索串 → 回查双库（认证官）；原始目录名兜底
    folder = game["title"]
    ai_titles, ai_queries = [], []
    if ai_cand:
        ai_titles = [t for t in (ai_cand.get("title_orig"), ai_cand.get("title"))
                     if (t or "").strip()]
        ai_titles += [t for t in (ai_cand.get("aliases") or []) if (t or "").strip()]
        ai_queries = ai_cand.get("search_queries") or []
    web_cands = []
    try:
        web_cands = match_ai(cfg, folder, ai_titles, ai_queries)
    except Exception:
        pass

    # 2) 三方对账
    evidence = {}
    if ai_cand:
        evidence["ai"] = {"score": ai_cand["score"], "title": ai_cand.get("title"),
                          "vndb_id_claim": ai_cand.get("vndb_id"),
                          "is_indie": ai_cand.get("is_indie")}
    best_db = web_cands[0] if web_cands else None
    db_score = best_db["score"] if best_db else 0.0

    # S1: AI 声称的 vndb_id → 直接按 ID 拉取验证（最强印证）
    claimed_cand = None
    if ai_cand and ai_cand.get("vndb_id"):
        c, err = vndb.get(cfg, ai_cand["vndb_id"])
        if c and err is None:
            s = max([score_candidate(t, c) for t in ai_titles] + [0.0])
            if s >= 0.6:  # 拉出来的条目与 AI 真名对得上
                claimed_cand = c
                claimed_cand["score"] = max(ai_cand["score"], 0.85)
                claimed_cand["external_id"] = ai_cand["vndb_id"]
                evidence["vndb"] = {"id_claim_verified": True, "score": s}

    # S3: VNDB 与 BGM 双库互证（同一游戏两库都命中）
    cross = False
    if not claimed_cand:
        vndb_cands = [c for c in web_cands if c["provider"] == "vndb"]
        bgm_cands = [c for c in web_cands if c["provider"] == "bgm"]
        for v in vndb_cands:
            for b in bgm_cands:
                if (normalize(v.get("title_orig")) and
                        normalize(v.get("title_orig")) == normalize(b.get("title_orig"))):
                    cross = True
                    evidence.setdefault("cross", []).append((v["external_id"], b["external_id"]))
    evidence["cross"] = bool(evidence.get("cross"))

    # AI 真名命中数据库候选（S2，用于判定 AI 与 DB 是否指向同一游戏）
    ai_hit_db = bool(ai_titles) and any(
        score_candidate(t, c) >= 0.6 for t in ai_titles for c in web_cands[:3])

    ai_extra = None
    if ai_cand:
        ai_extra = {"title_zh": (ai_cand.get("title") or "").strip() or None,
                    "summary": ai_cand.get("summary") or "",
                    "tags": ai_cand.get("tags") or []}

    chosen = None
    note = ""
    if claimed_cand:
        chosen, note = claimed_cand, "AI声称ID+VNDB条目印证"
    elif best_db and db_score >= thr:
        chosen, note = best_db, f"{best_db['provider']}高分命中({db_score})"
        if cross:
            note += "+双库互证"
        if ai_hit_db:
            note += "+AI真名印证"
    elif ai_cand and ai_cand["score"] >= thr and (ai_hit_db or cross):
        chosen = best_db if (best_db and best_db["score"] >= 0.6) else ai_cand
        note = "AI高分+数据库印证"
    if chosen and chosen.get("provider") == "ai":
        ai_extra = None  # 纯 AI 入库: 字段本就来自 AI；且 _apply_match 会跳过重复润色

    # 3) 落库候选（供待确认页展示；AI 候选排前）
    db.execute("DELETE FROM match_candidates WHERE game_id=?", (game["id"],))
    cands = ([ai_cand] if ai_cand else []) + web_cands
    for i, c in enumerate(cands[:6]):
        payload = dict(c)
        if chosen and c is chosen:
            payload["evidence"] = note
        db.execute(
            "INSERT INTO match_candidates (game_id, provider, external_id, title, score, payload)"
            " VALUES (?,?,?,?,?,?)",
            (game["id"], c["provider"], c["external_id"], c.get("title") or "",
             c["score"], json.dumps(payload, ensure_ascii=False)))

    if not chosen:
        db.execute("UPDATE games SET status=1 WHERE id=?", (game["id"],))
        return {"status": 1, "reason": "no_strong_match", "evidence": evidence}

    _apply_match(cfg, db, game, chosen, async_enrich=False, ai_extra=ai_extra)
    return {"status": 2, "matched": chosen.get("title"), "score": chosen["score"],
            "evidence": evidence, "note": note}


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


def _count_missing(db):
    """exe/目录已失效的游戏数（移动/改名/删除过）。"""
    n = 0
    for g in db.query("SELECT path FROM games"):
        p = (g.get("path") or "").strip()
        if p and not os.path.isdir(p):
            n += 1
    return n


def scan_all(cfg, db):
    if STATE["running"]:
        return
    _set(running=True, stage="scan", total=0, done=0, current="", error=None,
         cancel_requested=False, last_scan=None)
    new_paths = []
    started = now_iso()
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
        # 记录扫描历史（分析完成后写，带最终状态）→ 前端"本次新增 N 款"汇总
        new_games = []
        for p in new_paths:
            g = db.query_one("SELECT id, title, path, status FROM games WHERE path=?"
                             " ORDER BY id DESC LIMIT 1", (p,))
            if g:
                new_games.append({"id": g["id"], "title": g["title"],
                                  "path": g["path"], "status": g["status"]})
        ended = now_iso()
        total = db.query_one("SELECT COUNT(*) c FROM games")["c"]
        missing = _count_missing(db)
        try:
            sh_id = db.execute(
                "INSERT INTO scan_history (started_at, ended_at, roots, new_count,"
                " total_count, missing_count, new_games) VALUES (?,?,?,?,?,?,?)",
                (started, ended, json.dumps(cfg.get("library_roots", []), ensure_ascii=False),
                 len(new_games), total, missing,
                 json.dumps(new_games, ensure_ascii=False)))
        except Exception as e:
            _log(f"扫描历史记录失败: {e}")
            sh_id = None
        _set(last_scan={"id": sh_id, "started_at": started, "ended_at": ended,
                        "new_count": len(new_games), "total_count": total,
                        "missing_count": missing, "new_games": new_games})
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
