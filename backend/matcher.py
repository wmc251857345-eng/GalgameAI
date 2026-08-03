"""匹配器：本地目录名 → bgm/vndb 候选 + 多策略打分。

策略：规范化全等(1.0) > 互相包含(0.88) > 字符 Jaccard 相似度(0.35~0.9)
"""
import re

from .utils import normalize
from . import providers


def _clean_query(folder):
    """去掉汉化标记/括号注释/版本号等噪音。"""
    q = folder
    q = re.sub(r"[（(][^）)]*汉化[^）)]*[)）]", "", q)
    q = re.sub(r"_(?:chs|cn|patch|汉化)$", "", q, flags=re.I)
    q = re.sub(r"\s*[\[(【].{0,12}[)\】]]\s*$", "", q).strip()
    return q or folder


def char_jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def score_candidate(query, cand):
    """对单个候选打分：取所有可用标题/别名中的最高分。"""
    q = normalize(query)
    if not q:
        return 0.0
    titles = [cand.get("title"), cand.get("title_orig")]
    titles += list(cand.get("aliases") or [])
    best = 0.0
    for t in titles:
        tn = normalize(t)
        if not tn:
            continue
        if tn == q:
            best = max(best, 1.0)
        elif tn in q or q in tn:
            best = max(best, 0.88)
        else:
            j = char_jaccard(q, tn)
            score = 0.35 + 0.55 * j
            if max(len(q), len(tn)) > 12:
                score = min(score, 0.9)
            best = max(best, score)
    return round(min(best, 1.0), 3)


def search_candidates(cfg, query):
    """bgm(直连) + vndb(有 token 时) + steam(免 token)。"""
    cands = []
    try:
        cands += providers.bgm.search(cfg, query)
    except Exception:
        pass
    try:
        res, _ = providers.vndb.search(cfg, query)
        cands += res
    except Exception:
        pass
    try:
        cands += providers.steam.search(cfg, query)
    except Exception:
        pass
    return cands


def match(cfg, query):
    """完整匹配：搜索 + 打分 + 排序。"""
    cands = search_candidates(cfg, _clean_query(query))
    if not cands:  # 清理后没结果 → 用原名再试一次
        cands = search_candidates(cfg, query)
    for c in cands:
        c["score"] = score_candidate(query, c)
    cands.sort(key=lambda c: c["score"], reverse=True)
    return cands


def match_ai(cfg, folder, ai_titles=None, ai_queries=None):
    """三方互证检索：AI 识别的真名/检索串优先回查 bgm/vndb/steam，
    原始目录名兜底；候选同时对着【AI 真名】与【原始目录名】打分。

    - folder: 原始目录名（兜底查询 + 打分基准）
    - ai_titles: AI 识别出的 [title_jp, title_en, title_zh]（打分基准）
    - ai_queries: AI 建议的检索串（优先查询词，最多 4 条）
    返回去重后的候选列表（按分降序），每个候选带 matched_key 标记命中的基准。
    """
    queries = []
    for q in list(ai_queries or [])[:4]:
        q = (q or "").strip()
        if q and q not in queries:
            queries.append(q)
    if folder and folder not in queries:
        queries.append(folder)

    seen, out = set(), []
    for q in queries:
        for c in search_candidates(cfg, q):
            key = (c.get("provider"), c.get("external_id"))
            if key in seen:
                continue
            seen.add(key)
            out.append(c)

    bases = [t for t in (ai_titles or []) if (t or "").strip()]
    bases.append(folder)
    for c in out:
        best, best_key = 0.0, ""
        for b in bases:
            s = score_candidate(b, c)
            if s > best:
                best, best_key = s, b
        c["score"] = best
        c["matched_key"] = best_key
    out.sort(key=lambda c: c["score"], reverse=True)
    return out
