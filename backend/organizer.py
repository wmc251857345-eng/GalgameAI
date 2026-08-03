"""自动整理引擎：把散落在库根/【PC】包装层的新游戏，按用户习惯移入品牌桶。

核心思路——"从现有结构学习习惯"：
- 扫描库根下已存在的桶（含 ≥2 款游戏或受保护名），统计每个厂商在哪个桶里
  游戏最多 → 建立 maker→bucket 映射。例：Atelier_Kaguya 桶里装着
  Atelier Kaguya / Miel / LiLiTH / Azarashi Soft 的游戏 → 这些厂商的新游戏
  全部归入 Atelier_Kaguya，而不是每个厂商另建一桶（避免破坏品牌家族分组）。
- 未学到的厂商 → 自动建桶（纯 ASCII/罗马音目录名 + desktop.ini 中文马甲，
  遵循 windows-folder-magic 习惯）；厂商未知 → Uncategorized 兜底。
- 只移动"未整理"的游戏：库根直挂、或挂在非桶的包装层（如【PC】xxx）下。
  已入桶的游戏绝不移动（幂等，防误动）。

安全：同盘 rename、目标冲突加后缀/跳过、移动后同步更新 DB 的
path/exe_path/workdir/cover_local，全程 dry-run 可预览。
"""
import json
import os
import re

from .utils import now_iso

# 受保护桶：即使只有 1 款游戏也算桶（用户手工建的归类目录）
PROTECTED_BUCKETS = {
    "uncategorized", "unclassified", "misc", "other", "未分类", "其他",
    "independent_rpg_slg", "independent rpg slg", "rpg", "slg", "steam",
}

_PC_WRAP = re.compile(r"^【pc】", re.I)          # 【PC】包装前缀
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')  # Windows 非法字符


def _bucket_slug(name):
    """厂商名 → 桶目录名：纯 ASCII（日文转罗马音），空格/斜杠 → 下划线。"""
    from .makers import _romaji
    n = (name or "").strip()
    if not n:
        return ""
    if any(ord(c) > 0x7f for c in n):  # 含日文/中文 → 罗马音/ASCII 化
        n = _romaji(n) or ""
    n = _INVALID.sub("", n)
    n = re.sub(r"[\s/\\]+", "_", n)
    n = n.strip("_.") or ""
    return n


def _is_bucket(parent_name):
    return (parent_name or "").lower() in PROTECTED_BUCKETS


def _detect_buckets(db, root):
    """学习库根下现有桶：子目录 + 各桶内游戏数 + 桶内厂商分布。
    桶判定：有 desktop.ini（用户手工建的桶的强信号）或含 ≥2 款游戏或受保护名。"""
    buckets = {}  # bucket名(小写) → {"display": 原名, "games": n, "makers": {maker: count}}
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return buckets
    for e in entries:
        p = os.path.join(root, e)
        if not os.path.isdir(p) or e.startswith((".", "$")):
            continue
        n = db.query_one(
            "SELECT COUNT(*) c FROM games WHERE path LIKE ?",
            (p + os.sep + "%",))
        cnt = n["c"] if n else 0
        has_ini = os.path.exists(os.path.join(p, "desktop.ini"))
        if cnt < 2 and not has_ini and e.lower() not in PROTECTED_BUCKETS:
            continue
        makers = {}
        for g in db.query("SELECT maker FROM games WHERE path LIKE ?",
                          (p + os.sep + "%",)):
            m = (g.get("maker") or "").strip()
            if m:
                makers[m] = makers.get(m, 0) + 1
        buckets[e.lower()] = {"display": e, "games": cnt, "makers": makers,
                              "has_ini": has_ini}
    return buckets


