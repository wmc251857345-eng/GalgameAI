"""启动器：进程管理 + 游玩时长统计（session 持久化，重启可补记）。

v1.2：恢复 Locale Emulator 转区启动（v1.1 曾移除）。
旧结论"LEProc 秒退、时长无保障"的解法：LEProc 只是引导进程，真正的游戏
进程由它拉起后独立存活 → 转区启动时不靠 Popen.wait，改用 psutil 按
exe 名轮询游戏进程（复用 _exe_alive 机制），出现前等 60s、消失后结算。
转区是可选的：每游戏 region_locale 为空 = 普通直启（原有路径不变）。
"""
import os
import subprocess
import threading
import time

from .utils import now_iso

RUNNING = {}  # game_id -> {"proc": Popen|None, "started": iso, "session_id": int, "le": bool}
_lock = threading.Lock()

# LEProc.exe 默认候选位置（config locale_emulator.path 优先）
_LE_CANDIDATES = [
    r"G:\tools\LocaleEmulator\LEProc.exe",
    r"C:\Program Files\Locale Emulator\LEProc.exe",
    r"C:\Program Files (x86)\Locale Emulator\LEProc.exe",
]


def find_le_proc(cfg=None):
    """返回可用的 LEProc.exe 绝对路径，找不到返回 None。"""
    try:
        p = (cfg.get("locale_emulator.path") or "").strip()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    for c in _LE_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def _split_args(args):
    """把启动参数字符串按空格拆成 argv 列表（双引号包裹的算一个参数）。

    坑：之前整串 append 进 cmd 列表，Popen 会把它当成【一个】带引号的
    参数传给游戏（"-fullscreen -windowed" 整个是一个 argv），多参数必挂。
    """
    out, cur, in_quote = [], "", False
    for ch in args:
        if ch == '"':
            in_quote = not in_quote
            continue
        if ch in " \t" and not in_quote:
            if cur:
                out.append(cur)
                cur = ""
            continue
        cur += ch
    if cur:
        out.append(cur)
    return out


def launch(db, game, cfg=None):
    exe = game.get("exe_path")
    if not exe or not os.path.exists(exe):
        return {"ok": False, "error": f"exe 不存在: {exe}"}
    workdir = game.get("workdir") or os.path.dirname(exe)
    locale = (game.get("region_locale") or "").strip()
    le_proc = find_le_proc(cfg) if locale else None
    started = now_iso()
    if locale:
        if not le_proc:
            return {"ok": False, "error": "未找到 Locale Emulator(LEProc.exe)：请在设置页配置路径"}
        # 转区启动：LEProc 无参形式 = 应用自身 .le.config → 首个全局Profile → 默认ja-JP
        # 指定 locale 用 -runas <profile guid> <exe>；无对应 profile 时退回默认（多数用户装了 ja-JP 全局）
        guid = _le_profile_guid(locale, le_proc)
        cmd = [le_proc] + (["-runas", guid] if guid else []) + [exe]
        try:
            p = subprocess.Popen(cmd, cwd=workdir)
        except Exception as e:
            return {"ok": False, "error": f"LEProc 启动失败: {e}"}
        sid = _new_session(db, game["id"], started)
        with _lock:
            RUNNING[game["id"]] = {"proc": None, "started": started, "session_id": sid,
                                   "le": True, "exe": exe}
        # LEProc 秒退，游戏进程异步拉起 → psutil 轮询跟踪
        threading.Thread(target=_monitor_le, args=(game["id"], db, exe, started, sid, cfg),
                         daemon=True).start()
        return {"ok": True, "le": True, "note": f"转区 {locale} 启动中（LEProc 引导，游戏稍后弹出）"}
    # 普通直启（原路径）
    cmd = [exe]
    args = (game.get("launch_args") or "").strip()
    if args:
        cmd.extend(_split_args(args))
    try:
        p = subprocess.Popen(cmd, cwd=workdir)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    sid = _new_session(db, game["id"], started)
    with _lock:
        RUNNING[game["id"]] = {"proc": p, "started": started, "session_id": sid, "le": False}
    threading.Thread(target=_monitor,
                     args=(game["id"], db, p, started, sid, cfg),
                     daemon=True).start()
    return {"ok": True, "pid": p.pid}


