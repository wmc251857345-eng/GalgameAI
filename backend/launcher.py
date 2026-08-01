"""启动器：进程管理 + Locale Emulator + 游玩时长统计。"""
import os
import subprocess
import threading
import time

from .utils import now_iso

RUNNING = {}  # game_id -> {"proc": Popen, "started": iso}
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


def launch(db, game):
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
    with _lock:
        RUNNING[game["id"]] = {"proc": p, "started": started}
    threading.Thread(target=_monitor, args=(game["id"], db, p, started), daemon=True).start()
    return {"ok": True, "pid": p.pid}


def _monitor(game_id, db, proc, started):
    proc.wait()
    seconds = max(0, int(time.time() - time.mktime(time.strptime(started, "%Y-%m-%d %H:%M:%S"))))
    with _lock:
        RUNNING.pop(game_id, None)
    if seconds < 10:  # 误启动不计时
        return
    db.execute("INSERT INTO sessions (game_id, started_at, ended_at, seconds) VALUES (?,?,?,?)",
               (game_id, started, now_iso(), seconds))
    db.execute("UPDATE games SET playtime_seconds = playtime_seconds + ?, last_played = ? WHERE id=?",
               (seconds, now_iso(), game_id))


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
    with _lock:
        return dict(RUNNING)  # game_id -> started
