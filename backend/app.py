"""GALA 应用入口。

用法（在项目根目录）:
  venv\\Scripts\\python -m backend.app          # 加载 frontend/dist（需先 npm run build）
  venv\\Scripts\\python -m backend.app --dev    # 加载 vite dev server (http://localhost:5173)
"""
import os
import sys

from . import paths


def main():
    try:
        import webview
    except Exception as e:
        print(f"[GALA] pywebview 加载失败: {e}")
        print("       请确认: venv\\Scripts\\pip install -r requirements.txt")
        sys.exit(1)

    from .api import JsApi
    from .config import Config
    from .db import Database

    db = Database()
    db.init()
    cfg = Config()
    api = JsApi(db, cfg)

    dev = "--dev" in sys.argv
    if dev:
        url = "http://localhost:5173"
    else:
        dist = os.path.join(paths.BASE, "frontend", "dist", "index.html")
        if not os.path.exists(dist):
            print(f"[GALA] 未找到 {dist}")
            print("       请先构建前端: cd frontend && npm run build")
            sys.exit(1)
        url = dist

    print(f"[GALA] v0.1.0  加载: {url}")
    webview.create_window(
        "GALA — Galgame AI Library Agent",
        url,
        js_api=api,
        width=1280,
        height=820,
        min_size=(980, 640),
        background_color="#171a21",
    )
    webview.start()
    print("[GALA] 已退出")


if __name__ == "__main__":
    main()
