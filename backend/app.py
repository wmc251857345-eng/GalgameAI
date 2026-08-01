"""GALA 应用入口。

用法（项目根目录）:
  venv\\Scripts\\python -m backend.app          # 生产（HTTP 服务 + dist）
  venv\\Scripts\\python -m backend.app --dev    # 开发（vite dev server）
"""
import http.server
import os
import socketserver
import sys
import threading

from . import paths


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=paths.BASE, **kw)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def start_http_server():
    """本地 HTTP 服务：托管 frontend/dist + cache/（封面）。返回端口。"""
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1]


def main():
    try:
        import webview
    except Exception as e:
        print(f"[GALA] pywebview 加载失败: {e}")
        sys.exit(1)

    from . import api
    from .api import JsApi
    from .config import Config
    from .db import Database

    db = Database()
    db.init()
    cfg = Config()
    jsapi = JsApi(db, cfg)

    port = start_http_server()
    api.BASE_URL = f"http://127.0.0.1:{port}"
    print(f"[GALA] v{api.VERSION}  HTTP: {api.BASE_URL}")

    dev = "--dev" in sys.argv
    url = f"{api.BASE_URL}/frontend/dist/index.html"
    if dev:
        url = "http://localhost:5173"
    else:
        dist = os.path.join(paths.BASE, "frontend", "dist", "index.html")
        if not os.path.exists(dist):
            print(f"[GALA] 未找到 {dist}，请先: cd frontend && npm run build")
            sys.exit(1)

    print(f"[GALA] 加载: {url}")
    window = webview.create_window(
        "GALA — Galgame AI Library Agent",
        url,
        js_api=jsapi,
        width=1280,
        height=820,
        min_size=(980, 640),
        background_color="#171a21",
    )
    jsapi._window = window  # 供文件对话框等使用
    webview.start()
    print("[GALA] 已退出")


if __name__ == "__main__":
    main()