def _maker_bucket_map(buckets):
    """厂商 → 桶（该厂商游戏最多的桶；平局优先"厂商更聚焦"的桶——
    品牌家族桶(Atelier_Kaguya) 优先于题材大杂烩桶(Independent_RPG_SLG)，符合用户分组习惯）。"""
    m = {}
    for bname, b in buckets.items():
        for maker, cnt in b.get("makers", {}).items():
            cur = m.get(maker)
            key = (cnt, -len(b["makers"]), b["games"])
            if cur is None or key > cur[1]:
                m[maker] = (b["display"], key)
    return {k: v[0] for k, v in m.items()}


def _target_bucket(cfg, db, root, game, maker_map, buckets, overrides):
    """决定游戏的目标桶：overrides(用户指定) → 学习映射 → 自动建桶 → Uncategorized。"""
    maker = (game.get("maker") or "").strip()
    if overrides.get(maker):
        return overrides[maker]
    if maker in maker_map:
        return maker_map[maker]
    if maker and not maker.lower() in {"", "unknown", "未知", "n/a"}:
        slug = _bucket_slug(maker)
        if slug:
            return slug
    return "Uncategorized"


def _game_dirname(game):
    """目标目录名：去掉【PC】包装前缀；保留原名（重命名选项后续接入）。"""
    name = os.path.basename((game.get("path") or "").rstrip("\\/"))
    name = _PC_WRAP.sub("", name).strip() or name
    return name


# 垃圾名目录：纯版本号/数字/占位（"1"、"1.01"、"(2)"…），不能当游戏目录名用
_JUNK_NAME = re.compile(r"^[\d\s.\-()（）\[\]【】vV版号游戏]*$")


def build_plan(cfg, db):
    """生成整理计划（dry-run，不移动任何文件）。
    返回 {"ok": True, "items": [{game_id, title, maker, from, to, reason, selected}]}
    分类规则（由保守到激进）：
    - 直接挂在桶下（含受保护桶）→ 已整理，跳过
    - 桶内包装层：内层是垃圾名（"1"/"1.01"）或与包装层同名 → 原位平铺；
      有意义的内外层（Enjou_Gakuen_2/艶嬢学園…）→ 保留不动
    - 顶层散落 / 库根包装层（【PC】xxx）→ 按厂商学习映射归桶
    只处理 status=2 且路径存在的游戏。
    """
    roots = [r for r in cfg.get("library_roots", []) if os.path.isdir(r)]
    overrides = cfg.get("organize.maker_buckets", {}) or {}
    items = []
    for root in roots:
        buckets = _detect_buckets(db, root)
        maker_map = _maker_bucket_map(buckets)
        bucket_dirs = set(buckets.keys())
        games = db.query("SELECT * FROM games WHERE status=2 AND path LIKE ?",
                         (root + os.sep + "%",))
        for g in games:
            p = (g.get("path") or "").strip()
            if not p or not os.path.isdir(p):
                continue
            parent = os.path.basename(os.path.dirname(p.rstrip("\\/")))
            parent_low = parent.lower()
            # 1) 已整理：父目录是桶 → 跳过
            if parent_low in bucket_dirs or parent_low in PROTECTED_BUCKETS:
                continue
            grand = os.path.basename(os.path.dirname(os.path.dirname(p.rstrip("\\/"))))
            grand_low = grand.lower()
            # 2) 桶内包装层：只在垃圾名/同名时平铺，否则保留双层结构
            if grand_low in bucket_dirs or grand_low in PROTECTED_BUCKETS:
                inner = os.path.basename(p)
                if inner == parent or _JUNK_NAME.match(inner):
                    items.append({
                        "game_id": g["id"], "title": g.get("title") or "",
                        "maker": (g.get("maker") or ""),
                        "from": p,
                        "to": os.path.join(os.path.dirname(os.path.dirname(p)), parent),
                        "reason": "包装层平铺", "selected": True,
                    })
                continue
            # 3) 顶层散落 / 库根包装层 → 按厂商归桶
            target = _target_bucket(cfg, db, root, g, maker_map, buckets, overrides)
            if not target:
                continue
            new_dir = os.path.join(root, target, _effective_game_name(g))
            if os.path.normpath(os.path.dirname(p)) == os.path.normpath(os.path.join(root, target)):
                continue  # 已经在目标桶里
            reason = "顶层散落" if os.path.normpath(os.path.dirname(p)) == os.path.normpath(root) \
                else f"包装层 {parent} 拆解"
            items.append({
                "game_id": g["id"], "title": g.get("title") or "",
                "maker": (g.get("maker") or ""),
                "from": p, "to": new_dir,
                "reason": reason, "selected": True,
            })
    items.sort(key=lambda x: (x["to"], x["from"]))
    return {"ok": True, "items": items, "total": len(items)}


