"""制作组名称锚定：同一厂商的中/英/日文写法自动合并为一个规范名（canonical）。

数据模型：
- makers: 规范名（name 唯一，展示用）+ 可选 vndb_id（关联 VNDB producer 资料）
- maker_aliases: 每种写法(alias) → makers.id（中/英/日文变体都登记为别名）

核心规则（两条写法判定为同一厂商）：
1. 同一 vndb_id
2. 归一化键相等：ASCII(罗马音) / 汉字 任一相同
3. 模糊：kana→罗马音 转写后 difflib 相似度 ≥ 0.8（Miel / ミエル → miel/mieru 可合并）

所有写入点统一走 canonical(db, name, vndb_id)，历史脏数据由 sync_all 启动时归并。
"""
import difflib
import re

from .utils import now_iso

# ---------- 假名 → 罗马音（紧凑表：平假名自动 +0x60 扩展出片假名） ----------
_HIRA = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "を": "wo", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "ゔ": "vu",
}
_KANA = dict(_HIRA)
for _h, _r in list(_HIRA.items()):
    _KANA["".join(chr(ord(ch) + 0x60) for ch in _h)] = _r  # きゃ→キャ 等（片假名 = 平假名码点 + 0x60）
_KANA["ー"] = ""   # 长音记号：键比较时忽略
_KANA["っ"] = ""   # 促音：忽略
_KANA["ッ"] = ""

_STOPLIST = {"", "unknown", "unknown studio", "unknown developer", "未知",
             "未知厂商", "未知制作组", "其他", "other", "misc", "?", "n/a"}

_PUN = re.compile(r"[（(].*?[)）]")


def _romaji(s):
    """串内假名→罗马音，ASCII/数字原样保留小写；其他字符丢弃。"""
    out = []
    for ch in s:
        if "\u3040" <= ch <= "\u30ff":
            r = _KANA.get(ch, "")
            if r:
                out.append(r)
        elif re.match(r"[a-z0-9]", ch, re.I):
            out.append(ch.lower())
    return "".join(out)


def keys_of(name):
    """三种归一化键：ascii（纯罗马音字母数字）/ roma（假名→罗马音 + ascii）/ hanzi（纯汉字）。"""
    base = _PUN.sub("", name or "").strip()
    ascii_k = re.sub(r"[^a-z0-9]", "", base.lower())
    roma_k = _romaji(base)
    hanzi_k = re.sub(r"[^\u4e00-\u9fff]", "", base)
    return ascii_k, roma_k, hanzi_k


def is_blank(name):
    return (name or "").strip().lower() in _STOPLIST


def _same(a_ascii, a_roma, a_hanzi, b_ascii, b_roma, b_hanzi):
    """两条写法是否判定为同一厂商（不含 vndb_id 判定）。
    阈值分级：纯 ascii 对比从严(0.8，防误合并)；任一侧含假名转写的从宽(0.6，
    因为 ミエル→mieru 与官方罗马音 Miel 有系统性偏差)。"""
    if a_ascii and b_ascii and a_ascii == b_ascii:
        return True
    if a_hanzi and b_hanzi and a_hanzi == b_hanzi:
        return True
    if a_roma and b_roma and a_roma == b_roma:
        return True
    if not (a_roma and b_roma):
        return False
    a_kana = a_roma != a_ascii   # 原串含假名 → 转写后有 kana 痕迹
    b_kana = b_roma != b_ascii
    ratio = difflib.SequenceMatcher(None, a_roma, b_roma).ratio()
    if a_kana or b_kana:
        return min(len(a_roma), len(b_roma)) >= 4 and ratio >= 0.6
    return min(len(a_roma), len(b_roma)) >= 3 and ratio >= 0.8


def _find_existing(db, name, vndb_id=""):
    """按 别名精确 → 规范名精确 → 模糊扫描 → 同 vndb_id 的顺序找现成的 maker 行。
    返回 makers 行 dict 或 None。"""
    if not name:
        return None
    row = db.query_one(
        "SELECT m.* FROM maker_aliases a JOIN makers m ON m.id=a.maker_id WHERE a.alias=?",
        (name,))
    if row:
        return row
    row = db.query_one("SELECT * FROM makers WHERE name=?", (name,))
    if row:
        return row
    a_ascii, a_roma, a_hanzi = keys_of(name)
    if not (a_ascii or a_roma or a_hanzi):
        return None
    for m in db.query("SELECT * FROM makers"):
        b_ascii, b_roma, b_hanzi = keys_of(m["name"])
        if _same(a_ascii, a_roma, a_hanzi, b_ascii, b_roma, b_hanzi):
            return m
        if vndb_id and m.get("vndb_id") and m["vndb_id"] == vndb_id:
            return m
    return None


