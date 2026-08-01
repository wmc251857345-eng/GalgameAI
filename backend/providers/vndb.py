"""VNDB API v2 (api.vndb.org/kana) — 结构化最全（时长/评分/别名/标签），需免费 token。"""
from ..utils import http_post_json, http_session

API = "https://api.vndb.org/kana"

_FIELDS = (
    "title,alttitle,titles.title,titles.lang,titles.latin,aliases,released,"
    "developers.name,image.url,length,length_minutes,rating,description,"
    "tags.name,tags.spoiler,tags.rating"
)


def _query(cfg, body, timeout=15, tries=2):
    """POST VNDB API，返回 results 列表。（快失败：15s×2，避免桥接线程长时间挂起）"""
    token = cfg.get("vndb_token", "")
    if not token:
        return [], "未配置 VNDB token（设置页填写，可选）"
    s = http_session(cfg, proxy_ok=True)
    try:
        data = http_post_json(
            s, f"{API}/vn", json_body=body, timeout=timeout, tries=tries,
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


# 单条目查询 TTL 缓存（6 小时）：作品详情反复打开不重复打 VNDB（限速/卡慢主因）
_get_cache = {}
_GET_TTL = 6 * 3600


def get(cfg, vndb_id):
    """按 ID 精确获取（用于已入库游戏刷新信息）。6h TTL 缓存。"""
    import time
    now = time.time()
    hit = _get_cache.get(vndb_id)
    if hit and now - hit[0] < _GET_TTL:
        return hit[1], None
    results, err = _query(cfg, {
        "filters": ["id", "=", vndb_id],
        "fields": _FIELDS, "results": 1,
    })
    if err or not results:
        return None, err
    cand = _to_candidate(results[0])
    _get_cache[vndb_id] = (now, cand)
    return cand, None


# ---------- 厂商 / 系列追踪 ----------

_VN_LIST_FIELDS = (
    "id,title,titles.title,titles.lang,released,image.url,rating,length,"
    "tags.name,relations.id,relations.title,relations.relation"
)


def get_producer(cfg, name):
    """按名称搜索厂商（VNDB producer），返回 {id,name,aliases,description,type} 或 None。
    关键词自动展开：全名 → 去括号 → 纯英文 → 纯日文 → 拆词，取第一个有结果的。"""
    kws = _producer_keywords(name)
    last = None
    for kw in kws:
        prod, err = _producer_search(cfg, kw)
        if err:
            last = err
            continue
        if prod:
            return prod, None
    if last:
        return None, last
    return None, None


def _producer_keywords(name):
    """厂商名关键词展开：Miel (ミエル) → [Miel (ミエル), Miel, ミエル] 等。"""
    import re
    kws = [name.strip()]
    base = re.sub(r"[（(].*?[)）]", "", name).strip()
    if base and base not in kws:
        kws.append(base)
    en = " ".join(re.findall(r"[A-Za-z][A-Za-z0-9 .\-']*", name)).strip()
    if en and en not in kws:
        kws.append(en)
    ja = re.sub(r"[^\u3040-\u30ff\u4e00-\u9fff]", "", name)
    if ja and ja not in kws:
        kws.append(ja)
    for tok in re.split(r"[\s（）()/・、,，]+", base):
        tok = tok.strip()
        if len(tok) >= 2 and tok not in kws:
            kws.append(tok)
    return kws[:6]


def _producer_search(cfg, keyword):
    """单关键词搜 producer，返回最佳匹配（名称/别名精确匹配优先）。"""
    import time
    time.sleep(0.12)  # 节流：关键词展开可能连续多次请求，防 VNDB 限速
    token = cfg.get("vndb_token", "")
    if not token:
        return None, "未配置 VNDB token"
    s = http_session(cfg, proxy_ok=True)
    try:
        data = http_post_json(
            s, f"{API}/producer",
            json_body={"filters": ["search", "=", keyword],
                       "fields": "id,name,aliases,description,type",
                       "sort": "searchrank", "results": 8},
            timeout=20,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Token {token}"})
    except Exception as e:
        return None, f"VNDB 请求失败: {e}"
    results = data.get("results", [])
    if not results:
        return None, None
    kw_l = keyword.lower()
    best = next((r for r in results if r.get("name", "").lower() == kw_l), None)
    if not best:
        best = next((r for r in results if kw_l in (a.lower() for a in (r.get("aliases") or []))), None)
    if not best:
        best = results[0]
    return {
        "id": best.get("id", ""),
        "name": best.get("name", ""),
        "aliases": (best.get("aliases") or [])[:8],
        "description": (best.get("description") or "")[:1000],
        "type": best.get("type", ""),
    }, None


def search_producers(cfg, keyword, limit=8):
    """给用户手动更正的候选列表。"""
    token = cfg.get("vndb_token", "")
    if not token:
        return [], "未配置 VNDB token"
    s = http_session(cfg, proxy_ok=True)
    try:
        data = http_post_json(
            s, f"{API}/producer",
            json_body={"filters": ["search", "=", keyword],
                       "fields": "id,name,aliases,type",
                       "sort": "searchrank", "results": limit},
            timeout=20,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Token {token}"})
    except Exception as e:
        return [], f"VNDB 请求失败: {e}"
    return [{"id": r.get("id", ""), "name": r.get("name", ""),
             "aliases": (r.get("aliases") or [])[:6], "type": r.get("type", "")}
            for r in data.get("results", [])], None


def _vn_list(cfg, filters, limit=50):
    """按过滤条件取 VN 列表，含排序（发售日倒序）+分页。"""
    token = cfg.get("vndb_token", "")
    if not token:
        return [], "未配置 VNDB token"
    s = http_session(cfg, proxy_ok=True)
    out = []
    page = 1
    while len(out) < limit and page <= 3:
        try:
            data = http_post_json(
                s, f"{API}/vn",
                json_body={"filters": filters,
                           "fields": _VN_LIST_FIELDS,
                           "sort": "released", "reverse": True,
                           "results": min(50, limit), "page": page},
                timeout=20,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Token {token}"})
        except Exception as e:
            return out, f"VNDB 请求失败: {e}"
        results = data.get("results", [])
        if not results:
            break
        for v in results:
            if len(out) >= limit:
                break
            img = v.get("image") or {}
            ja = next((t.get("title") for t in (v.get("titles") or [])
                       if t.get("lang") == "ja"), v.get("title", ""))
            rels = [{"id": rv.get("id"), "title": rv.get("title"),
                     "relation": rv.get("relation")}
                    for rv in (v.get("relations") or [])]
            out.append({
                "id": v.get("id", ""),
                "title": v.get("title", ""),
                "title_jp": ja,
                "released": (v.get("released") or "")[:10],
                "cover_url": img.get("url", ""),
                "rating": v.get("rating"),
                "length_level": v.get("length"),
                "relations": rels,
                "tags": [t.get("name", "") for t in (v.get("tags") or [])][:12],
            })
        if len(results) < 50:
            break
        page += 1
    return out, None


def get_producer_vns(cfg, pid):
    """该厂商的全部作品（按发售日倒序）。
    VNDB 的"厂商"关系经由 release.producer 表达，需嵌套过滤器。"""
    return _vn_list(cfg, ["release", "=", ["producer", "=", ["id", "=", pid]]])


def get_series(cfg, anchor_id):
    """系列/前作全家桶：以锚点 VN 为基准，收集家族关系（ser 同系列/seq 续作/preq 前作/
    side 外传/fan 粉丝盘/alt 换版/par 平行/set 同设定/orig 原作）的 VN。
    VNDB v2 没有 series 字段，家族关系通过 relations 表达。"""
    token = cfg.get("vndb_token", "")
    if not token:
        return [], None, "未配置 VNDB token"
    _FAMILY = {"ser", "seq", "preq", "side", "fan", "alt", "par", "set", "orig"}
    s = http_session(cfg, proxy_ok=True)
    try:
        data = http_post_json(
            s, f"{API}/vn",
            json_body={"filters": ["id", "=", anchor_id],
                       "fields": "id,title,relations.id,relations.title,relations.relation",
                       "results": 1},
            timeout=20,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Token {token}"})
    except Exception as e:
        return [], None, f"VNDB 请求失败: {e}"
    results = data.get("results", [])
    if not results:
        return [], None, f"VNDB 没有找到条目 {anchor_id}"
    anchor = results[0]
    fam_ids = [anchor_id]
    for r in (anchor.get("relations") or []):
        if r.get("relation") in _FAMILY:
            fam_ids.append(r.get("id"))
    fam_ids = list(dict.fromkeys(fam_ids))  # 去重保序
    works, err = _vn_list(cfg, ["or"] + [["id", "=", i] for i in fam_ids])
    if err:
        return [], None, err
    return works, anchor.get("title"), None
