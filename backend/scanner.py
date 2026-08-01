"""扫描器：BFS 查找含 exe 的游戏目录（任意深度），提取特征入库。

规则：
- 目录内含 .exe → 视为游戏，不再下钻
- 否则继续下钻（支持 GalGame/厂商/游戏名 或 GalGame/游戏名 两种布局）
- 跳过：隐藏目录、save/data/patch 等目录、setup/unins 等 exe
"""
import os
import re

from .utils import now_iso, normalize, read_text_file

SKIP_DIR = re.compile(
    r"^(save|savedata|data|patch|汉化|补丁|update|backup|cache|thumbs|logs?|"
    r"System Volume Information|recycle|hotpatch)$", re.I)
EXE_SKIP = re.compile(
    r"setup|unins|install|launcher|update|patch|readme|directx|redist|dxsetup|"
    r"crash|error|启动器|汉化|日语|savedata|auto", re.I)
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
COVER_NAMES = re.compile(r"cover|box|package|jacket|front|表紙|パッケージ|立ち絵", re.I)
TEXT_NAMES = re.compile(r"readme|说明|説明|漢化|汉化|ver|version|游戏|游戏|インストール|install|manual|\.nfo", re.I)
HANHUA = re.compile(r"汉化|chs|cn_patch|简中|繁中", re.I)

MAX_DEPTH = 5


def _hidden(name):
    return name.startswith(".") or name.startswith("$")


def guess_main_exe(dirpath, folder_name, exes):
    cands = [f for f in exes if not EXE_SKIP.search(f)]
    if not cands:
        cands = exes
    base = normalize(folder_name)
    for f in cands:  # 1. exe 名 == 目录名
        if normalize(os.path.splitext(f)[0]) == base:
            return f
    for f in cands:  # 2. exe 名包含目录名主词
        if base and base in normalize(f):
            return f
    return max(cands, key=lambda f: os.path.getsize(os.path.join(dirpath, f)))


def find_cover_image(dirpath):
    files = [f for f in os.listdir(dirpath) if f.lower().endswith(IMG_EXT)]
    if not files:
        return None
    for f in files:
        if COVER_NAMES.search(f):
            return f
    return max(files, key=lambda f: os.path.getsize(os.path.join(dirpath, f)))


def extract_texts(dirpath):
    parts = []
    try:
        entries = os.listdir(dirpath)
    except OSError:
        return ""
    for f in entries:
        low = f.lower()
        if not (low.endswith((".txt", ".nfo")) or TEXT_NAMES.search(f)):
            continue
        p = os.path.join(dirpath, f)
        try:
            if os.path.isfile(p) and os.path.getsize(p) < 1_000_000:
                t = read_text_file(p)
                if t.strip():
                    parts.append(f"[{f}]\n{t[:1200]}")
        except OSError:
            continue
    return "\n\n".join(parts)[:4000]


def _save_game(db, info):
    if db.query_one("SELECT id FROM games WHERE path=?", (info["path"],)):
        return None
    db.execute(
        """INSERT INTO games (path, root, title, exe_path, workdir, hanhua,
                              text_sample, size_bytes, cover_local, status, added_at)
           VALUES (?,?,?,?,?,?,?,?,?,0,?)""",
        (info["path"], info["root"], info["title"], info["exe_path"],
         info["workdir"], 1 if info["hanhua"] else 0, info["text_sample"],
         info["size_bytes"], info.get("cover_local"), now_iso()))
    return info


def _extract_game(dirpath, root, exes):
    folder = os.path.basename(dirpath)
    exe = guess_main_exe(dirpath, folder, exes)
    cover = find_cover_image(dirpath)
    text = extract_texts(dirpath)
    hanhua = bool(HANHUA.search(folder)) or "汉化" in text[:300]
    size = 0
    try:
        size = sum(os.path.getsize(os.path.join(dirpath, f))
                   for f in os.listdir(dirpath) if os.path.isfile(os.path.join(dirpath, f)))
    except OSError:
        pass
    return {
        "path": os.path.abspath(dirpath),
        "root": os.path.abspath(root),
        "title": folder,
        "exe_path": os.path.join(dirpath, exe) if exe else None,
        "workdir": dirpath,
        "hanhua": hanhua,
        "text_sample": text,
        "size_bytes": size,
        "cover_local": os.path.join(dirpath, cover) if cover else None,
    }


def scan_root(root, db):
    """BFS 扫描一个根目录，返回新增游戏列表。"""
    root = os.path.abspath(root)
    found = []
    queue = [root]
    seen = set()
    while queue:
        d = queue.pop(0)
        if d in seen:
            continue
        seen.add(d)
        depth = d[len(root):].count(os.sep) if d.startswith(root) else 0
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        subdirs, exes = [], []
        for e in entries:
            p = os.path.join(d, e)
            if os.path.isfile(p):
                if e.lower().endswith(".exe"):
                    exes.append(e)
            elif os.path.isdir(p) and not _hidden(e):
                subdirs.append(e)
        if exes:
            info = _extract_game(d, root, exes)
            if _save_game(db, info):
                found.append(info)
            continue  # 游戏目录不继续下钻
        if depth < MAX_DEPTH:
            for e in subdirs:
                if not SKIP_DIR.search(e):
                    queue.append(os.path.join(d, e))
    return found
