"""Bangumi API (api.bgm.tv) — 国内直连、中文数据，搜索无需 token。"""
from ..utils import http_get_json, http_session

API = "https://api.bgm.tv"

_unreachable = False  # 熔断：不可达后本次会话不再尝试


def search(cfg, keyword, limit=8):
    """搜索游戏类条目(type=4)，返回统一候选结构。"""
    global _unreachable
    if _unreachable:
        return []
    s = http_session(cfg, proxy_ok=True)  # 跟随代理设置（国内直连可能被 DNS 污染）
    try:
        data = http_get_json(
            s, f"{API}/search/subject/{keyword}",
            params={"type": 4, "responseGroup": "large"}, timeout=8, tries=1)
    except Exception:
        _unreachable = True  # 网络不通 → 熔断
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data[:limit]:
        images = item.get("images") or {}
        producers = item.get("producer")
        maker = ""
        if isinstance(producers, list) and producers:
            maker = (producers[0].get("name") or "")
        out.append({
            "provider": "bgm",
            "external_id": str(item.get("id", "")),
            "title": item.get("name_cn") or item.get("name") or "",
            "title_orig": item.get("name") or "",
            "aliases": [],
            "maker": maker,
            "released": (item.get("date") or "")[:10],
            "rating": (item.get("rating") or {}).get("score"),
            "cover_url": images.get("large") or images.get("common") or "",
            "summary": (item.get("summary") or "")[:800],
            "tags": [t.get("name", "") for t in (item.get("tags") or [])][:10],
        })
    return out
