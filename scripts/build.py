"""一键构建：1) 前端 vite build  2) PyInstaller 打包 exe（便携结构）。

产物: dist/GalgameAI/
  GalgameAI.exe
  frontend/dist/          <- 前端资源（拷贝，frozen 后 paths.BASE=exe目录 直接可用）
  _internal/              <- 依赖（PyInstaller 6 onedir）
首次运行自动生成: config/ database/ cache/ plugins/ logs/ （exe 旁，便携）
"""
import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "dist", "GalgameAI")


def run(cmd, cwd=None, **kw):
    print(f"$ {cmd}")
    subprocess.run(cmd, cwd=cwd or BASE, check=True, shell=True, **kw)


def main():
    # 1/3 前端构建（vite build，产物带内容 hash）
    print("== 1/3 构建前端 ==")
    run("npm run build", cwd=os.path.join(BASE, "frontend"))
    dist_html = os.path.join(BASE, "frontend", "dist", "index.html")
    assert os.path.exists(dist_html), "前端构建产物缺失"

    # 2/3 PyInstaller 打包（onedir 便携结构）
    print("== 2/3 PyInstaller 打包 ==")
    # 版本号直接读源码字面量（不 import backend，避免脚本环境缺依赖/慢启动）
    import re as _re
    with open(os.path.join(BASE, "backend", "api.py"), encoding="utf-8") as f:
        m = _re.search(r'^VERSION\s*=\s*["\']([^"\']+)', f.read(), _re.M)
    VERSION = m.group(1) if m else "0.0.0"
    cmd = (
        f'"{sys.executable}" -m PyInstaller '
        "--noconfirm --clean "
        '--name GalgameAI '
        "--windowed "          # 无控制台窗口
        "--onedir "           # 目录结构（启动快、便于排错；exe 旁放便携数据）
        # pywebview 动态选择平台后端，必须显式收集 winforms
        '--hidden-import webview.platforms.winforms '
        # 系统托盘（pystray 走 win32 ctypes，动态加载需显式收集，否则打包版托盘静默失效）
        "--hidden-import pystray --hidden-import pystray._win32 "
        # collect-all 双保险：环境 PYTHONPATH 被 Hermes venv 遮蔽时静态分析可能漏收，
        # 强制整包收集（pystray 是纯 Python 小包，代价可忽略）
        "--collect-all pystray "
        f'"{os.path.join(BASE, "main.py")}"'
    )
    run(cmd)

    # 3/3 前端资源拷贝到 exe 旁（frozen 后 paths.BASE = exe 目录）
    print("== 3/3 拷贝前端资源 ==")
    dst = os.path.join(OUT, "frontend", "dist")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(os.path.join(BASE, "frontend", "dist"), dst)

    # 3.5 版本清单：构建时写入 version.json（版本号+构建日期+git短哈希），
    # 供前端"版本自检"展示，也便于排查"我装的到底是不是最新版"
    print("== 3.5 写版本清单 ==")
    import datetime as _dt
    git_sha = ""
    try:
        import subprocess as _sp
        git_sha = _sp.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=BASE,
            stderr=_sp.DEVNULL).decode().strip()
    except Exception:
        pass
    import json as _json
    with open(os.path.join(OUT, "version.json"), "w", encoding="utf-8") as f:
        _json.dump({"version": VERSION, "build_date": _dt.date.today().isoformat(),
                    "git": git_sha}, f, ensure_ascii=False, indent=2)
    print(f"  version.json ← v{VERSION} ({git_sha or 'no-git'})")

    # 4/4 便携数据迁移：PyInstaller --clean 会删掉 dist 目录里的 database/cache/config，
    # 打包后从开发库自动回填（已有数据则跳过，保留用户改动的便携数据）
    print("== 4/4 便携数据迁移 ==")
    dev_db = os.path.join(BASE, "database", "library.db")
    exe_db = os.path.join(OUT, "database", "library.db")
    if not os.path.exists(exe_db) and os.path.exists(dev_db):
        os.makedirs(os.path.join(OUT, "database"), exist_ok=True)
        shutil.copy(dev_db, exe_db)
        print(f"  database/library.db ← 开发库")
    dev_covers = os.path.join(BASE, "cache", "covers")
    if os.path.isdir(dev_covers):
        os.makedirs(os.path.join(OUT, "cache", "covers"), exist_ok=True)
        for f in os.listdir(dev_covers):
            s, d = os.path.join(dev_covers, f), os.path.join(OUT, "cache", "covers", f)
            if os.path.isfile(s) and not os.path.exists(d):
                shutil.copy(s, d)
        print(f"  cache/covers ← {len(os.listdir(dev_covers))} 个封面")
    dev_cfg = os.path.join(BASE, "config", "config.json")
    exe_cfg = os.path.join(OUT, "config", "config.json")
    if not os.path.exists(exe_cfg) and os.path.exists(dev_cfg):
        os.makedirs(os.path.join(OUT, "config"), exist_ok=True)
        # 路径重写：开发配置里指向【开发根】的绝对路径（backup 目标等）在部署版会失效，
        # 一并改写为 exe 旁目录，避免部署版备份写到源码目录（历史踩坑）。
        import json as _json
        try:
            with open(dev_cfg, "r", encoding="utf-8") as f:
                _cfg = _json.load(f)
            _local_bak = os.path.join(OUT, "database", "ludusavi_backups").replace("\\", "\\\\")
            for t in (_cfg.get("backup", {}).get("targets") or []):
                if isinstance(t, dict) and str(t.get("path", "")).startswith(BASE):
                    t["path"] = _local_bak
            if str(_cfg.get("backup", {}).get("root") or "").startswith(BASE):
                _cfg["backup"]["root"] = _local_bak
            with open(exe_cfg, "w", encoding="utf-8") as f:
                _json.dump(_cfg, f, ensure_ascii=False, indent=2)
            print("  config/config.json ← 开发配置（backup 目标已重写到 exe 旁）")
        except Exception as e:
            shutil.copy(dev_cfg, exe_cfg)
            print(f"  config/config.json ← 开发配置（路径重写失败，原样复制: {e}）")

    print(f"== 完成: {OUT} ==")
    exe = os.path.join(OUT, "GalgameAI.exe")
    assert os.path.exists(exe), "exe 未生成"
    print(f"exe: {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
