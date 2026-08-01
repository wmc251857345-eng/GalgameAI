"""VNDB API v2 (api.vndb.org/kana) — 结构化最全（时长/评分/别名/标签），需免费 token。"""
from ..utils import http_post_json, http_session

API = "https://api.vndb.org/kana"

_FIELDS = (
    "title,alttitle,titles.title,titles.lang,titles.latin,aliases,released,"
    "developers.name,image.url,length,length_minutes,rating,description,"
    "tags.name,tags.spoiler,tags.rating"
)


def _query(cfg, body):
    """POST VNDB API，返回 results 列表。"""
    token = cfg.get("vndb_token", "")
    if not token:
        return [], "未配置 VNDB token（设置页填写，可选）"
    s = http_session(cfg, proxy_ok=True)
    try:
        data = http_post_json(
            s, f"{API}/vn", json_body=body, timeout=20,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Token {token}"})
    except Exception as e:
        return [], f"VNDB 请求失败: {e}"
    return data.get("results", []), None


def _to_candidate(v):
    img = v.get("image") or {}
    devs = [d.get("name", "") for d in (v.get("developers") or [])]
    ja_title = next((t.get("title") for t in (v.get("titles") or [])
                     if t.get("lang") == "ja"), v.get("title", ""))
    return {
        "provider": "vndb",
        "external_id": v.get("id", ""),
        "title": v.get("title", ""),
        "title_orig": ja_title,
        "aliases": (v.get("aliases") or [])[:10],
        "maker": " / ".join(devs),
        "released": (v.get("released") or "")[:10],
        "rating": v.get("rating"),
        "cover_url": img.get("url", ""),
        "summary": (v.get("description") or "")[:800],
        "tags": [t.get("name", "") for t in (v.get("tags") or [])
                 if t.get("rating", 0) >= 0.5][:10],
        "length_level": v.get("length"),
        "length_minutes": v.get("length_minutes"),
    }


def search(cfg, keyword, limit=8):
    results, err = _query(cfg, {
        "filters": ["search", "=", keyword],
        "fields": _FIELDS, "sort": "searchrank", "results": limit,
    })
    if err:
        return [], err
    return [_to_candidate(v) for v in results], None


def get(cfg, vndb_id):
    """按 ID 精确获取（用于已入库游戏刷新信息）。"""
    results, err = _query(cfg, {
        "filters": ["id", "=", vndb_id],
        "fields": _FIELDS, "results": 1,
    })
    if err or not results:
        return None, err
    return _to_candidate(results[0]), None