def _effective_game_name(game):
    """有效游戏目录名：内层是垃圾名（"1"）时用包装层名。"""
    p = (game.get("path") or "").rstrip("\\/")
    inner = os.path.basename(p)
    wrapper = os.path.basename(os.path.dirname(p))
    name = _PC_WRAP.sub("", inner).strip() or inner
    if _JUNK_NAME.match(name) and wrapper and not _JUNK_NAME.match(wrapper):
        name = wrapper
    return name


def _update_db_paths(db, game_id, old_path, new_path):
    """移动后同步 DB：path/exe_path/workdir/cover_local 的相对部分。"""
    g = db.query_one("SELECT * FROM games WHERE id=?", (game_id,))
    if not g:
        return
    fields = {"path": new_path}
    for col, key in (("exe_path", "exe_path"), ("workdir", "workdir"),
                     ("cover_local", "cover_local")):
        v = (g.get(key) or "").strip()
        if v and (v == old_path or v.startswith(old_path + os.sep)):
            fields[col] = new_path + v[len(old_path):]
    sets = ", ".join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE games SET {sets} WHERE id=?", (*fields.values(), game_id))


# ---------- desktop.ini 本地化（windows-folder-magic 习惯：纯英文路径 + 中文/日文显示名） ----------
_FA_HIDDEN = 0x2
_FA_SYSTEM = 0x4
_FA_READONLY = 0x1


def _set_attrs(path, attrs):
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(path, attrs)
    except Exception:
        pass


def localize_bucket(dirpath, display_name):
    """给桶目录写 desktop.ini：UTF-16 + 隐藏/系统属性 + 目录只读。
    显示名与目录名相同时跳过（纯 ASCII 名直接可读则不需要马甲）。"""
    if not display_name:
        return
    base = os.path.basename(os.path.normpath(dirpath))
    if display_name == base:
        return
    os.makedirs(dirpath, exist_ok=True)
    ini = os.path.join(dirpath, "desktop.ini")
    try:
        with open(ini, "w", encoding="utf-16") as f:
            f.write(f"[.ShellClassInfo]\nLocalizedResourceName={display_name}\n")
        _set_attrs(ini, _FA_HIDDEN | _FA_SYSTEM)
        _set_attrs(dirpath, _FA_READONLY)
        try:
            import ctypes
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        except Exception:
            pass
    except OSError:
        pass


