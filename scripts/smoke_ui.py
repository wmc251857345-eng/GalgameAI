"""Playwright 冒烟：GALA 前端渲染层（无 pywebview 桥接 → fallback mock 数据）。

覆盖：库网格 → 详情页 → 待确认 → 厂商墙 → 设置，全视图渲染无 JS 错误。
用法：先起本地 HTTP 服务（见下），再运行本脚本。
"""
import sys
sys.path.insert(0, r"G:\GalgameAI")
from playwright.sync_api import sync_playwright

EXE = r"G:\Hermes\hermes_portable\playwright-browsers\chromium-1228\chrome-win64\chrome.exe"
# 用法：python scripts/smoke_ui.py [URL]（默认打运行中的打包实例；也可指向 vite dev / 任意静态服务）
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:51957/frontend/dist/index.html"

errors = []
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(detail)[:100]) if detail else ""))
    if not cond:
        fails.append(name)


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=EXE, headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    page.goto(URL, timeout=20000, wait_until="load")
    # 等 mock 数据渲染（apiReady 纯浏览器 2s 降级 + 加载）
    page.wait_for_selector(".game-card, .list-row", timeout=15000)
    cards = page.locator(".game-card, .list-row").count()
    check("库网格渲染", cards > 0, f"{cards} 卡")

    # 2. 详情页（cover-hover 覆盖层会拦截卡片中心 force 点击 → 点卡片标题区，安全且真实）
    page.locator(".game-card .card-title").first.click()
    page.wait_for_selector("text=返回游戏库", timeout=8000)
    check("详情页渲染", True)
    page.locator("text=返回游戏库").first.click(force=True)
    page.wait_for_timeout(600)

    # 2.5 排序：默认按公司 → 第一张卡应为 ANIPLEX.EXE 的 ATRI；切换发售时间/标题首字不崩
    first_maker = page.locator(".game-card .ch-maker").first.inner_text()
    check("默认排序按公司", first_maker.strip() == "ANIPLEX.EXE", first_maker)
    page.locator(".sort-btn", has_text="发售时间").click(force=True)
    page.wait_for_timeout(400)
    check("切换发售时间", page.locator(".game-card").count() > 0,
          f"{page.locator('.game-card').count()} 卡")
    page.locator(".sort-btn", has_text="标题首字").click(force=True)
    page.wait_for_timeout(400)
    check("切换标题首字", page.locator(".game-card").count() > 0,
          f"{page.locator('.game-card').count()} 卡")
    page.locator(".sort-btn", has_text="制作组").click(force=True)
    page.wait_for_timeout(400)

    # 2.6 返回游戏库保持滚动位置（详情页返回不跳回第一行）
    saved = page.locator(".content").evaluate(
        "el => { el.scrollTop = el.scrollHeight; return el.scrollTop }")
    page.wait_for_timeout(300)
    # 滚动后第一张卡仍在视口内但封面被 hover 覆盖层拦截 → 点其标题区
    page.locator(".game-card .card-title").first.click()
    page.wait_for_selector("text=返回游戏库", timeout=8000)
    page.locator("text=返回游戏库").first.click(force=True)
    page.wait_for_timeout(700)
    restored = page.locator(".content").evaluate("el => el.scrollTop")
    check("返回游戏库保持滚动位置", abs(restored - saved) < 2, f"{saved}→{restored}")

    # 3. 待确认（mock 有 2 条 + 候选卡）
    page.locator(".nav-item", has_text="待确认").click(force=True)
    page.wait_for_timeout(1200)
    body = page.inner_text("body")
    check("待确认页渲染", "确认" in body and "待确认" in body, body[:60])

    # 4. 厂商墙
    page.locator(".nav-item", has_text="厂商墙").click(force=True)
    page.wait_for_timeout(1200)
    body = page.inner_text("body")
    check("厂商墙渲染", "厂商" in body, body[:60])

    # 5. 设置页
    page.locator(".nav-item", has_text="设置").click(force=True)
    page.wait_for_timeout(1000)
    body = page.inner_text("body")
    check("设置页渲染", "设置" in body, body[:60])

    # 6. 库页导入弹窗（改版：本地文件 + AI 补全录入）
    page.locator(".nav-item", has_text="游戏库").click(force=True)
    page.wait_for_timeout(800)
    page.locator("text=＋ 导入游戏").first.click(force=True)
    page.wait_for_timeout(600)
    body = page.inner_text("body")
    check("导入弹窗打开", "导入本地游戏" in body and "AI 补全录入" in body
          and "选择游戏 exe" in body, body[:60])
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    # 7. 右键菜单（网格卡片）
    card = page.locator(".game-card").first
    box = card.bounding_box()
    if box:
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, button="right")
        page.wait_for_timeout(500)
        body = page.inner_text("body")
        check("右键菜单打开", "打开详情" in body and "删除" in body, body[:60])
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

    # 8. 聊天页：上下文游戏选择器（搜索 → 选游戏 → 快捷操作区出现）
    page.locator(".nav-item", has_text="AI 管家").click(force=True)
    page.wait_for_selector(".ctx-search-input", timeout=8000)
    check("聊天页渲染", page.locator(".ctx-search-input").count() > 0
          and "选一个游戏作为上下文" in (page.locator(".ctx-search-input")
                                          .get_attribute("placeholder") or ""), "")
    page.locator(".ctx-search-input").fill("千恋")
    page.wait_for_selector(".ctx-drop-item", timeout=5000)
    check("上下文候选下拉", page.locator(".ctx-drop-item").count() > 0,
          f"{page.locator('.ctx-drop-item').count()} 项")
    page.locator(".ctx-drop-item").first.click()
    page.wait_for_selector(".ctx-card", timeout=5000)
    body = page.inner_text("body")
    check("聊天上下文选择生效", "说「这个游戏」就是指它" in body and "改标题" in body, body[:60])

    print(f"JS 错误数: {len(errors)}")
    for e in errors[:8]:
        print("  ", e[:140])

    browser.close()

print("\n" + ("SMOKE PASS" if not fails and not errors else "SMOKE FAIL: " + ", ".join(fails)))
sys.exit(0 if not fails and not errors else 1)