def _new_session(db, game_id, started):
    return db.execute(
        "INSERT INTO sessions (game_id, started_at, ended_at, seconds) VALUES (?,?,NULL,0)",
        (game_id, started))


def _le_profile_guid(locale, le_proc=None):
    """LEProc 同目录 LEConfig.xml 里找 Location 匹配的 Profile guid。

    没有匹配 profile 返回 None → launch 退回 LEProc 默认 profile
    （应用自身 .le.config → 首个全局 Profile → 默认 ja-JP）。
    """
    try:
        f = os.path.join(os.path.dirname(le_proc), "LEConfig.xml") if le_proc else None
        if not f or not os.path.exists(f):
            return None
        import re
        xml = open(f, encoding="utf-8", errors="ignore").read()
        m = re.search(
            r'<Profile\s+Name="[^"]*"\s+Guid="([^"]+)"[^>]*>.*?<'
            r'Location>\s*' + re.escape(locale) + r'\s*<', xml, re.S)
        return m.group(1) if m else None
    except Exception:
        return None


def _monitor_le(game_id, db, exe, started, session_id, cfg=None):
    """转区启动监控：LEProc 秒退后游戏进程异步出现。
    前 60s 内没出现 → 视为启动失败（关 session 不计时长）；
    出现后按进程名轮询，消失时结算时长。"""
    deadline = time.time() + 60
    while not _exe_alive(exe) and time.time() < deadline:
        time.sleep(2)
    if not _exe_alive(exe):
        db.execute("UPDATE sessions SET ended_at=?, seconds=0"
                   " WHERE id=? AND ended_at IS NULL", (now_iso(), session_id))
        with _lock:
            RUNNING.pop(game_id, None)
        return
    _poll_le(game_id, db, exe, started, session_id, cfg)


def _poll_le(game_id, db, exe, started, session_id, cfg=None):
    """轮询游戏进程（进程名），消失后结算时长 + 自动备份存档。"""
    while _exe_alive(exe):
        time.sleep(30)
    _finalize(db, game_id, session_id, started)
    with _lock:
        RUNNING.pop(game_id, None)
    threading.Thread(target=_auto_snapshot, args=(db, game_id, cfg), daemon=True).start()


def _finalize(db, game_id, session_id, started, ended=None, seconds=None, estimated=False):
    """结算一条 session：写 ended_at/seconds 并累加到游戏总时长。

    estimated=True（进程已消失、真实结束时刻未知）：
    - gap ≤ 24h 的按实际 gap 计入时长（当天会话，误差可接受）
    - gap > 24h 的陈年孤儿（应用被关后隔天才重启）→ 只标记结束、不计时长，
      避免按"上限 8 小时"凭空伪造游玩记录
    """
    ended = ended or now_iso()
    if seconds is None:
        try:
            seconds = max(0, int(time.time() - time.mktime(time.strptime(started, "%Y-%m-%d %H:%M:%S"))))
        except (ValueError, OSError):
            seconds = 0
    counted = seconds
    if estimated and seconds > 24 * 3600:
        counted = 0  # 陈年孤儿不计时长
    if estimated:
        db.execute("UPDATE sessions SET ended_at=?, seconds=?, estimated=1 WHERE id=? AND ended_at IS NULL",
                   (ended, seconds, session_id))
    else:
        db.execute("UPDATE sessions SET ended_at=?, seconds=? WHERE id=? AND ended_at IS NULL",
                   (ended, seconds, session_id))
    if counted > 0:
        db.execute("UPDATE games SET playtime_seconds = playtime_seconds + ?, last_played=? WHERE id=?",
                   (counted, ended, game_id))


def _auto_snapshot(db, game_id, cfg):
    """游戏退出后自动备份存档（后台线程，失败静默——详情页有手动入口）。"""
    try:
        from . import backup
        if cfg is not None and not cfg.get("backup.auto_backup_on_close", True):
            return
        game = db.query_one("SELECT * FROM games WHERE id=?", (game_id,))
        if not game:
            return
        r = backup.snapshot_backup(db, game, kind="auto")
        if r.get("ok"):
            print(f"[GALA] 已自动备份《{game.get('title')}》存档 → {r.get('ts')}")
    except Exception:
        pass  # 自动备份失败不打扰游戏流程