def _register_alias(db, maker_id, alias, source="auto"):
    if not alias:
        return
    db.execute(
        "INSERT OR IGNORE INTO maker_aliases (alias, maker_id, source) VALUES (?,?,?)",
        (alias, maker_id, source))


def canonical(db, name, vndb_id=""):
    """把任意写法归一到规范名：命中别名/规范名/模糊合并 → 返回规范名；否则新建。
    所有写 games.maker 的入口都必须走这里（自动锚定）。"""
    name = (name or "").strip()
    if not name:
        return ""
    existing = _find_existing(db, name, vndb_id)
    if existing:
        # 补记 vndb_id（VNDB 候选带 producer 线索时）
        if vndb_id and existing.get("vndb_id") != vndb_id:
            db.execute("UPDATE makers SET vndb_id=?, updated_at=? WHERE id=?",
                       (vndb_id, now_iso(), existing["id"]))
        _register_alias(db, existing["id"], name)
        return existing["name"]
    mid = db.execute(
        "INSERT INTO makers (name, vndb_id, updated_at) VALUES (?,?,?)",
        (name, vndb_id or None, now_iso()))
    _register_alias(db, mid, name, source="created")
    return name


def _rename(db, maker_id, new_name):
    """改规范名：旧名降级为别名，保持别名集合完整。
    目标名已被其他厂商占用时跳过（防 UNIQUE 冲突）。"""
    old = db.query_one("SELECT * FROM makers WHERE id=?", (maker_id,))
    if not old or old["name"] == new_name or not new_name:
        return
    if db.query_one("SELECT 1 FROM makers WHERE name=? AND id!=?", (new_name, maker_id)):
        return
    if db.query_one("SELECT 1 FROM maker_aliases WHERE alias=? AND maker_id!=?",
                    (new_name, maker_id)):
        return
    db.execute("UPDATE makers SET name=?, updated_at=? WHERE id=?",
               (new_name, now_iso(), maker_id))
    _register_alias(db, maker_id, old["name"])


def sync_all(db):
    """启动归并：把 games.maker / producer_map / maker_follows 里的历史脏写法统一。
    幂等；规范名取出现次数最多的写法；producer_map.display_name（用户手动指定过）
    优先作为规范名（用户更正的必须回显，见 #33）。"""
    counts = {}
    for r in db.query("SELECT maker FROM games WHERE maker IS NOT NULL AND maker!=''"):
        m = (r["maker"] or "").strip()
        if m and not is_blank(m):
            counts[m] = counts.get(m, 0) + 1
    for t in ("producer_map", "maker_follows"):
        for r in db.query(f"SELECT maker_name AS name FROM {t}"):
            m = (r["name"] or "").strip()
            if m and not is_blank(m):
                counts[m] = counts.get(m, 0) + 1
    # 出现多 → 先锚定，让高频写法成为规范名（同组内先到先得）
    order = sorted(counts, key=lambda k: (-counts[k], k))
    for name in order:
        canonical(db, name)
    # producer_map.display_name 是用户手动指定过的显示名 → 覆盖为规范名。
    # 同一 canonical 可能有多条 pm 行（用户先后更正过多个写法）：每次 sync 每行只改一次名，
    # 按 updated_at 倒序让「最后一次更正」生效（避免后行覆盖前行）。
    renamed = set()
    for r in db.query(
            "SELECT maker_name, display_name, vndb_id, updated_at FROM producer_map"
            " ORDER BY updated_at DESC"):
        disp = (r.get("display_name") or "").strip()
        if not disp or is_blank(disp):
            continue
        row = db.query_one(
            "SELECT m.* FROM maker_aliases a JOIN makers m ON m.id=a.maker_id WHERE a.alias=?",
            (r["maker_name"],))
        if row and row["name"] != disp and row["id"] not in renamed:
            _rename(db, row["id"], disp)
            renamed.add(row["id"])
    # 用别名集合回写 games.maker：所有挂在同一 canonical 下的写法 → 规范名
    groups = {}
    for a in db.query(
            "SELECT a.alias, m.name FROM maker_aliases a JOIN makers m ON m.id=a.maker_id"):
        groups.setdefault(a["name"], []).append(a["alias"])
    for canon, aliases in groups.items():
        for al in aliases:
            if al == canon:
                continue
            db.execute("UPDATE games SET maker=? WHERE maker=?", (canon, al))
            # maker_follows / producer_map 主键都是 maker_name：规范行已存在则删别名行，
            # 否则改名（不能直接 UPDATE，两条别名归一时会撞 UNIQUE 约束）
            if db.query_one("SELECT 1 FROM maker_follows WHERE maker_name=?", (canon,)):
                db.execute("DELETE FROM maker_follows WHERE maker_name=?", (al,))
            else:
                db.execute("UPDATE maker_follows SET maker_name=? WHERE maker_name=?", (canon, al))
            pm = db.query_one("SELECT vndb_id, display_name FROM producer_map WHERE maker_name=?",
                              (al,))
            if pm:
                existing = db.query_one(
                    "SELECT vndb_id FROM producer_map WHERE maker_name=?", (canon,))
                if existing:
                    if not existing.get("vndb_id") and pm.get("vndb_id"):
                        db.execute("UPDATE producer_map SET vndb_id=? WHERE maker_name=?",
                                   (pm["vndb_id"], canon))
                else:
                    db.execute(
                        "INSERT OR REPLACE INTO producer_map (maker_name, vndb_id, display_name, updated_at)"
                        " VALUES (?,?,?,?)",
                        (canon, pm.get("vndb_id") or None, pm.get("display_name") or canon, now_iso()))
                db.execute("DELETE FROM producer_map WHERE maker_name=?", (al,))


