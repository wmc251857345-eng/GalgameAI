"""一键构建：1) 前端 vite build  2) PyInstaller 打包（Phase 4 完善）。"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd, cwd=None):
    print(f"$ {cmd}")
    subprocess.run(cmd, cwd=cwd or BASE, check=True, shell=True)


def main():
    print("== 1/2 构建前端 ==")
    run("npm run build", os.path.join(BASE, "frontend"))
    dist = os.path.join(BASE, "frontend", "dist", "index.html")
    assert os.path.exists(dist), "前端构建产物缺失"
    print(f"== 前端完成: {dist}")

    print("== 2/2 后端打包（Phase 4 启用）==")
    print('pyinstaller --noconfirm --name GalgameAI --windowed '
          '--add-data "frontend/dist;frontend/dist" backend/app.py')
    print("构建完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
