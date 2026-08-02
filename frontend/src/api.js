// 前后端桥：pywebview 环境调用真实后端；浏览器开发环境自动降级为 mock。
const hasBridge = () =>
  typeof window !== 'undefined' && window.pywebview && window.pywebview.api

const delay = (ms = 200) => new Promise((r) => setTimeout(r, ms))

// 慢调用超时保护：网络卡住时提示而不是无限挂起（js_api 桥接 HTTP 无超时）
const withTimeout = (p, ms = 90000, label = '请求') =>
  Promise.race([
    p,
    new Promise((_, rej) =>
      setTimeout(() => rej(new Error(`${label}超时(${ms / 1000}s)，请检查网络后重试`)), ms)),
  ])

// ---------- 桥接就绪等待（修复启动竞态：Vue 挂载可能早于 pywebview 注入 js_api，
// 导致 store.load() 走了 mock 分支、整个应用显示假数据。必须等 pywebviewready） ----------
let _bridgePromise = null
export const apiReady = () => {
  if (!_bridgePromise) {
    _bridgePromise = new Promise((resolve) => {
      if (hasBridge()) return resolve(true)
      let done = false
      const finish = (v) => {
        if (done) return
        done = true
        clearInterval(iv)
        window.removeEventListener('pywebviewready', onReady)
        resolve(v)
      }
      const onReady = () => finish(true)
      const t0 = Date.now()
      const iv = setInterval(() => {
        if (hasBridge()) finish(true)
        else if (Date.now() - t0 > 8000) finish(false)
        // 纯浏览器预览/冒烟：pywebview 对象从未注入 → 2s 后直接降级 mock，
        // 不必干等 8s（生产环境 pywebview 对象在页面加载早期就存在，不受影响）
        else if (!window.pywebview && Date.now() - t0 > 2000) finish(false)
      }, 100)
      window.addEventListener('pywebviewready', onReady)
    })
  }
  return _bridgePromise
}

// ---------- mock 数据（浏览器预览用） ----------
const MOCK_GAMES = [
  { id: 1, title: '千恋万花', title_en: 'Senren * Banka', maker: 'Yuzusoft', year: '2016', score: 8.8, tags: ['纯爱', '废萌', '和风'], playtime_hours: 30.5, hue: 330, status: 2 },
  { id: 2, title: 'Summer Pockets', title_en: 'Summer Pockets', maker: 'Key', year: '2018', score: 9.1, tags: ['催泪', '夏', '全年龄'], playtime_hours: 42.0, hue: 200, status: 2 },
  { id: 3, title: 'Mama×Holic', title_en: 'Mama×Holic', maker: 'Atelier Kaguya', year: '2020', score: 7.6, tags: ['母系', '恋爱喜剧', '学园'], playtime_hours: 12.3, hue: 10, status: 1 },
  { id: 4, title: '9-nine- 九次九日九重色', title_en: '9-nine-', maker: 'PALETTE', year: '2017', score: 8.5, tags: ['超能力', '悬疑'], playtime_hours: 8.0, hue: 150, status: 2 },
  { id: 5, title: '美少女万华镜 -理と迷宮の少女-', title_en: 'Bishoujo Mangekyou', maker: 'ωstar', year: '2020', score: 8.9, tags: ['实用', '悬疑', '惊悚'], playtime_hours: 15.2, hue: 270, status: 2 },
  { id: 6, title: 'WHITE ALBUM2', title_en: 'WHITE ALBUM2', maker: 'Leaf', year: '2010', score: 9.3, tags: ['胃疼', '恋爱', '冬'], playtime_hours: 60.1, hue: 210, status: 2 },
  { id: 7, title: 'ATRI -My Dear Moments-', title_en: 'ATRI', maker: 'ANIPLEX.EXE', year: '2020', score: 8.7, tags: ['科幻', '催泪'], playtime_hours: 10.8, hue: 190, status: 1 },
  { id: 8, title: '素晴らしき日々', title_en: 'Wonderful Everyday', maker: 'ケロQ', year: '2010', score: 9.4, tags: ['哲学', '电波', '猎奇'], playtime_hours: 45.0, hue: 45, status: 2 },
]

