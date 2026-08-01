"""VNDB API v2 (api.vndb.org/kana) — 结构化最全（时长/评分/别名/标签），需免费 token。"""
from ..utils import http_post_json, http_session

API = "https://api.vndb.org/kana"

_FIELDS = (
    "title,alttitle,titles.title,titles.lang,titles.latin,aliases,released,"
    "developers.name,image.url,length,length_minutes,rating,description,"
    "tags.name,tags.spoiler,tags.rating"
)


def search(cfg, keyword, limit=8):
    """搜索 VN，返回 (candidates, error)。未配 token 时 error 提示。"""
    token = cfg.get("vndb_token", "")
    if not token:
        return [], "未配置 VNDB token（设置页填写，可选）"
    s = http_session(cfg, proxy_ok=True)
    body = {
        "filters": ["search", "=", keyword],
        "fields": _FIELDS,
        "sort": "searchrank",
        "results": limit,
    }
    try:
        data = http_post_json(
            s, f"{API}/vn", json_body=body, timeout=20,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Token {token}"})
    except Exception as e:
        return [], f"VNDB 请求失败: {e}"
    out = []
    for v in data.get("results", []):
        img = v.get("image") or {}
        devs = [d.get("name", "") for d in (v.get("developers") or [])]
        ja_title = next((t.get("title") for t in (v.get("titles") or [])
                         if t.get("lang") == "ja"), v.get("title", ""))
        out.append({
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
        })
    return out, None
