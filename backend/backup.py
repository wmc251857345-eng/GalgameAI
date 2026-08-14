"""存档备份引擎胶水层：封装 ludusavi.exe (Rust CLI) 为 Python API。

架构：
    GALA 前端/API → backup.py → ludusavi.exe --api (JSON) → 存档备份/恢复/历史

设计要点：
- 引擎路径：优先 config.backup.engine_path，否则探测常见位置。
- 配置隔离：引擎使用 GALA 专属配置目录（--config），不污染用户手动配置
  （%APPDATA%/ludusavi/config.yaml），GALA 自定义游戏写入专属配置。
- 所有调用 subprocess + 超时 + 锁（引擎不支持并发调用）。
- 游戏名匹配：steam_id → exact → fuzzy 三级，供 GALA 游戏映射到引擎名称。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from typing import Any, Optional

from . import paths
from .utils import now_iso

# 引擎配置目录（GALA 专属，与手动使用的 %APPDATA%/ludusavi 隔离）
ENGINE_CONFIG_DIR = os.path.join(paths.CONFIG_DIR, "ludusavi")
# 引擎备份数据根目录（默认在 GALA 根下；可在设置中改为 OneDrive 同步文件夹等）
BACKUP_ROOT_DEFAULT = os.path.join(paths.BASE, "database", "ludusavi_backups")


def backup_targets(config=None) -> list[dict]:
    """解析备份目标列表（支持双线/多线：U盘 + OneDrive + 本地）。

    配置格式 config.backup.targets: [{path, enabled, label}]
    兼容旧字段 config.backup.root（单目标）。
    """
    if config is not None:
        targets = config.get("backup.targets")
        if isinstance(targets, list) and targets:
            out = []
            for t in targets:
                p = t.get("path") if isinstance(t, dict) else t
                if p:
                    out.append({
                        "path": str(p),
                        "enabled": t.get("enabled", True) if isinstance(t, dict) else True,
                        "label": t.get("label", "") if isinstance(t, dict) else "",
                    })
            if out:
                return out
        legacy = config.get("backup.root")
        if legacy:
            return [{"path": str(legacy), "enabled": True, "label": "默认"}]
    return [{"path": BACKUP_ROOT_DEFAULT, "enabled": True, "label": "本地默认"}]


def backup_root(config=None) -> str:
    """主备份根 = 第一个启用的目标（引擎 config.yaml 的 backup.path 用它）。"""
    for t in backup_targets(config):
        if t["enabled"]:
            return t["path"]
    return BACKUP_ROOT_DEFAULT


# 兼容旧引用：模块级 BACKUP_ROOT（保持默认值，实际使用请调用 backup_root(config)）
BACKUP_ROOT = BACKUP_ROOT_DEFAULT


# ---------- 备份目标探测（U盘 / OneDrive / 本地） ----------

def list_removable_drives() -> list[dict]:
    """探测可移动磁盘（U盘等）。返回 [{path, label, total_gb, free_gb}]。"""
    out = []
    try:
        import psutil
        for p in psutil.disk_partitions():
            if "removable" in (p.opts or ""):
                try:
                    u = psutil.disk_usage(p.mountpoint)
                    out.append({
                        "path": p.mountpoint,
                        "label": p.device,
                        "total_gb": round(u.total / (1024 ** 3), 1),
                        "free_gb": round(u.free / (1024 ** 3), 1),
                    })
                except OSError:
                    out.append({"path": p.mountpoint, "label": p.device,
                                "total_gb": 0, "free_gb": 0})
    except ImportError:
        pass
    return out


def detect_onedrive_path() -> Optional[str]:
    """探测 OneDrive 同步文件夹（注册表 KnownFolder 优先，其次常见路径）。"""
    import winreg
    # OneDrive KnownFolder ID
    ONEDRIVE_KF = "{A52BBA46-E9E1-435F-B3D9-28DAA648C0F6}"
    for subkey in (r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
                   r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"):
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey)
            val, _ = winreg.QueryValueEx(k, ONEDRIVE_KF)
            winreg.CloseKey(k)
            if val:
                p = os.path.expandvars(val)
                if os.path.isdir(p):
                    return p
        except OSError:
            continue
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "OneDrive"), os.path.join(home, "OneDrive - 个人")):
        if os.path.isdir(cand):
            return cand
    return None


def detect_targets(config=None) -> list[dict]:
    """汇总全部可用的备份目标（含探测），供设置页展示。

    返回 [{path, kind: local|usb|onedrive|default, enabled, total_gb, free_gb, exists}]
    """
    enabled = {t["path"].lower(): t for t in backup_targets(config)}
    out = []
    # 本地默认
    out.append({
        "path": BACKUP_ROOT_DEFAULT, "kind": "default", "label": "本地默认",
        "enabled": BACKUP_ROOT_DEFAULT.lower() in enabled or not enabled,
        "total_gb": None, "free_gb": None, "exists": os.path.isdir(BACKUP_ROOT_DEFAULT),
    })
    # U盘
    for d in list_removable_drives():
        out.append({
            "path": d["path"], "kind": "usb", "label": f"U盘 {d['label']}",
            "enabled": d["path"].lower() in enabled,
            "total_gb": d["total_gb"], "free_gb": d["free_gb"],
            "exists": os.path.isdir(d["path"]),
        })
    # OneDrive
    od = detect_onedrive_path()
    if od:
        out.append({
            "path": od, "kind": "onedrive", "label": "OneDrive",
            "enabled": od.lower() in enabled,
            "total_gb": None, "free_gb": None, "exists": os.path.isdir(od),
        })
    # 已配置但未探测到的（自定义路径）
    for t in enabled.values():
        p = t["path"]
        if not any(x["path"].lower() == p.lower() for x in out):
            out.append({
                "path": p, "kind": "custom", "label": t.get("label") or p,
                "enabled": t["enabled"], "total_gb": None, "free_gb": None,
                "exists": os.path.isdir(p),
            })
    return out

_ENGINE_CANDIDATES = [
    # config 指定（运行时覆盖）
    None,
    # 与 GALA 同目录（打包分发场景）
    os.path.join(paths.BASE, "ludusavi.exe"),
    os.path.join(paths.BASE, "tools", "ludusavi", "ludusavi.exe"),
    # 用户手动位置
    r"G:\tools\ludusavi-master\ludusavi.exe",
    # PATH 中
    "ludusavi",
]

_engine_lock = threading.Lock()
_engine_path: Optional[str] = None


# ---------- 基础 ----------

def find_engine(config) -> Optional[str]:
    """定位 ludusavi.exe。返回绝对路径或 None。"""
    global _engine_path
    if _engine_path and os.path.isfile(_engine_path):
        return _engine_path
    candidates = []
    cfg_path = config.get("backup.engine_path")
    if cfg_path:
        candidates.append(cfg_path)
    candidates += [c for c in _ENGINE_CANDIDATES if c]
    for c in candidates:
        if c == "ludusavi":
            p = shutil.which("ludusavi")
            if p:
                _engine_path = p
                return p
        if c and os.path.isfile(c):
            _engine_path = c
            return c
    return None


def engine_ready(config) -> bool:
    return find_engine(config) is not None


def _run(config, args: list[str], timeout: int = 600) -> dict:
    """执行引擎命令，返回 {ok, code, data, error}。

    data: 解析后的 JSON（--api 模式）；非 JSON 输出放 raw。
    """
    exe = find_engine(config)
    if not exe:
        return {"ok": False, "code": -1, "data": None, "error": "未找到 ludusavi.exe，请在设置中配置引擎路径"}
    os.makedirs(ENGINE_CONFIG_DIR, exist_ok=True)
    cmd = [exe, "--config", ENGINE_CONFIG_DIR, "--no-manifest-update"] + args
    with _engine_lock:
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "code": -1, "data": None, "error": f"引擎超时（{timeout}s）"}
        except OSError as e:
            return {"ok": False, "code": -1, "data": None, "error": f"引擎启动失败: {e}"}
    out = proc.stdout or ""
    data = None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        pass
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "data": data,
        "error": (proc.stderr or "").strip() or (None if proc.returncode == 0 else "引擎返回错误"),
        "raw": out,
    }


# ---------- 配置 ----------

def ensure_engine_config(config) -> dict:
    """确保引擎配置目录存在且具备最小配置（备份路径指向 GALA 的备份根）。"""
    root = backup_root(config)
    os.makedirs(ENGINE_CONFIG_DIR, exist_ok=True)
    os.makedirs(root, exist_ok=True)
    cfg_path = os.path.join(ENGINE_CONFIG_DIR, "config.yaml")
    if not os.path.isfile(cfg_path):
        # 引擎会自动生成；先跑一次 config path 触发初始化
        _run(config, ["config", "path"], timeout=60)
    # 强制备份/恢复路径指向 GALA 的备份根（不依赖引擎默认值）
    try:
        import yaml
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        backup_root_win = root.replace("\\", "/")
        changed = False
        if data.get("backup", {}).get("path") != backup_root_win:
            data.setdefault("backup", {})["path"] = backup_root_win
            changed = True
        if data.get("restore", {}).get("path") != backup_root_win:
            data.setdefault("restore", {})["path"] = backup_root_win
            changed = True
        if changed:
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    except ImportError:
        pass
    return {"config_dir": ENGINE_CONFIG_DIR, "backup_root": root}


def write_custom_games(config, games: list[dict]) -> dict:
    """把 GALA 的存档配置同步为引擎 custom games。

    games: [{name, files: [绝对路径...], installDir: [目录名...]}]
    直接写引擎专属 config.yaml 的 customGames 段（引擎未提供 CLI 管理命令）。
    返回 {ok, error, count}。
    """
    cfg_path = os.path.join(ENGINE_CONFIG_DIR, "config.yaml")
    if not os.path.isfile(cfg_path):
        ensure_engine_config(config)
    try:
        import yaml  # PyYAML 由引擎配置读写引入；若无则回退手写
    except ImportError:
        return {"ok": False, "error": "缺少 PyYAML，请安装", "count": 0}

    with _engine_lock:
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}
        data["customGames"] = [
            {
                "name": g["name"],
                "integration": "override",
                "files": [p.replace("\\", "/") for p in g.get("files", [])],
                "installDir": g.get("installDir", []),
                "registry": [],
            }
            for g in games
            if g.get("name") and g.get("files")
        ]
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            return {"ok": False, "error": f"写入引擎配置失败: {e}", "count": 0}
    return {"ok": True, "error": None, "count": len(data["customGames"])}


# ---------- 匹配 ----------

def find_game(config, name: str, steam_id: Optional[str] = None) -> Optional[str]:
    """GALA 游戏名 → 引擎识别名。

    优先级：steam_id → 精确名 → normalized → fuzzy。
    返回引擎中的游戏标题；找不到返回 None。
    """
    if steam_id:
        r = _run(config, ["find", "--api", "--steam-id", str(steam_id)], timeout=120)
        if r["ok"] and r["data"] and r["data"].get("games"):
            return next(iter(r["data"]["games"]))
    for flag in ("--normalized", "--fuzzy"):
        r = _run(config, ["find", "--api", flag, name], timeout=120)
        if r["ok"] and r["data"] and r["data"].get("games"):
            return next(iter(r["data"]["games"]))
    return None


# ---------- 存档路径智能探测 ----------

# 常见存档目录名（小写匹配，游戏目录内一层扫描）
_SAVE_DIR_NAMES = {
    "save", "saves", "savedata", "save_data", "savedatas", "savegames",
    "savegame", "saved games", "save files", "savefiles", "profile",
    "profiles", "存档", "存档文件", "data", "sav", "savdata",
}
# 常见存档文件扩展名（用于识别"存档散落在目录里"的情况）
_SAVE_EXTS = {
    ".sav", ".srm", ".sol", ".dat", ".sgo", ".save", ".sds", ".nv",
    ".rpy", ".rpgsave", ".lsd", ".dsav", ".savx", ".json",
}
# 排除的目录名（游戏根目录下这些不是存档）
_EXCLUDE_DIR_NAMES = {"bin", "config", "cfg", "graphics", "bgm", "se", "voice",
                      "video", "movie", "movies", "font", "fonts", "patch",
                      "update", "redist", "dx9", "dx10", "dx11", "dx12",
                      "vc_redist", "plugins", "logs", "debug", "unitycrashhandler"}


def _dir_has_save_files(d: str, depth: int = 0) -> bool:
    """目录内（浅层递归）是否有存档特征文件。"""
    try:
        entries = os.listdir(d)
    except OSError:
        return False
    for e in entries:
        full = os.path.join(d, e)
        if os.path.isfile(full):
            if os.path.splitext(e)[1].lower() in _SAVE_EXTS:
                return True
        elif depth < 2 and os.path.isdir(full) and not e.startswith("."):
            if _dir_has_save_files(full, depth + 1):
                return True
    return False


def detect_save_paths(game: dict) -> list[dict]:
    """智能探测一款游戏的存档位置。

    game: GALA games 行（path/exe_path/title/title_en/title_zh/workdir）。
    返回 [{path, reason, exists}]，按可信度排序。
    """
    found: list[dict] = []
    seen = set()

    def add(p, reason, exists=None):
        p = os.path.normpath(p)
        key = p.lower()
        if key in seen:
            return
        seen.add(key)
        if exists is None:
            exists = os.path.isdir(p)
        found.append({"path": p, "reason": reason, "exists": exists})

    game_dir = game.get("path") or (os.path.dirname(game.get("exe_path") or "") if game.get("exe_path") else "")
    exe_dir = os.path.dirname(game.get("exe_path") or "") if game.get("exe_path") else ""
    titles = [t for t in (game.get("title"), game.get("title_en"),
                          game.get("title_zh"), game.get("title_jp")) if t]

    # --- 第 1 层：游戏目录下 ---
    for base in (game_dir, exe_dir):
        if not base or not os.path.isdir(base):
            continue
        # 1a. 常见存档子目录名（一层）
        try:
            entries = os.listdir(base)
        except OSError:
            entries = []
        for e in entries:
            full = os.path.join(base, e)
            if not os.path.isdir(full):
                continue
            el = e.lower()
            if el in _SAVE_DIR_NAMES and el not in _EXCLUDE_DIR_NAMES:
                add(full, f"游戏目录内 {e}")
        # 1b. 有存档特征文件的子目录（一层，排除常见非存档目录）
        for e in entries:
            full = os.path.join(base, e)
            if not os.path.isdir(full) or e.lower() in _EXCLUDE_DIR_NAMES:
                continue
            if _dir_has_save_files(full):
                add(full, f"含存档文件 {e}")

    # --- 第 2 层：用户文档 ---
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    my_games = os.path.join(docs, "My Games")
    doc_candidates = []
    for t in titles + [os.path.basename(game_dir or "")]:
        if not t:
            continue
        doc_candidates.append((os.path.join(docs, t), f"文档\\{t}"))
        doc_candidates.append((os.path.join(my_games, t), f"文档\\My Games\\{t}"))
    # 排除明显的非存档（Documents 根目录本身等）
    for p, reason in doc_candidates:
        if p.lower() == docs.lower() or p.lower() == my_games.lower():
            continue
        add(p, reason)

    # --- 第 3 层：AppData ---
    for env, label in (("APPDATA", "AppData\\Roaming"),
                       ("LOCALAPPDATA", "AppData\\Local")):
        base = os.environ.get(env)
        if not base:
            continue
        for t in titles + [os.path.basename(game_dir or "")]:
            if t:
                add(os.path.join(base, t), f"{label}\\{t}")
    locallow = os.path.join(home, "AppData", "LocalLow")
    for t in titles:
        if t:
            add(os.path.join(locallow, t), f"AppData\\LocalLow\\{t}")

    # 排序：存在的在前，目录内优先
    order = {"游戏目录内": 0, "含存档文件": 1, "文档\\My Games": 2, "文档": 3,
             "AppData\\LocalLow": 4, "AppData\\Roaming": 5, "AppData\\Local": 6}
    found.sort(key=lambda x: (not x["exists"], order.get(x["reason"].split()[0] if x["reason"] else "", 9)))
    return found


# ---------- 备份 / 恢复 / 历史 ----------

def backup(config, games: Optional[list[str]] = None, dry_run: bool = False,
           by_all: bool = False, path: Optional[str] = None) -> dict:
    """执行备份（单目标）。games: 引擎游戏名列表；by_all: 备份全部。

    返回引擎 JSON（overall/games 结构），并附加 ok 字段。
    """
    args = ["backup", "--api", "--force"]
    if dry_run:
        args.append("--preview")
    if path:
        args += ["--path", path]
    if by_all:
        args += ["--by", "all"]
    if games:
        args += games
    r = _run(config, args, timeout=1800)
    if not r["ok"]:
        return {"ok": False, "error": r["error"]}
    data = r["data"] or {}
    data["ok"] = True
    return data


def backup_multi(config, games: Optional[list[str]] = None, dry_run: bool = False,
                 by_all: bool = False, targets: Optional[list[dict]] = None) -> dict:
    """多目标备份（双线/多线：U盘 + OneDrive + 本地，每个启用目标各跑一次）。

    返回 {ok, targets: [{path, ok, error, overall}], overall(合并统计), games(合并)}。
    """
    tgts = targets if targets is not None else backup_targets(config)
    enabled = [t for t in tgts if t.get("enabled")]
    if not enabled:
        return {"ok": False, "error": "没有启用的备份目标", "targets": []}

    merged_games = {}
    merged_overall = {"totalGames": 0, "totalBytes": 0, "processedGames": 0,
                      "processedBytes": 0, "changedGames": {"new": 0, "different": 0, "same": 0}}
    results = []
    all_ok = True
    for t in enabled:
        p = t["path"]
        label = t.get("label") or p
        if not os.path.isdir(p):
            try:
                os.makedirs(p, exist_ok=True)
            except OSError as e:
                results.append({"path": p, "label": label, "ok": False,
                                "error": f"目标不可用（无法创建目录: {e}）", "overall": None})
                all_ok = False
                continue
        r = backup(config, games=games, dry_run=dry_run, by_all=by_all, path=p)
        if not r.get("ok"):
            results.append({"path": p, "label": label, "ok": False,
                            "error": r.get("error"), "overall": None})
            all_ok = False
            continue
        ov = r.get("overall", {})
        results.append({"path": p, "label": label, "ok": True, "error": None, "overall": ov})
        # 合并
        for k in ("totalGames", "totalBytes", "processedGames", "processedBytes"):
            merged_overall[k] += ov.get(k, 0) or 0
        cg = ov.get("changedGames", {})
        for k in ("new", "different", "same"):
            merged_overall["changedGames"][k] += cg.get(k, 0) or 0
        for gname, info in (r.get("games") or {}).items():
            merged_games.setdefault(gname, info)

    return {"ok": all_ok, "targets": results, "overall": merged_overall,
            "games": merged_games, "error": None if all_ok else "部分目标备份失败"}


def restore(config, games: list[str], dry_run: bool = False,
            path: Optional[str] = None) -> dict:
    args = ["restore", "--api", "--force"]
    if dry_run:
        args.append("--preview")
    if path:
        args += ["--path", path]
    args += games
    r = _run(config, args, timeout=1800)
    if not r["ok"]:
        return {"ok": False, "error": r["error"]}
    data = r["data"] or {}
    data["ok"] = True
    return data


def list_backups(config, games: Optional[list[str]] = None, path: Optional[str] = None) -> dict:
    args = ["backups", "--api"]
    if path:
        args += ["--path", path]
    if games:
        args += games
    r = _run(config, args, timeout=300)
    if not r["ok"]:
        return {"ok": False, "error": r["error"]}
    return r["data"] or {}


# ---------- 元数据（GALA 侧记录） ----------

def record_backup_meta(db, game_title: str, engine_name: str, result: dict):
    """备份后记录元数据：备份时间、引擎名映射、大小。

    result: backup() 返回的引擎 JSON（含 overall 和 games 明细）。
    """
    overall = result.get("overall", {})
    total_bytes = overall.get("totalBytes", 0) or 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """INSERT OR REPLACE INTO backup_history
           (game_title, engine_name, last_backup_at, total_bytes, backup_count)
           VALUES (?, ?, ?, ?,
                   COALESCE((SELECT backup_count FROM backup_history WHERE game_title=?), 0) + 1)""",
        (game_title, engine_name, now, total_bytes, game_title),
    )


def get_backup_meta(db) -> list[dict]:
    rows = db.query(
        """SELECT game_title, engine_name, last_backup_at, total_bytes, backup_count
           FROM backup_history ORDER BY last_backup_at DESC""")
    return rows


# ========== GALA 版本快照（关游戏自动备份 / 详情页时间线） ==========
# 与 ludusavi 引擎备份独立：直接把存档文件复制为带时间戳的版本目录，
# 不依赖 ludusavi.exe，版本管理完全自控（保留 SNAPSHOT_KEEP 份/游戏）。
# 目录结构：database/backups/<游戏中文名>/<YYYYmmdd_HHMMSS>/
SNAPSHOT_ROOT = os.path.join(paths.BASE, "database", "backups")
SNAPSHOT_KEEP = 20
# 复制存档时忽略的垃圾/临时内容
_SNAP_IGNORE = ("desktop.ini", "Thumbs.db", "*.tmp", "*.log", "$RECYCLE.BIN", "System Volume Information")


def _safe_name(name: str) -> str:
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    name = name.strip().strip(".")
    return name or "未命名"


def snapshot_dir(db, game) -> str:
    """版本快照根：database/backups/<游戏中文名>/（同名游戏共享目录，时间戳区分）。"""
    name = (game.get("title_zh") or "").strip() or (game.get("title") or "").strip() or f"游戏{game['id']}"
    d = os.path.join(SNAPSHOT_ROOT, _safe_name(name))
    os.makedirs(d, exist_ok=True)
    return d


def _game_save_dirs(db, game) -> list[str]:
    """自动备份用的存档源目录（去重、只保留存在项）：
    优先用户手动配置过的 backup_history.save_paths，再补 detect_save_paths 探测命中。"""
    dirs, seen = [], set()
    meta = db.query_one("SELECT save_paths FROM backup_history WHERE game_id=?", (game["id"],))
    if meta and meta.get("save_paths"):
        try:
            for p in json.loads(meta["save_paths"] or "[]"):
                if p and os.path.isdir(p) and p.lower() not in seen:
                    seen.add(p.lower())
                    dirs.append(p)
        except (ValueError, TypeError):
            pass
    for c in detect_save_paths(game):
        p = c.get("path")
        if p and c.get("exists") and os.path.isdir(p) and p.lower() not in seen:
            seen.add(p.lower())
            dirs.append(p)
    return dirs


def snapshot_backup(db, game, kind: str = "manual") -> dict:
    """把游戏当前存档复制为版本快照 database/backups/<游戏名>/<ts>/。

    kind: manual（手动点击/恢复前保险）| auto（关游戏自动备份）。
    写 backup_versions + 每游戏保留 SNAPSHOT_KEEP 份（超量删最旧）。
    """
    srcs = _game_save_dirs(db, game)
    if not srcs:
        return {"ok": False,
                "error": "未找到该游戏的存档目录（可在详情页手动配置存档路径后再备份）"}
    ts = time.strftime("%Y%m%d_%H%M%S")
    # 同一秒重复备份 → 加序号（游戏秒退重开场景）
    dest = os.path.join(snapshot_dir(db, game), ts)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(snapshot_dir(db, game), f"{ts}_{i}")
        i += 1
    ts = os.path.basename(dest)
    total = 0
    copied_dirs = []
    try:
        for s in srcs:
            name = _safe_name(os.path.basename(s.rstrip("\\/")) or "save")
            d = os.path.join(dest, name)
            k = 1
            while os.path.exists(d):
                d = os.path.join(dest, f"{name}_{k}")
                k += 1
            shutil.copytree(s, d, ignore=shutil.ignore_patterns(*_SNAP_IGNORE))
            copied_dirs.append(d)
            for root, _dirs, files in os.walk(d):
                total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
    except Exception as e:
        return {"ok": False, "error": f"备份失败: {e}"}
    try:
        with open(os.path.join(dest, "_meta.json"), "w", encoding="utf-8") as f:
            json.dump({"game_id": game["id"], "title": game.get("title"), "created": ts,
                       "sources": srcs, "bytes": total, "kind": kind}, f,
                      ensure_ascii=False, indent=2)
    except OSError:
        pass
    db.execute(
        "INSERT INTO backup_versions (game_id, backed_at, engine_when, bytes, status, kind)"
        " VALUES (?,?,?,?,?,?)",
        (game["id"], now_iso(), ts, total, "ok", kind))
    _snapshot_prune(db, game)
    return {"ok": True, "ts": ts, "bytes": total, "dirs": len(copied_dirs), "dest": dest}


def _snapshot_prune(db, game):
    """每游戏最多保留 SNAPSHOT_KEEP 份（时间戳排序删最旧，同步清 backup_versions）。"""
    base = snapshot_dir(db, game)
    try:
        vers = sorted(d for d in os.listdir(base)
                      if os.path.isdir(os.path.join(base, d)))
    except OSError:
        return
    for old in vers[:-SNAPSHOT_KEEP]:
        shutil.rmtree(os.path.join(base, old), ignore_errors=True)
        db.execute("DELETE FROM backup_versions WHERE game_id=? AND engine_when=?",
                   (game["id"], old))


def snapshot_versions(db, game_id: int) -> list[dict]:
    """版本时间线（新→旧）。kind/backed_at/bytes/目录是否仍在。"""
    game = db.query_one("SELECT * FROM games WHERE id=?", (game_id,))
    out = []
    if not game:
        return out
    base = snapshot_dir(db, game)
    for r in db.query(
            "SELECT * FROM backup_versions WHERE game_id=? ORDER BY backed_at DESC",
            (game_id,)):
        ts = r.get("engine_when") or ""
        p = os.path.join(base, ts) if ts else ""
        out.append({
            "ts": ts, "backed_at": r["backed_at"], "bytes": r["bytes"] or 0,
            "kind": r.get("kind") or "manual", "status": r["status"],
            "exists": bool(ts) and os.path.isdir(p),
        })
    return out


def snapshot_restore(db, game, ts: str) -> dict:
    """恢复指定版本：先把当前存档自动存为新版本（保险，可反悔），
    再把该版本内容复制回存档源目录。"""
    src = os.path.join(snapshot_dir(db, game), ts)
    if not os.path.isdir(src):
        return {"ok": False, "error": f"版本不存在: {ts}"}
    srcs = _game_save_dirs(db, game)
    if not srcs:
        return {"ok": False, "error": "该游戏没有可恢复的存档目标路径"}
    # 保险：当前状态先存为新版本
    try:
        snapshot_backup(db, game, kind="manual")
    except Exception:
        pass
    restored = []
    for s in srcs:
        name = _safe_name(os.path.basename(s.rstrip("\\/")) or "save")
        cand = os.path.join(src, name)
        if not os.path.isdir(cand):
            continue
        shutil.rmtree(s, ignore_errors=True)  # 快照已留底，直接覆盖
        shutil.copytree(cand, s)
        restored.append(s)
    if not restored:
        return {"ok": False,
                "error": f"该版本快照中没有与存档目录匹配的内容（{src}）"}
    return {"ok": True, "restored": restored, "ts": ts}


def snapshot_import(db, game, src_path: str) -> dict:
    """导入存档：把用户提供的文件/目录复制到游戏存档目录（先自动存当前状态保险）。"""
    if not src_path or not os.path.exists(src_path):
        return {"ok": False, "error": "选择的存档不存在"}
    srcs = _game_save_dirs(db, game)
    if not srcs:
        return {"ok": False, "error": "该游戏没有可导入的存档目标路径（先配置存档路径）"}
    try:
        snapshot_backup(db, game, kind="manual")
    except Exception:
        pass
    target = srcs[0]  # 最可信的存档目录
    if os.path.isdir(src_path):
        # 目录：整个复制（若目录名与目标相同则复制内容，否则复制为子目录）
        if os.path.basename(src_path.rstrip("\\/")).lower() == os.path.basename(target).lower():
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(src_path, target)
        else:
            sub = os.path.join(target, os.path.basename(src_path.rstrip("\\/")))
            shutil.copytree(src_path, sub)
    else:
        os.makedirs(target, exist_ok=True)
        shutil.copy2(src_path, os.path.join(target, os.path.basename(src_path)))
    return {"ok": True, "target": target, "src": src_path}