def apply_plan(cfg, db, items):
    """执行整理：移动目录 + 更新 DB + 记录历史。items: [{game_id, to}]。
    返回 {"ok": True, "results": [{game_id, title, ok, from, to, error}]}
    """
    from .utils import now_iso as _now
    results = []
    for it in items or []:
        gid = int(it.get("game_id") or 0)
        g = db.query_one("SELECT * FROM games WHERE id=?", (gid,))
        if not g:
            results.append({"game_id": gid, "ok": False, "error": "游戏不存在"})
            continue
        old = (g.get("path") or "").strip()
        new = (it.get("to") or "").strip()
        if not old or not new or not os.path.isdir(old):
            results.append({"game_id": gid, "title": g.get("title"),
                            "ok": False, "error": "源目录不存在"})
            continue
        if os.path.normpath(old) == os.path.normpath(new):
            results.append({"game_id": gid, "title": g.get("title"),
                            "ok": True, "moved": False, "note": "已在目标位置"})
            continue
        # 包装层平铺：目标 == 源目录的父目录（同名/垃圾名包装层）→ 内容上移一层，删空包装
        if os.path.normpath(new) == os.path.normpath(os.path.dirname(old)):
            try:
                moved = 0
                for item in os.listdir(old):
                    src = os.path.join(old, item)
                    dst = os.path.join(os.path.dirname(old), item)
                    if not os.path.exists(dst):
                        os.rename(src, dst)
                        moved += 1
                flat_new = os.path.dirname(old)
                if not os.listdir(old):
                    os.rmdir(old)
                _update_db_paths(db, gid, old, flat_new)
                db.execute(
                    "INSERT INTO organize_history (game_id, title, from_path, to_path, moved_at, ok)"
                    " VALUES (?,?,?,?,?,1)",
                    (gid, g.get("title") or "", old, flat_new, _now()))
                results.append({"game_id": gid, "title": g.get("title"),
                                "ok": True, "moved": True, "from": old, "to": flat_new,
                                "note": "包装层平铺"})
            except Exception as e:
                db.execute(
                    "INSERT INTO organize_history (game_id, title, from_path, to_path, moved_at, ok)"
                    " VALUES (?,?,?,?,?,0)",
                    (gid, g.get("title") or "", old, os.path.dirname(old), _now()))
                results.append({"game_id": gid, "title": g.get("title"),
                                "ok": False, "error": f"平铺失败: {e}"})
            continue
        if os.path.dirname(old).lower() != os.path.dirname(new).lower() and \
                os.path.splitdrive(old)[0].lower() != os.path.splitdrive(new)[0].lower():
            results.append({"game_id": gid, "title": g.get("title"),
                            "ok": False, "error": "跨盘移动不支持"})
            continue
        try:
            target_dir = os.path.dirname(new)
            is_new_bucket = not os.path.isdir(target_dir)
            os.makedirs(target_dir, exist_ok=True)
            if is_new_bucket:  # 新建桶 → 按习惯写 desktop.ini（已有桶绝不动，尊重用户本地化）
                localize_bucket(target_dir, (g.get("maker") or "").strip())
            if os.path.exists(new):
                # 目标冲突 → 加序号后缀，绝不覆盖
                base, i = new, 2
                while os.path.exists(new):
                    new = f"{base} ({i})"
                    i += 1
            os.rename(old, new)
            _update_db_paths(db, gid, old, new)
            db.execute(
                "INSERT INTO organize_history (game_id, title, from_path, to_path, moved_at, ok)"
                " VALUES (?,?,?,?,?,1)",
                (gid, g.get("title") or "", old, new, _now()))
            results.append({"game_id": gid, "title": g.get("title"),
                            "ok": True, "moved": True, "from": old, "to": new})
        except Exception as e:
            db.execute(
                "INSERT INTO organize_history (game_id, title, from_path, to_path, moved_at, ok)"
                " VALUES (?,?,?,?,?,0)",
                (gid, g.get("title") or "", old, new or "", _now()))
            results.append({"game_id": gid, "title": g.get("title"),
                            "ok": False, "error": str(e)})
    # 清理移动后变空的包装层（【PC】xxx 等）
    _cleanup_empty_wrappers(db)
    return {"ok": True, "results": results}


def _cleanup_empty_wrappers(db):
    """删除移动后变空的包装层目录（【PC】xxx 等，仅当目录内无任何文件）。"""
    for r in db.query("SELECT DISTINCT from_path FROM organize_history WHERE ok=1"):
        p = (r.get("from_path") or "").strip()
        if not p:
            continue
        wrapper = os.path.dirname(p)
        try:
            if wrapper and os.path.isdir(wrapper) and not os.listdir(wrapper):
                os.rmdir(wrapper)
        except OSError:
            pass


def list_history(db, limit=20):
    rows = db.query(
        "SELECT * FROM organize_history ORDER BY id DESC LIMIT ?", (limit,))
    return rows
