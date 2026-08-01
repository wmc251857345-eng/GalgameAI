"""分析流水线：匹配 → 自动确认/待确认 → 封面下载 → AI 中文简介/标签。
全局进度 STATE 供前端轮询；可断点续跑（status 0/1 的游戏重跑即可）。
"""
import json
import os
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


def _apply_match(cfg, db, game, cand):
    """把候选应用到 game：填字段、下载封面、AI 中文化。"""
    cover_path = download_cover(cfg, game["id"], cand.get("cover_url"),
                                game.get("cover_local"))
    bgm_id = int(cand["external_id"]) if cand["provider"] == "bgm" and cand["external_id"].isdigit() else None
    vndb_id = cand["external_id"] if cand["provider"] == "vndb" else None
    rating = cand.get("rating")
    if isinstance(rating, (int, float)) and rating > 20:  # VNDB 0-100 → 统一 10 分制
        rating = round(rating / 10, 2)
    db.execute(
        """UPDATE games SET title=?, title_en=?, title_jp=?, maker=?, released=?,
           rating=?, description=?, cover_path=?, cover_url=?, vndb_id=?, bgm_id=?,
           length_level=?, length_minutes=?, status=2, match_confidence=?, source=?
           WHERE id=?""",
        (cand.get("title") or game["title"],
         cand.get("title") or "", cand.get("title_orig") or "",
         cand.get("maker") or "", cand.get("released") or "",
         rating, cand.get("summary") or "",
         cover_path, cand.get("cover_url") or "",
         vndb_id, bgm_id,
         cand.get("length_level"), cand.get("length_minutes"),
         cand["score"], cand["provider"], game["id"]))
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


def _ai_identify(cfg, db, game):
    """AI 主通道识别：目录名 + readme + 本地封面(视觉)。返回候选 dict 或 None。"""
    from .providers import llm
    extra = []
    text = (game.get("text_sample") or "").strip()
    if text:
        extra.append(f"本地文件信息:\n{text[:800]}")
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
    """AI 识别为主，bgm/vndb 尽力而为。"""
    from .matcher import match
    thr = cfg.get("analysis.auto_confirm_threshold", 0.9)

    ai_cand = _ai_identify(cfg, db, game)
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


def scan_all(cfg, db):
    if STATE["running"]:
        return
    _set(running=True, stage="scan", total=0, done=0, current="", error=None, log=[])
    try:
        from .scanner import scan_root
        roots = cfg.get("library_roots", [])
        for root in roots:
            if not os.path.isdir(root):
                _log(f"跳过不存在的目录: {root}")
                continue
            _set(current=f"扫描 {root}")
            found = scan_root(root, db)
            _log(f"扫描 {root}: 新增 {len(found)} 个游戏")
    except Exception as e:
        _set(error=str(e))
    finally:
        _set(running=False, stage="idle", current="")


def analyze_all(cfg, db):
    if STATE["running"]:
        return
    _set(running=True, stage="analyze", total=0, done=0, current="", error=None)
    try:
        games = db.query("SELECT * FROM games WHERE status IN (0,1) ORDER BY id")
        _set(total=len(games))
        for i, g in enumerate(games, 1):
            if not STATE["running"]:  # 允许停止
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
    """批量补封面：status=2 且无本地封面的游戏，vndb_id 精确取 → bgm 搜索兜底。"""
    if STATE["running"]:
        return
    _set(running=True, stage="covers", total=0, done=0, current="", error=None)
    try:
        from .providers import bgm, vndb
        games = db.query(
            "SELECT * FROM games WHERE status=2 AND (cover_path IS NULL OR cover_path='') ORDER BY id")
        _set(total=len(games))
        done = 0
        for g in games:
            if not STATE["running"]:
                break
            _set(current=g["title"], done=done)
            url = None
            if g.get("vndb_id"):
                cand, _ = vndb.get(cfg, g["vndb_id"])
                if cand and cand.get("cover_url"):
                    url = cand["cover_url"]
            if not url:
                try:
                    cands = bgm.search(cfg, g.get("title") or g.get("title_jp") or "")
                    if cands and cands[0].get("cover_url"):
                        url = cands[0]["cover_url"]
                except Exception:
                    pass
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
