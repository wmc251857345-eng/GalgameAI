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
    """bgm(直连) + vndb(有 token 时)。"""
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
