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
- **Phase 1** 扫描 / 匹配 / 待确认 / 封面下载 / 详情页 / 启动器(LE) / 时长统计
- **Phase 2** provider 抽象 + 能力矩阵、AI 中文简介、断点续跑任务队列
- **Phase 3** Bangumi、FTS 搜索、统计页、导出备份
- **Phase 4** 插件化 + PyInstaller 单 exe 打包