def _monitor(game_id, db, proc, started, session_id, cfg=None):
    proc.wait()
    with _lock:
        RUNNING.pop(game_id, None)
    try:
        elapsed = time.time() - time.mktime(time.strptime(started, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OSError):
        elapsed = 0
    if elapsed < 10:
        # 误启动不计时。必须把 session 关掉（seconds=0）：
        # 否则留下 ended_at=NULL 的孤儿会话，下次启动 reconcile 会按
        # "发现时刻-开始时刻" 补记，最长凭空多出 24 小时幽灵时长（v1.1 修）。
        db.execute("UPDATE sessions SET ended_at=?, seconds=0"
                   " WHERE id=? AND ended_at IS NULL", (now_iso(), session_id))
        return
    _finalize(db, game_id, session_id, started)
    # 关闭游戏 → 自动备份存档（开关在设置页：备份 → 关闭游戏时自动备份）
    threading.Thread(target=_auto_snapshot, args=(db, game_id, cfg), daemon=True).start()


def stop(game_id):
    with _lock:
        info = RUNNING.get(game_id)
    if not info:
        return {"ok": False, "error": "该游戏未在运行"}
    try:
        if info.get("proc") is not None:
            # 普通直启：杀整个进程树（游戏+子进程）
            try:
                import psutil
                psutil.Process(info["proc"].pid).kill()
            except Exception:
                info["proc"].terminate()
            return {"ok": True}
        # 转区启动（无父进程句柄）：按 exe 名杀
        exe = info.get("exe") or ""
        if exe:
            name = os.path.basename(exe).lower()
            import psutil
            for p in psutil.process_iter(["name"]):
                if (p.info.get("name") or "").lower() == name:
                    try:
                        p.kill()
                    except Exception:
                        pass
        return {"ok": True, "note": "已发送终止（转区游戏按进程名结束）"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def running_ids():
    # 只返回可 JSON 序列化的字段（game_id -> started）。
    # 坑：之前直接 dict(RUNNING) 会把 {"proc": Popen, ...} 透传给 pywebview 桥
    # → TypeError: Object of type Popen is not JSON serializable（日志反复刷屏）。
    with _lock:
        return {gid: info["started"] for gid, info in RUNNING.items()}


# ---------- 启动补记（应用重启后） ----------
def _proc_names():
    """当前所有进程名集合（小写）。"""
    try:
        import psutil
        return {p.info["name"].lower() for p in psutil.process_iter(["name"])
                if p.info.get("name")}
    except Exception:
        return set()


def _exe_alive(exe_path):
    if not exe_path:
        return False
    name = os.path.basename(exe_path).lower()
    return name in _proc_names()


def reconcile(db):
    """启动时补记上次未结算的 session：
    - exe 进程还活着 → 继续跟踪（轮询进程消失时结算）
    - 进程已不在 → 估算结算：
      gap ≤ 24h 按实际时长计入（当天会话）；
      gap > 24h 的陈年孤儿只标记结束、不计时长（estimated=1），
      避免按旧逻辑"上限 8 小时"凭空伪造游玩时长
    """
    orphans = db.query(
        "SELECT s.id, s.game_id, s.started_at, g.exe_path"
        " FROM sessions s JOIN games g ON g.id = s.game_id"
        " WHERE s.ended_at IS NULL")
    for s in orphans:
        if _exe_alive(s.get("exe_path")):
            threading.Thread(target=_poll_alive,
                             args=(db, s["id"], s["game_id"], s["started_at"], s.get("exe_path")),
                             daemon=True).start()
            continue
        try:
            gap = time.time() - time.mktime(time.strptime(s["started_at"], "%Y-%m-%d %H:%M:%S"))
        except (ValueError, OSError):
            gap = 0
        if gap > 24 * 3600:
            # 陈年孤儿：只标记结束（结束时刻用发现时刻），不碰游戏总时长/最后游玩
            db.execute("UPDATE sessions SET ended_at=?, seconds=0, estimated=1"
                       " WHERE id=? AND ended_at IS NULL", (now_iso(), s["id"]))
        else:
            _finalize(db, s["game_id"], s["id"], s["started_at"], estimated=True)


def _poll_alive(db, session_id, game_id, started, exe_path):
    """轮询进程是否还在；消失后结算（用于重启后仍在运行的游戏）。"""
    while _exe_alive(exe_path):
        time.sleep(30)
    _finalize(db, game_id, session_id, started)
