import { defineStore } from 'pinia'
import { api } from '../api.js'

export const useLibraryStore = defineStore('library', {
  state: () => ({
    games: [],
    summary: { total: 0, pending: 0, confirmed: 0, playtime_hours: 0, makers: 0 },
    loading: false,
    search: '',
    sort: 'title',
    currentView: 'library', // library | detail | pending | stats | settings
    selectedGameId: null,
    detail: null,
    detailLoading: false,
    pendingGames: [],
    pendingLoading: false,
    roots: [],
    scan: { running: false, stage: 'idle', total: 0, done: 0, current: '', error: null, log: [] },
    runningGames: {},
  }),

  getters: {
    filteredGames(state) {
      const q = state.search.trim().toLowerCase()
      let list = state.games
      if (q) {
        list = list.filter((g) =>
          (g.title || '').toLowerCase().includes(q) ||
          (g.title_en || '').toLowerCase().includes(q) ||
          (g.title_zh || '').toLowerCase().includes(q) ||
          (g.maker || '').toLowerCase().includes(q) ||
          (g.tags || []).join(' ').toLowerCase().includes(q),
        )
      }
      const sort = state.sort
      return [...list].sort((a, b) => {
        if (sort === 'playtime') return (b.playtime_hours || 0) - (a.playtime_hours || 0)
        if (sort === 'score') return (b.score || 0) - (a.score || 0)
        if (sort === 'year') return String(b.released || '').localeCompare(String(a.released || ''))
        return String(a.title || '').localeCompare(String(b.title || ''), 'zh-Hans-CN')
      })
    },
  },

  actions: {
    async load() {
      this.loading = true
      try {
        const [games, summary] = await Promise.all([api.listGames(), api.getLibrarySummary()])
        this.games = games
        this.summary = summary
      } finally {
        this.loading = false
      }
    },

    // ---- 详情 ----
    async openDetail(id) {
      this.selectedGameId = id
      this.currentView = 'detail'
      this.detailLoading = true
      try {
        this.detail = await api.getGame(id)
      } finally {
        this.detailLoading = false
      }
    },

    async refreshDetail() {
      if (!this.selectedGameId) return
      this.detail = await api.getGame(this.selectedGameId)
    },

    back() {
      this.currentView = 'library'
      this.detail = null
      this.selectedGameId = null
    },

    // ---- 待确认 ----
    async loadPending() {
      this.pendingLoading = true
      try {
        this.pendingGames = await api.getPending()
        this.summary.pending = this.pendingGames.length
      } finally {
        this.pendingLoading = false
      }
    },

    async confirmPending(game, cand) {
      const r = await api.confirmMatch(game.id, cand.provider, cand.external_id)
      if (r && r.ok) {
        await Promise.all([this.loadPending(), this.load()])
        this.back()
      } else {
        alert(r?.error || '确认失败')
      }
    },

    async skipPending(game) {
      await api.markUnmatched(game.id)
      await Promise.all([this.loadPending(), this.load()])
    },

    // ---- 扫描 ----
    async startScan() {
      const r = await api.scanLibrary()
      if (r && !r.ok) alert(r.error)
      this.pollScan()
    },

    async startAnalyze() {
      const r = await api.analyzePending()
      if (r && !r.ok) alert(r.error)
      this.pollScan()
    },

    pollScan() {
      // 轮询扫描/分析进度，直到结束
      const tick = async () => {
        this.scan = await api.getScanProgress()
        if (this.scan.running) {
          setTimeout(tick, 800)
        } else {
          if (this.scan.error) alert(`任务出错: ${this.scan.error}`)
          await Promise.all([this.load(), this.loadPending()])
        }
      }
      tick()
    },

    async loadRoots() {
      this.roots = await api.listLibraryRoots()
    },

    async refreshRunning() {
      this.runningGames = await api.getRunning()
    },
  },
})