const MOCK_CONFIG = {
  provider: { name: 'custom', model: 'gcli-gemini-3-flash-preview-search', api_key: '', base_url: 'https://catiecli.sukaka.top/v1', vision: true, search: true },
  proxy: { enabled: false, url: 'http://127.0.0.1:7897' },
  vndb_token: '',
  library_roots: [],
  ui: { theme: 'dark', language: 'zh-CN' },
  analysis: { auto_confirm_threshold: 0.9, concurrency: 2 },
  backup: { auto_enabled: true, interval_days: 7 },
}

const MOCK_PENDING = MOCK_GAMES.filter((g) => g.status === 1).map((g) => ({
  ...g,
  candidates: [
    { ...g, provider: 'bgm', external_id: '12345', title: g.title, score: 0.92 },
    { ...g, provider: 'vndb', external_id: 'v999', title: g.title_en, score: 0.55 },
  ],
}))

const MOCK_ROOT = ['D:\\Games_HDD\\GalGame']

// ---------- 导出 API ----------
export const api = {
  // 基础
  async ping() { return hasBridge() ? window.pywebview.api.ping() : 'mock-pong' },

  async getAppInfo() {
    if (hasBridge()) return window.pywebview.api.get_app_info()
    return { name: 'GALA', version: '0.2.0', python: '3.11.9', platform: 'browser-mock', db_path: '(mock)', base_url: '' }
  },

  // 配置
  async getConfig() {
    if (hasBridge()) return window.pywebview.api.get_config()
    await delay()
    return JSON.parse(JSON.stringify(MOCK_CONFIG))
  },

  async setConfig(key, value) {
    if (hasBridge()) return window.pywebview.api.set_config(key, value)
    await delay()
    const parts = key.split('.')
    let node = MOCK_CONFIG
    for (let i = 0; i < parts.length - 1; i++) node = node[parts[i]]
    node[parts[parts.length - 1]] = value
    return JSON.parse(JSON.stringify(MOCK_CONFIG))
  },

  // 库
  async getLibrarySummary() {
    if (hasBridge()) return window.pywebview.api.get_library_summary()
    await delay()
    return {
      total: MOCK_GAMES.length,
      pending: MOCK_GAMES.filter((g) => g.status === 1).length,
      confirmed: MOCK_GAMES.filter((g) => g.status === 2).length,
      playtime_hours: Math.round(MOCK_GAMES.reduce((s, g) => s + g.playtime_hours, 0) * 10) / 10,
      makers: new Set(MOCK_GAMES.map((g) => g.maker)).size,
    }
  },

  async getStats() {
    if (hasBridge()) return window.pywebview.api.get_stats()
    await delay()
    return {
      overview: { total: 8, confirmed: 6, pending: 2, skipped: 0, favorites: 1, hanhua: 3, playtime_hours: 168.4, played_count: 5, total_size_gb: 45.2 },
      makers: [{ name: 'Yuzusoft', count: 2, avg_rating: 8.8, playtime_hours: 30.5 }],
      tags: [{ name: '纯爱', count: 3 }, { name: '催泪', count: 2 }],
      years: [{ year: '2018', count: 2 }, { year: '2016', count: 1 }],
      top_played: [{ id: 1, title: '千恋万花', hours: 30.5, last_played: '2026-07-01' }],
      sources: { vndb: 4, ai: 3, manual: 1 },
    }
  },

  async listGames() {
    if (hasBridge()) return window.pywebview.api.list_games(1000, 0, 'title', '')
    await delay(300)
    return MOCK_GAMES
  },

  async getGame(id) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.get_game(id), 20000, '游戏详情')
    }
    await delay()
    const g = MOCK_GAMES.find((x) => x.id === id)
    return g ? { ...g, candidates: MOCK_PENDING.find((p) => p.id === id)?.candidates || [], running: false } : null
  },

  async getPending() {
    if (hasBridge()) return window.pywebview.api.get_pending()
    await delay()
    return MOCK_PENDING
  },

  // 扫描 / 分析
  async scanLibrary() {
    if (hasBridge()) return window.pywebview.api.scan_library()
    return { ok: true }
  },

  async analyzePending() {
    if (hasBridge()) return window.pywebview.api.analyze_pending()
    return { ok: true }
  },

  async getScanProgress() {
    if (hasBridge()) return window.pywebview.api.get_scan_progress()
    return { running: false, stage: 'idle', total: 0, done: 0, current: '', error: null, log: [] }
  },

  async confirmMatch(gameId, provider, externalId) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.confirm_match(gameId, provider, externalId), 30000, '确认')
    }
    await delay()
    return { ok: true }
  },

  async markUnmatched(gameId) {
    if (hasBridge()) return window.pywebview.api.mark_unmatched(gameId)
    return { ok: true }
  },

  async reanalyzeGame(gameId) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.reanalyze_game(gameId), 10000, '分析启动')
    }
    await delay(600)
    return { ok: true }
  },

  async getJobStatus() {
    if (hasBridge()) return window.pywebview.api.get_job_status()
    await delay()
    return { running: false, game_id: null, stage: 'idle', result: null, error: null }
  },

  // 库根目录
  async listLibraryRoots() {
    if (hasBridge()) return window.pywebview.api.list_library_roots()
    await delay()
    return [...MOCK_ROOT]
  },

  async addLibraryRoot(path) {
    if (hasBridge()) return window.pywebview.api.add_library_root(path)
    await delay()
    MOCK_ROOT.push(path)
    return { ok: true, roots: [...MOCK_ROOT] }
  },

  async removeLibraryRoot(path) {
    if (hasBridge()) return window.pywebview.api.remove_library_root(path)
    await delay()
    const i = MOCK_ROOT.indexOf(path)
    if (i >= 0) MOCK_ROOT.splice(i, 1)
    return { ok: true, roots: [...MOCK_ROOT] }
  },

  // 启动
  async launchGame(id) {
    if (hasBridge()) return window.pywebview.api.launch_game(id)
    await delay()
    return { ok: true, pid: 12345 }
  },

  async stopGame(id) {
    if (hasBridge()) return window.pywebview.api.stop_game(id)
    return { ok: true }
  },

  async getRunning() {
    if (hasBridge()) return window.pywebview.api.get_running()
    return {}
  },

  async setLocaleEmu(id, enabled) {
    if (hasBridge()) return window.pywebview.api.set_locale_emu(id, enabled)
    return { ok: true }
  },

  // 手动编辑
  async updateGame(id, fields) {
    if (hasBridge()) return window.pywebview.api.update_game(id, fields)
    await delay()
    return { ok: true }
  },

  async updateTags(id, tags) {
    if (hasBridge()) return window.pywebview.api.update_tags(id, tags)
    await delay()
    return { ok: true, tags }
  },

  async chooseCover(id) {
    if (hasBridge()) return window.pywebview.api.choose_cover(id)
    await delay()
    return { ok: false, error: '浏览器预览模式无法弹文件对话框' }
  },

  async setCoverUrl(id, url) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.set_cover_url(id, url), 45000, '封面下载')
    }
    await delay()
    return { ok: true }
  },

  // 封面裁剪（x/y/w/h 为原图 0~1 小数比例）与重置自动适配
  async setCoverCrop(id, x, y, w, h) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.set_cover_crop(id, x, y, w, h), 30000, '封面裁剪')
    }
    await delay()
    return { ok: false, error: '浏览器预览模式无法裁剪' }
  },

  async clearCoverCrop(id) {
    if (hasBridge()) return window.pywebview.api.clear_cover_crop(id)
    await delay()
    return { ok: true }
  },

  // 制作组锚定：全部规范厂商 + 手动合并
  async listMakers() {
    if (hasBridge()) return window.pywebview.api.list_makers()
    await delay()
    return { ok: true, makers: [] }
  },

  async mergeMakers(src, dst) {
    if (hasBridge()) return window.pywebview.api.merge_makers(src, dst)
    await delay()
    return { ok: true, canonical: dst }
  },

  async removeGame(id) {
    if (hasBridge()) return window.pywebview.api.remove_game(id)
    await delay()
    return { ok: true }
  },

  // 手动导入 / AI 补全
  async searchCandidates(keyword) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.search_candidates(keyword), 30000, '候选搜索')
    }
    await delay()
    return { ok: true, candidates: [] }
  },

  async importGameCandidate(candidate) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.import_game_candidate(candidate), 20000, '导入')
    }
    await delay()
    return { ok: true, id: 999 }
  },

  async addGameManual(fields) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.add_game_manual(fields), 20000, '创建条目')
    }
    await delay()
    return { ok: true, id: 999 }
  },

  // 本地导入：选文件 + 备注 → AI 补全
  async pickGamePath(kind) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.pick_game_path(kind), 30000, '文件选择')
    }
    await delay()
    return { ok: false, error: '浏览器预览模式无法弹文件对话框' }
  },

  async importLocalGame(fields) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.import_local_game(fields), 90000, 'AI 补全录入')
    }
    await delay(600)
    return { ok: true, id: 999, title: '(mock)', matched: '', provider: 'manual', alternates: [] }
  },

  async reimportGameSource(id, candidate) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.reimport_game_source(id, candidate), 20000, '换用资料')
    }
    await delay()
    return { ok: true, id }
  },

  // 封面 / 维护
  async refreshCover(id) {
    if (hasBridge()) return window.pywebview.api.refresh_cover(id)
    await delay()
    return { ok: true }
  },

  async fillMissingCovers() {
    if (hasBridge()) return window.pywebview.api.fill_missing_covers()
    await delay()
    return { ok: true }
  },

  async exportGames() {
    if (hasBridge()) return window.pywebview.api.export_games()
    await delay()
    return { ok: true, path: '(mock)' }
  },

  async backupDb() {
    if (hasBridge()) return window.pywebview.api.backup_db()
    await delay()
    return { ok: true, path: '(mock)' }
  },

  // 收藏 / 筛选维度 / 维护
  async toggleFavorite(id) {
    if (hasBridge()) return window.pywebview.api.toggle_favorite(id)
    await delay()
    return { ok: true, favorite: true }
  },

  async getLibraryFacets() {
    if (hasBridge()) return window.pywebview.api.get_library_facets()
    await delay()
    return {
      tags: [...new Set(MOCK_GAMES.flatMap((g) => g.tags || []))].slice(0, 12).map((t) => ({ name: t, c: 1 })),
      makers: [...new Set(MOCK_GAMES.map((g) => g.maker).filter(Boolean))].slice(0, 10).map((m) => ({ maker: m, c: 1 })),
      years: [...new Set(MOCK_GAMES.map((g) => g.year).filter(Boolean))].map((y) => ({ y, c: 1 })),
    }
  },

  async testConnection() {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.test_connection(), 120000, '连接测试')
    }
    await delay(500)
    return { bgm: { ok: true, ms: 120 }, vndb: { ok: true, ms: 900 }, llm: { ok: true, ms: 800 } }
  },

  async getMissingPaths() {
    if (hasBridge()) return window.pywebview.api.get_missing_paths()
    await delay()
    return []
  },

  async relocateGame(id) {
    if (hasBridge()) return window.pywebview.api.relocate_game(id)
    await delay()
    return { ok: true }
  },

  async cancelTask() {
    if (hasBridge()) return window.pywebview.api.cancel_task()
    return { ok: true }
  },

  // 多提供商
  async setActiveProvider(name) {
    if (hasBridge()) return window.pywebview.api.set_active_provider(name)
    await delay()
    return { ok: true }
  },

  async testProvider(provider) {
    if (hasBridge()) return window.pywebview.api.test_provider(provider)
    await delay(800)
    return { ok: true, ms: 300 }
  },

  // AI 管家对话
  async chatSend(message, contextGameId) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.chat_send(message, contextGameId), 180000, '管家回复')
    }
    await delay(1500)
    return { ok: true, reply: '(mock) 管家回复', actions: [] }
  },

  async chatHistory() {
    if (hasBridge()) return window.pywebview.api.chat_history()
    await delay()
    return []
  },

  async chatClear() {
    if (hasBridge()) return window.pywebview.api.chat_clear()
    return { ok: true }
  },

  // 厂商/系列追踪
  async getMakerProfile(maker) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.get_maker_profile(maker), 60000, '厂商档案')
    }
    await delay(800)
    return { ok: false, error: '(mock) 无厂商数据' }
  },

  async getSeriesProfile(vndbId) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.get_series_profile(vndbId), 60000, '系列档案')
    }
    await delay(800)
    return { ok: false, error: '(mock) 无系列数据' }
  },

  // 厂商墙 / 新作 / 作品详情
  async getMakersWall() {
    if (hasBridge()) return window.pywebview.api.get_makers_wall()
    await delay()
    return { ok: true, makers: [] }
  },

  async refreshNewReleases() {
    if (hasBridge()) return window.pywebview.api.refresh_new_releases()
    return { ok: true, started: true }
  },

  async getNewReleases() {
    if (hasBridge()) return window.pywebview.api.get_new_releases()
    await delay()
    return { ok: true, state: { running: false }, releases: [] }
  },

  async getWorkDetail(vndbId) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.get_work_detail(vndbId), 45000, '作品详情')
    }
    await delay()
    return { ok: false, error: '(mock) 无数据' }
  },

  async translateWorkAsync(vndbId) {
    if (hasBridge()) return window.pywebview.api.translate_work_async(vndbId)
    return { ok: true }
  },

  async translateWorks(works) {
    if (hasBridge()) return window.pywebview.api.translate_works_async(works)
    return { ok: true, translated: 0 }
  },

  async getTranslateStatus() {
    if (hasBridge()) return window.pywebview.api.get_translate_status()
    return { running: false, done: false }
  },

  // 厂商更正 / 标签翻译 / 关注
  async searchProducers(keyword) {
    if (hasBridge()) {
      return withTimeout(window.pywebview.api.search_producers(keyword), 30000, '厂商搜索')
    }
    await delay()
    return { ok: false, candidates: [] }
  },

  async setMakerMapping(makerName, vndbId, displayName) {
    if (hasBridge()) return window.pywebview.api.set_maker_mapping(makerName, vndbId, displayName)
    return { ok: true }
  },

  async translateTags(tags) {
    if (hasBridge()) return window.pywebview.api.translate_tags_async(tags)
    return { ok: true }
  },

  async getTagTranslateStatus() {
    if (hasBridge()) return window.pywebview.api.get_tag_translate_status()
    return { running: false, done: 0, pending: [] }
  },

  async getWorkTranslateStatus() {
    if (hasBridge()) return window.pywebview.api.get_work_translate_status()
    return { running: false, done: 0, pending: {} }
  },

  // 日志
  async logError(message) {
    try {
      if (hasBridge()) return window.pywebview.api.log_error(message)
    } catch (e) { /* 日志失败忽略，防循环 */ }
    return { ok: true }
  },

  async getLogTail(lines = 200) {
    if (hasBridge()) return window.pywebview.api.get_log_tail(lines)
    await delay()
    return { ok: true, log: '' }
  },

  async followMaker(name, vndbId, displayName) {
    if (hasBridge()) return window.pywebview.api.follow_maker(name, vndbId, displayName)
    return { ok: true }
  },

  async unfollowMaker(name) {
    if (hasBridge()) return window.pywebview.api.unfollow_maker(name)
    return { ok: true }
  },

  async listFollows() {
    if (hasBridge()) return window.pywebview.api.list_follows()
    await delay()
    return { ok: true, follows: [] }
  },
}