def merge_makers(db, src, dst, vndb_id=""):
    """用户手动合并：src 的所有游戏/关注/别名 → dst（dst 不存在则新建）。
    返回 (ok, 规范名, 错误)。"""
    src = (src or "").strip()
    dst = (dst or "").strip()
    if not src or not dst:
        return False, "", "厂商名不能为空"
    if src == dst:
        return False, "", "来源与目标相同"
    target = canonical(db, dst, vndb_id)
    trow = db.query_one("SELECT * FROM makers WHERE name=?", (target,))
    # 若 src 已有独立 maker 行 → 别名并入目标后删旧行
    src_row = db.query_one(
        "SELECT m.* FROM maker_aliases a JOIN makers m ON m.id=a.maker_id WHERE a.alias=?",
        (src,)) or db.query_one("SELECT * FROM makers WHERE name=?", (src,))
    if src_row and trow and src_row["id"] != trow["id"]:
        db.execute("UPDATE maker_aliases SET maker_id=? WHERE maker_id=?",
                   (trow["id"], src_row["id"]))
        db.execute("DELETE FROM makers WHERE id=?", (src_row["id"],))
    if trow:
        _register_alias(db, trow["id"], src, source="manual")
    db.execute("UPDATE games SET maker=? WHERE maker=?", (target, src))
    # follows 主键=maker_name：目标已关注则删来源行，否则改名（防 UNIQUE 冲突）
    if db.query_one("SELECT 1 FROM maker_follows WHERE maker_name=?", (target,)):
        db.execute("DELETE FROM maker_follows WHERE maker_name=?", (src,))
    else:
        db.execute("UPDATE maker_follows SET maker_name=? WHERE maker_name=?", (target, src))
    db.execute("DELETE FROM producer_map WHERE maker_name=?", (src,))
    db.execute(
        "INSERT OR REPLACE INTO producer_map (maker_name, vndb_id, display_name, updated_at)"
        " VALUES (?,?,?,?)", (target, vndb_id or None, target, now_iso()))
    return True, target, ""


def register_aliases(db, name, aliases, source="vndb"):
    """把外部来源（VNDB producer aliases 等）的写法登记为 name 的别名。
    VNDB 厂商别名常同时含中/英/日写法 → 之后任何来源写入该厂商都会自动归一。"""
    canon = canonical(db, name)
    if not canon:
        return canon
    row = db.query_one("SELECT id FROM makers WHERE name=?", (canon,))
    if not row:
        return canon
    for al in aliases or []:
        al = (al or "").strip()
        if al and al != canon and not is_blank(al):
            _register_alias(db, row["id"], al, source)
    return canon


def list_makers(db):
    """全部规范厂商（合并 UI / 排序用）：游戏数 + 别名集合 + vndb_id。"""
    out = []
    for m in db.query("SELECT * FROM makers ORDER BY name"):
        aliases = [a["alias"] for a in db.query(
            "SELECT alias FROM maker_aliases WHERE maker_id=? AND alias!=?",
            (m["id"], m["name"]))]
        cnt = db.query_one("SELECT COUNT(*) c FROM games WHERE maker=?", (m["name"],))
        out.append({
            "name": m["name"], "vndb_id": m.get("vndb_id"),
            "count": cnt["c"] if cnt else 0, "aliases": aliases[:12],
        })
    out.sort(key=lambda x: (-x["count"], x["name"]))
    return out
