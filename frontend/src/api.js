// 前后端桥：pywebview 环境调用真实后端；浏览器开发环境自动降级为 mock。
const hasBridge = () =>
  typeof window !== 'undefined' && window.pywebview && window.pywebview.api

const delay = (ms = 200) => new Promise((r) => setTimeout(r, ms))

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

  async listGames() {
    if (hasBridge()) return window.pywebview.api.list_games(1000, 0, 'title', '')
    await delay(300)
    return MOCK_GAMES
  },

  async getGame(id) {
    if (hasBridge()) return window.pywebview.api.get_game(id)
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
    if (hasBridge()) return window.pywebview.api.confirm_match(gameId, provider, externalId)
    await delay()
    return { ok: true }
  },

  async markUnmatched(gameId) {
    if (hasBridge()) return window.pywebview.api.mark_unmatched(gameId)
    return { ok: true }
  },

  async reanalyzeGame(gameId) {
    if (hasBridge()) return window.pywebview.api.reanalyze_game(gameId)
    await delay(600)
    return { ok: true }
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
}
