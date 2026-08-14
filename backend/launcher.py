"""启动器：进程管理 + Locale Emulator + 游玩时长统计（session 持久化，重启可补记）。"""
import os
import subprocess
import threading
import time

from .utils import now_iso

RUNNING = {}  # game_id -> {"proc": Popen, "started": iso, "session_id": int}
_lock = threading.Lock()


def find_leproc():
    for base in [os.environ.get("LOCALAPPDATA", ""),
                 "C:\\LocaleEmulator",
                 r"C:\Program Files\Locale Emulator",
                 r"C:\Program Files (x86)\Locale Emulator"]:
        p = os.path.join(base, "LEProc.exe")
        if os.path.exists(p):
            return p
    for d in os.environ.get("PATH", "").split(";"):
        p = os.path.join(d, "LEProc.exe")
        if os.path.exists(p):
            return p
    return None


def launch(db, game, cfg=None):
    exe = game.get("exe_path")
    if not exe or not os.path.exists(exe):
        return {"ok": False, "error": f"exe 不存在: {exe}"}
    workdir = game.get("workdir") or os.path.dirname(exe)
    use_le = bool(game.get("use_locale_emu"))
    if use_le:
        le = find_leproc()
        if not le:
            return {"ok": False, "error": "未找到 LEProc.exe（Locale Emulator）"}
        cmd = [le, "-run", exe]
        workdir = os.path.dirname(le)
    else:
        cmd = [exe]
    args = (game.get("launch_args") or "").strip()
    if args:
        cmd.append(args)
    try:
        p = subprocess.Popen(cmd, cwd=workdir)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    started = now_iso()
    # session 先落库（ended_at=NULL 表示进行中，应用崩溃/关闭后启动时可补记）
    sid = db.execute(
        "INSERT INTO sessions (game_id, started_at, ended_at, seconds) VALUES (?,?,NULL,0)",
        (game["id"], started))
    with _lock:
        RUNNING[game["id"]] = {"proc": p, "started": started, "session_id": sid}
    threading.Thread(target=_monitor, args=(game["id"], db, p, started, sid, cfg), daemon=True).start()
    return {"ok": True, "pid": p.pid}


def _finalize(db, game_id, session_id, started, ended=None, seconds=None):
    """结算一条 session：写 ended_at/seconds 并累加到游戏总时长。"""
    ended = ended or now_iso()
    if seconds is None:
        try:
            seconds = max(0, int(time.time() - time.mktime(time.strptime(started, "%Y-%m-%d %H:%M:%S"))))
        except (ValueError, OSError):
            seconds = 0
    db.execute("UPDATE sessions SET ended_at=?, seconds=? WHERE id=? AND ended_at IS NULL",
               (ended, seconds, session_id))
    db.execute("UPDATE games SET playtime_seconds = playtime_seconds + ?, last_played=? WHERE id=?",
               (seconds, ended, game_id))


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
    if time.time() - time.mktime(time.strptime(started, "%Y-%m-%d %H:%M:%S")) < 10:
        return  # 误启动不计时
    _finalize(db, game_id, session_id, started)
    # 关闭游戏 → 自动备份存档（开关在设置页：备份 → 关闭游戏时自动备份）
    threading.Thread(target=_auto_snapshot, args=(db, game_id, cfg), daemon=True).start()


def stop(game_id):
    with _lock:
        info = RUNNING.get(game_id)
    if not info:
        return {"ok": False, "error": "该游戏未在运行"}
    try:
        info["proc"].terminate()
        return {"ok": True}
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
    - 进程已不在 → 按启动时刻估算结算（上限 8 小时，避免隔夜误计）
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
        else:
            try:
                gap = time.time() - time.mktime(time.strptime(s["started_at"], "%Y-%m-%d %H:%M:%S"))
            except (ValueError, OSError):
                gap = 0
            _finalize(db, s["game_id"], s["id"], s["started_at"],
                      seconds=min(max(0, int(gap)), 8 * 3600))


def _poll_alive(db, session_id, game_id, started, exe_path):
    """轮询进程是否还在；消失后结算（用于重启后仍在运行的游戏）。"""
    while _exe_alive(exe_path):
        time.sleep(30)
    _finalize(db, game_id, session_id, started)
