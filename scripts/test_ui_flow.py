# -*- coding: utf-8 -*-
"""UI 端到端测试：隐藏 pywebview 窗口 + 注入 JS 驱动真实界面（真实桥接/真实后端）。
临时插入一条 __edit_test__ 游戏，验证: 打开详情→编辑→保存→换封面，最后清理。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webview  # noqa: E402

from backend.db import Database  # noqa: E402
from backend.config import Config  # noqa: E402
from backend import api as api_mod  # noqa: E402
from backend.app import start_http_server  # noqa: E402

db = Database()
db.init()
cfg = Config()
jsapi = api_mod.JsApi(db, cfg)

sid = db.execute(
    "INSERT INTO games (title, status, source) VALUES (?,2,'manual')", ("__edit_test__",))

port = start_http_server()
api_mod.BASE_URL = f"http://127.0.0.1:{port}"
print(f"[TEST] BASE_URL={api_mod.BASE_URL} scratch_id={sid}", flush=True)

window = webview.create_window(
    "GALA UI TEST",
    f"http://127.0.0.1:{port}/frontend/dist/index.html",
    js_api=jsapi, hidden=True, width=1280, height=820,
    background_color="#171a21")
jsapi._window = window


def ev(js):
    return window.evaluate_js(js)


def log(m):
    print(m, flush=True)


def run():
    time.sleep(4)
    try:
        bridge = ev("!!window.pywebview && !!window.pywebview.api")
        log(f"[0] 桥接注入: {bridge}")
        n = ev("document.querySelectorAll('.game-card').length")
        log(f"[1] 网格卡片数: {n}")

        found = ev("""(() => {
            const c = [...document.querySelectorAll('.game-card')]
                .find(x => x.querySelector('.card-title')?.textContent === '__edit_test__');
            if (!c) return false;
            c.click(); return true;
        })()""")
        log(f"[2] 找到并点击测试卡片: {found}")
        time.sleep(2)
        ht = ev("document.querySelector('.hero-title')?.textContent")
        log(f"[3] 详情页标题: {ht}")

        ev("[...document.querySelectorAll('button')].find(b => b.textContent.includes('编辑'))?.click()")
        time.sleep(1)
        editing = ev("!!document.querySelector('.edit-table')")
        log(f"[4] 进入编辑模式: {editing}")

        ev("""(() => {
            const inputs = document.querySelectorAll('.edit-table input');
            const set = (el, v) => { el.value = v; el.dispatchEvent(new Event('input', {bubbles:true})); };
            set(inputs[0], 'UI测试译名');
            set(inputs[3], 'UI测试标题');
            set(inputs[4], 'UI测试会社');
            set(inputs[6], '9.1');
            set(inputs[8], 'D:/fake/exe.exe');
            const ta = document.querySelector('.edit-table textarea');
            set(ta, '这是通过UI自动化写入的中文简介。');
            return 'filled';
        })()""")
        time.sleep(0.5)

        ev("[...document.querySelectorAll('button')].find(b => b.textContent.includes('保存'))?.click()")
        time.sleep(2)
        ht2 = ev("document.querySelector('.hero-title')?.textContent")
        log(f"[5] 保存后详情标题: {ht2}")

        g = db.query_one("SELECT title,title_zh,maker,rating,exe_path,description,status,source FROM games WHERE id=?", (sid,))
        log(f"[6] DB 校验: {dict(g) if g else None}")

        # 封面: 编辑模式 → URL → 下载
        ev("[...document.querySelectorAll('button')].find(b => b.textContent.includes('编辑'))?.click()")
        time.sleep(1)
        ev("""(() => {
            const el = document.querySelector('.url-input');
            el.value = 'https://t.vndb.org/cv/30/85430.jpg';
            el.dispatchEvent(new Event('input', {bubbles:true}));
            return true;
        })()""")
        time.sleep(0.3)
        ev("[...document.querySelectorAll('.cover-tools button')].find(b => b.textContent.includes('下载'))?.click()")
        time.sleep(5)
        img = ev("document.querySelector('.hero-cover img')?.src")
        log(f"[7] 封面 img src: {img}")
        cover_file = os.path.join("cache", "covers", f"{sid}.jpg")
        log(f"[8] 封面落盘: exists={os.path.exists(cover_file)} size={os.path.getsize(cover_file) if os.path.exists(cover_file) else 0}")
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        db.execute("DELETE FROM games WHERE id=?", (sid,))
        db.execute("DELETE FROM game_tags WHERE game_id=?", (sid,))
        try:
            if os.path.exists(cover_file):
                os.remove(cover_file)
        except Exception:
            pass
        log("[DONE] 测试结束，已清理")
        try:
            window.destroy()
        except Exception:
            pass


webview.start(run)
