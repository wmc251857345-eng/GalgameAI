"""Steam Store API — 免 token 补充渠道（galgame 现多上架 Steam，VNDB/BGM 无记录的厂商在这里能搜到）。

- 搜索: store.steampowered.com/api/storesearch （返回 appid + 本地化名）
- 详情: store.steampowered.com/api/appdetails （厂商/发售日/简介/类型）
- 封面: cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg （2:3，正好做封面）

快失败策略与其他 provider 一致：单次请求 12s、不重试，避免桥接线程长时间挂起。
"""
import re
import time

from ..utils import http_get_json, http_session

SEARCH_API = "https://store.steampowered.com/api/storesearch/"
DETAIL_API = "https://store.steampowered.com/api/appdetails/"
CDN = "https://cdn.akamai.steamstatic.com/steam/apps"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_date(s):
    """Steam 日期字符串 → YYYY-MM-DD / YYYY（兼容 schinese 与英文两种格式）。"""
    if not s:
        return ""
    t = str(s).strip()
    m = re.search(r"(\d{4})\s*年(?:\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?)?", t)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        return f"{y}-{int(mo):02d}-{int(d):02d}" if (mo and d) else (f"{y}-{int(mo):02d}" if mo else y)
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[\.,]?\s+(\d{4})", t)
    if m and m.group(2).lower()[:3] in _MONTHS:
        d, mo, y = m.group(1), _MONTHS[m.group(2).lower()[:3]], m.group(3)
        return f"{y}-{mo:02d}-{int(d):02d}"
    m = re.search(r"([A-Za-z]{3})[\.,]?\s+(\d{1,2})[\.,]?\s+(\d{4})", t)
    if m and m.group(1).lower()[:3] in _MONTHS:
        mo, d, y = _MONTHS[m.group(1).lower()[:3]], m.group(2), m.group(3)
        return f"{y}-{mo:02d}-{int(d):02d}"
    m = re.search(r"(\d{4})", t)
    return m.group(1) if m else ""


def _candidate(appid, name, data):
    """appdetails data → 统一候选结构（与 vndb/bgm 对齐）。"""
    devs = [d for d in (data.get("developers") or []) if d]
    mc = (data.get("metacritic") or {}).get("score")
    return {
        "provider": "steam",
        "external_id": str(appid),
        "title": name or data.get("name") or "",
        "title_orig": data.get("name") or name or "",
        "aliases": [],
        "maker": " / ".join(devs),
        "released": _parse_date((data.get("release_date") or {}).get("date")),
        "rating": mc,          # Metacritic 0-100，显示端统一转 10 分制
        "cover_url": f"{CDN}/{appid}/library_600x900.jpg",
        "summary": (data.get("short_description") or "")[:800],
        "tags": [g.get("description", "") for g in (data.get("genres") or [])
                 if g.get("description")][:10],
    }


def _details(s, appid, timeout=12):
    """单 app 详情（快失败 12s×1）。失败返回 None。
    注意：不能加 filters=basic —— 它会裁掉 developers/release_date/genres 等关键字段。"""
    try:
        data = http_get_json(
            s, DETAIL_API,
            params={"appids": appid, "l": "schinese", "cc": "CN"},
            timeout=timeout, tries=1)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    entry = data.get(str(appid)) or {}
    if not entry.get("success"):
        return None
    d = entry.get("data")
    if not isinstance(d, dict) or d.get("type") not in ("game", "demo"):
        return None  # 只收游戏（过滤软件/原声带/DLC 等噪音）
    return d


# 单条目查询 TTL 缓存（6 小时，与 vndb 一致）
_get_cache = {}
_GET_TTL = 6 * 3600


def get(cfg, appid):
    """按 appid 精确获取（已入库刷新/匹配记忆命中）。6h TTL 缓存。"""
    appid = str(appid or "").strip()
    if not appid:
        return None, None
    now = time.time()
    hit = _get_cache.get(appid)
    if hit and now - hit[0] < _GET_TTL:
        return hit[1], None
    s = http_session(cfg, proxy_ok=True)
    d = _details(s, appid)
    if not d:
        return None, "Steam 无此 appid"
    cand = _candidate(appid, d.get("name") or "", d)
    _get_cache[appid] = (now, cand)
    return cand, None


def search(cfg, keyword, limit=6):
    """搜索 Steam 游戏，返回统一候选结构列表（storesearch + 逐个 appdetails 补厂商/日期）。"""
    kw = (keyword or "").strip()
    if not kw:
        return []
    s = http_session(cfg, proxy_ok=True)
    try:
        data = http_get_json(
            s, SEARCH_API,
            params={"term": kw, "l": "schinese", "cc": "CN"},
            timeout=12, tries=1)
    except Exception:
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not items:
        return []
    out = []
    for it in items[:limit + 4]:
        if it.get("type") != "app":
            continue
        appid = it.get("id")
        name = it.get("name") or ""
        if not appid:
            continue
        d = _details(s, appid)
        if not d:
            continue
        out.append(_candidate(appid, name, d))
        if len(out) >= limit:
            break
        time.sleep(0.15)  # 节流：逐个拉详情，防 Steam 限速
    return out
