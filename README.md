# GALA — Galgame AI Library Agent

本地 Galgame 智能管理器：Steam 风格界面，扫描本地游戏 → 匹配 VNDB/Bangumi → AI 生成中文简介 → 标签 / 时长 / 一键启动（含 Locale Emulator）。

## 架构

```
Vue3 前端 (Steam 风格深色 UI)
   │  pywebview (系统 WebView2)
Python 后端 (流水线: 扫描 → 匹配 → 丰富 → 确认)
   ├─ scanner/   Phase 1  特征提取、exe 启发式、readme 编码
   ├─ matcher/   Phase 1  规范化 + 多策略打分 + 待确认
   ├─ providers/ Phase 2  vndb / bgm / gemini / openai / ocr
   ├─ enrich/    Phase 2  AI 分析流水线 + 断点续跑任务队列
   └─ launcher/  Phase 1  启动 / Locale Emulator / 时长统计
SQLite (library.db, schema v1)
```

## 快速开始

```bash
# 1. 后端依赖
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# 2. 前端依赖
cd frontend && npm install && cd ..

# 3. 开发模式（vite 热更新 + pywebview）
dev.bat
# 或分开跑: cd frontend && npm run dev  ← 另一个终端
#          venv\Scripts\python -m backend.app --dev

# 4. 生产模式（加载构建产物）
cd frontend && npm run build && cd ..
run.bat
# 或: venv\Scripts\python -m backend.app
```

浏览器单独预览前端（不弹桌面窗口）：`cd frontend && npm run dev` 后访问 http://localhost:5173 —— api.js 会自动降级为 mock 数据。

## 目录

```
backend/    Python 后端（app / api / config / db / paths）
frontend/   Vue3 + Vite + Pinia
scripts/    build.py 一键构建
config/     配置文件（含 API key，不入库）
database/   library.db
cache/      封面 / 缩略图 / AI 结果缓存
logs/       日志
```

## 路线图

- **Phase 0 ✅** 骨架：pywebview + Vue3 打通、DB schema v1、Steam 风格壳层
- **Phase 1 ✅** 扫描 / 匹配 / 待确认 / 封面下载 / 详情页 / 启动器(LE) / 时长统计
- **Phase 2 ✅** provider 抽象 + 能力矩阵、AI 中文简介、断点续跑任务队列、手动编辑（信息/标签/封面/删除）、VNDB 刷新
- **Phase 3 🔶** Bangumi ✅ · 统计页 ✅ · 导出/备份 ✅ · 批量补封面 ✅ · 收藏/筛选/双视图/随机 ✅ · match_cache 纠正记忆 ✅ · 失效路径重定位 ✅ · 启动补记时长 ✅ · 托盘 ✅ · 自动备份 ✅ · 连接自检 ✅ · FTS 全文搜索（待做）
- **Phase 4 ⬜** 插件化 + PyInstaller 单 exe 打包

## 开发注意事项（踩过的坑）

1. **pywebview js_api 注入有竞态**：Vue 挂载可能早于桥接注入，`store.load()` 会走到 mock 分支导致整个应用显示假数据（表现为"扫描/编辑没反应"）。前端必须 `await apiReady()`（监听 `pywebviewready` 事件 + 轮询兜底）后再拉数据。
2. **`_game_row` / `_tags` 是模块级函数**，签名 `_game_row(g, db, with_extra=False)`，必须传 db。曾因 `_game_row` 调类方法 `_tags` 导致 `get_game` 抛 NameError、详情页永远打不开。
3. **VNDB 评分是 0-100 制**：入库时 `_apply_match` 统一转 10 分制（>20 则 /10），展示层 `rating_disp` 兼容历史遗留原始值。
4. **回归测试**：`scripts/verify.py`（规范验证：迁移幂等/库体验/记忆/稳定性/构建新鲜度，跑 `venv\Scripts\python scripts/verify.py`）、`scripts/test_edit_flow.py`（后端 API 全链路，DB 副本）和 `scripts/test_ui_flow.py`（隐藏 pywebview 窗口 + 注入 JS 驱动真实 UI）。改完记得跑。
5. **删除游戏**必须级联清理 sessions/staff/screenshots/analysis_jobs 等表，并删 cache/covers 里的封面文件。
6. **BGM API 搜索返回 `{"results":N,"list":[...]}` 字典**，不是裸列表——`isinstance(data, list)` 判断会让 bgm.search 永远空（曾导致 bgm 数据源静默失效）。
7. **pywebview closing 事件可取消**：handler 返回 `False` → 取消关闭（用于"关窗最小化到托盘"）；托盘用 pystray `run_detached()`。
8. **无损迁移**：新增列用 `PRAGMA table_info` 检查 + `ALTER TABLE`，不要 bump SCHEMA_VERSION（会删库重建）。favorite / match_cache.provider 都这么加的。
9. 扫描器 exe 启发式、readme 编码（Shift-JIS/GBK）、代理（v2rayN 127.0.0.1:7897）、DoH 防 DNS 污染均已内置。
