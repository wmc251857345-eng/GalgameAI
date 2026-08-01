"""GALA 应用入口。

用法（项目根目录）:
  venv\\Scripts\\python -m backend.app          # 生产（HTTP 服务 + dist）
  venv\\Scripts\\python -m backend.app --dev    # 开发（vite dev server）
"""
import http.server
import logging
import os
import socketserver
import sys
import threading
import time
import traceback

from . import paths


def _setup_logging():
    """文件日志 + 全局异常钩子：任何线程崩溃/卡死前兆都留痕（logs/app.log）。"""
    log_file = os.path.join(paths.LOGS_DIR, "app.log")
    logging.basicConfig(
        filename=log_file, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8")

    def _exc(t, v, tb):
        msg = "".join(traceback.format_exception(t, v, tb))
        logging.error("Unhandled exception:\n%s", msg)
        try:
            print(f"[GALA] 未捕获异常 {t.__name__}: {v}", file=sys.stderr)
        except Exception:
            pass

    sys.excepthook = _exc
    threading.excepthook = lambda args: logging.error(
        "Thread %s crashed:\n%s", args.thread.name,
        "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    logging.info("=== GALA 启动 ===")


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


def _startup_tasks(cfg, db):
    """后台启动任务：游玩时长补记 + 自动备份 + 新作预抓取。"""
    time.sleep(3)
    try:
        from . import launcher
        launcher.reconcile(db)
        logging.info("时长补记完成")
    except Exception as e:
        logging.error("时长补记失败: %s", e)
        print(f"[GALA] 时长补记失败: {e}")
    try:
        from .api import JsApi, maybe_auto_backup
        js = JsApi(db, cfg)
        js.refresh_new_releases()  # 启动即预抓取新作（后台，厂商墙打开即有数据）
        logging.info("新作预抓取已启动")
    except Exception as e:
        logging.error("新作预抓取启动失败: %s", e)
    try:
        maybe_auto_backup(cfg, db)
    except Exception as e:
        logging.error("自动备份失败: %s", e)
        print(f"[GALA] 自动备份失败: {e}")

def _start_tray(window):
    """系统托盘：显示/隐藏 + 退出。关窗默认最小化到托盘（closing 事件返回 False 取消关闭）。"""
    try:
        from PIL import Image, ImageDraw
        import pystray
    except Exception as e:
        print(f"[GALA] 托盘不可用: {e}")
        return
    img = Image.new("RGBA", (64, 64), (23, 26, 33, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, 58, 58], radius=12, fill=(102, 192, 244, 255))
    d.polygon([(24, 20), (24, 44), (46, 32)], fill=(16, 19, 25, 255))

    quit_flag = {"q": False}

    def on_toggle(icon, item):
        if window.hidden:
            window.show()
        else:
            window.hide()

    def on_quit(icon, item):
        quit_flag["q"] = True
        icon.stop()
        window.destroy()

    menu = pystray.Menu(
        pystray.MenuItem("显示 / 隐藏 GALA", on_toggle, default=True),
        pystray.MenuItem("退出", on_quit),
    )
    icon = pystray.Icon("gala", img, "GALA — Galgame AI Library", menu)

    def on_closing():
        if not quit_flag["q"]:
            window.hide()  # 关窗 → 缩到托盘
            return False
        return None  # 允许真正退出

    window.events.closing += on_closing
    icon.run_detached()


def main():
    _setup_logging()
    try:
        import webview
    except Exception as e:
        print(f"[GALA] pywebview 加载失败: {e}")
        logging.error("pywebview 加载失败: %s", e)
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

    threading.Thread(target=_startup_tasks, args=(cfg, db), daemon=True).start()
    _start_tray(window)

    webview.start()
    print("[GALA] 已退出")


if __name__ == "__main__":
    main()
