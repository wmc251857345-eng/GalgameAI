"""Playwright 冒烟：GALA 前端渲染层（无 pywebview 桥接 → fallback mock 数据）"""
import sys
sys.path.insert(0, r"G:\GalgameAI")
from playwright.sync_api import sync_playwright

EXE = r"G:\Hermes\hermes_portable\playwright-browsers\chromium-1228\chrome-win64\chrome.exe"
URL = "http://127.0.0.1:49855/frontend/dist/index.html"

errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=EXE, headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type in ("error",) else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    page.goto(URL, timeout=20000, wait_until="load")
    page.wait_for_timeout(2500)

    # 网格里有多少游戏（mock）
    cards = page.locator(".card, .list-row").count()
    print(f"游戏卡片数: {cards}")

    # 点第一个游戏 → 详情页
    if cards > 0:
        page.locator(".card, .list-row").first.click()
        page.wait_for_timeout(2000)
        body = page.inner_text("body")
        detail_ok = ("返回游戏库" in body) or ("启动游戏" in body) or ("编辑" in body)
        print(f"详情页渲染: {'OK' if detail_ok else 'FAIL'} | 片段: {body[:80]!r}")

    # 侧栏切换视图
    page.wait_for_timeout(500)
    print(f"JS 错误数: {len(errors)}")
    for e in errors[:5]:
        print("  ", e[:120])

    browser.close()
