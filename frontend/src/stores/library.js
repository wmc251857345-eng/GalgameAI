import { defineStore } from 'pinia'
import { api } from '../api.js'

export const useLibraryStore = defineStore('library', {
  state: () => ({
    games: [],
    summary: { total: 0, pending: 0, confirmed: 0, playtime_hours: 0, makers: 0 },
    loading: false,
    search: '',
    sort: 'title',
    filterStatus: 'all',   // all | 2(已入库) | 1(待确认) | 3(已跳过) | fav(收藏)
    filterTag: '',
    filterMaker: '',
    filterYear: '',
    viewMode: 'grid',      // grid | list
    facets: { tags: [], makers: [], years: [] },
    missingPaths: [],
    chat: { messages: [], sending: false, contextGame: null },
    currentView: 'library', // library | detail | pending | stats | settings | chat | maker | makers
    maker: { mode: 'maker', key: null, profile: null, loading: false, error: null },
    makers: { list: [], loading: false },
    follows: [],
    tagTranslating: false,
    workTranslating: false,
    newReleases: { items: [], loading: false, running: false, done: 0, total: 0, stage: '' },
    workDetail: { vndbId: null, work: null, loading: false, error: null, translating: false, translateError: null },
    selectedGameId: null,
    detail: null,
    detailError: null,
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
      if (state.filterStatus === 'fav') list = list.filter((g) => g.favorite)
      else if (state.filterStatus !== 'all') list = list.filter((g) => g.status === state.filterStatus)
      if (state.filterTag) list = list.filter((g) => (g.tags || []).includes(state.filterTag))
      if (state.filterMaker) list = list.filter((g) => g.maker === state.filterMaker)
      if (state.filterYear) list = list.filter((g) => String(g.released || '').startsWith(state.filterYear))
      const sort = state.sort
      return [...list].sort((a, b) => {
        if (sort === 'playtime') return (b.playtime_hours || 0) - (a.playtime_hours || 0)
        if (sort === 'score') return (b.score || 0) - (a.score || 0)
        if (sort === 'year') return String(b.released || '').localeCompare(String(a.released || ''))
        if (sort === 'favorite') {
          return ((b.favorite || 0) - (a.favorite || 0)) ||
            String(a.title || '').localeCompare(String(b.title || ''), 'zh-Hans-CN')
        }
        return String(a.title || '').localeCompare(String(b.title || ''), 'zh-Hans-CN')
      })
    },
  },

  actions: {
    async load() {
      this.loading = true
      try {
        const [games, summary, facets] = await Promise.all([
          api.listGames(), api.getLibrarySummary(), api.getLibraryFacets(),
        ])
        this.games = games
        this.summary = summary
        this.facets = facets
      } finally {
        this.loading = false
      }
    },

    async toggleFavorite(g) {
      const r = await api.toggleFavorite(g.id)
      if (r && r.ok) {
        g.favorite = r.favorite
        if (this.detail && this.detail.id === g.id) this.detail.favorite = r.favorite
      }
    },

    randomGame() {
      const list = this.filteredGames
      if (!list.length) return null
      return list[Math.floor(Math.random() * list.length)]
    },

    async loadMissing() {
      this.missingPaths = await api.getMissingPaths()
    },

    async relocateGame(id) {
      const r = await api.relocateGame(id)
      if (r && r.ok) {
        await Promise.all([this.load(), this.loadMissing()])
        if (this.detail && this.detail.id === id) this.refreshDetail()
        return true
      }
      alert(r?.error || '重定位失败')
      return false
    },

    // ---- 详情 ----
    async openDetail(id) {
      this.selectedGameId = id
      this.currentView = 'detail'
      this.detailLoading = true
      this.detailError = null
      try {
        this.detail = await api.getGame(id)
        if (!this.detail) {
          this.detailError = '游戏数据不存在（可能已被删除）'
        }
      } catch (e) {
        // 超时/异常 → 显示错误+返回，绝不永久空白/转圈
        this.detailError = e.message || '加载失败（超时或网络异常）'
        this.detail = null
      } finally {
        this.detailLoading = false
      }
    },

    async refreshDetail() {
      if (!this.selectedGameId) return
      try {
        this.detail = await api.getGame(this.selectedGameId)
        this.detailError = null
      } catch (e) {
        this.detailError = e.message || '刷新失败'
      }
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

    async cancelTask() {
      await api.cancelTask()
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

    // ---- AI 管家 ----
    async chatLoad() {
      this.chat.messages = await api.chatHistory()
    },

    async chatSend(text) {
      if (!text.trim() || this.chat.sending) return
      this.chat.sending = true
      this.chat.messages.push({ role: 'user', content: text, created_at: new Date().toISOString() })
      try {
        const r = await api.chatSend(text, this.chat.contextGame?.id)
        this.chat.messages.push({
          role: 'assistant',
          content: r?.ok ? r.reply : (r?.error || '发送失败'),
          actions: (r && r.actions) || [],
          created_at: new Date().toISOString(),
        })
      } catch (e) {
        this.chat.messages.push({ role: 'assistant', content: e.message || '请求失败', actions: [] })
      } finally {
        this.chat.sending = false
      }
    },

    async chatClear() {
      await api.chatClear()
      this.chat.messages = []
    },

    setChatContext(g) {
      this.chat.contextGame = g || null
    },

    // ---- 厂商 / 系列追踪 ----
    async loadMakerProfile(maker) {
      this.maker = { mode: 'maker', key: maker, profile: null, loading: true, error: null }
      const r = await api.getMakerProfile(maker)
      this.maker.loading = false
      if (r && r.ok) this.maker.profile = r
      else this.maker.error = (r && r.error) || '加载失败'
    },

    async loadSeriesProfile(vndbId) {
      this.maker = { mode: 'series', key: vndbId, profile: null, loading: true, error: null }
      const r = await api.getSeriesProfile(vndbId)
      this.maker.loading = false
      if (r && r.ok) this.maker.profile = r
      else this.maker.error = (r && r.error) || '加载失败'
    },

    openMaker(maker) {
      this.currentView = 'maker'
      this.loadMakerProfile(maker)
    },

    openSeries(vndbId) {
      this.currentView = 'maker'
      this.loadSeriesProfile(vndbId)
    },

    // ---- 厂商墙 / 新作 / 作品详情 ----
    async loadMakersWall() {
      this.makers.loading = true
      const r = await api.getMakersWall()
      this.makers.loading = false
      if (r && r.ok) this.makers.list = r.makers || []
    },

    async refreshNewReleases() {
      if (this.newReleases.running) return
      const r = await api.refreshNewReleases()
      if (r && r.ok) this.pollNewReleases()
    },

    async pollNewReleases() {
      const r = await api.getNewReleases()
      if (!r || !r.ok) return
      const st = r.state || {}
      this.newReleases.running = !!st.running
      this.newReleases.done = st.done || 0
      this.newReleases.total = st.total || 0
      this.newReleases.stage = st.stage || ''
      this.newReleases.items = r.releases || this.newReleases.items
      this.newReleases.loading = false
      if (st.running) {
        setTimeout(() => this.pollNewReleases(), 1500)
      }
    },

    async loadNewReleases() {
      this.newReleases.loading = true
      await this.pollNewReleases()
    },

    async openWorkDetail(vndbId) {
      if (!vndbId) return
      this.workDetail = { vndbId, work: null, loading: true, error: null, translating: false, translateError: null }
      try {
        const r = await api.getWorkDetail(vndbId)
        if (r && r.ok) {
          this.workDetail.work = r.work
          this.workDetail.loading = false
          // 无中文 → 自动触发翻译
          if (!r.work.zh_title && !r.work.zh_summary) {
            this.triggerTranslate(vndbId)
          }
        } else {
          this.workDetail.error = (r && r.error) || '加载失败'
          this.workDetail.loading = false
        }
      } catch (e) {
        // 超时/异常 → 显示错误+重试，绝不永久转圈
        this.workDetail.error = e.message || '加载失败（超时或网络异常）'
        this.workDetail.loading = false
      }
    },

    async triggerTranslate(vndbId) {
      if (this.workDetail.translating) return
      this.workDetail.translating = true
      this.workDetail.translateError = null
      await api.translateWorkAsync(vndbId)
      const deadline = Date.now() + 120000
      const poll = async () => {
        const st = await api.getTranslateStatus()
        if (st && st.done) {
          this.workDetail.translating = false
          if (st.error) {
            this.workDetail.translateError = st.error
          } else {
            const r = await api.getWorkDetail(vndbId)
            if (r && r.ok) this.workDetail.work = r.work
          }
          return
        }
        if (Date.now() < deadline) setTimeout(poll, 2000)
        else {
          this.workDetail.translating = false
          this.workDetail.translateError = '翻译超时，可稍后重试'
        }
      }
      setTimeout(poll, 1500)
    },

    closeWorkDetail() {
      this.workDetail = { vndbId: null, work: null, loading: false, error: null, translating: false, translateError: null }
    },

    // ---- 关注厂商 / 标签翻译 ----
    async loadFollows() {
      const r = await api.listFollows()
      if (r && r.ok) this.follows = r.follows || []
    },

    isFollowed(name) {
      return this.follows.some((f) => f.maker_name === name)
    },

    async toggleFollow(name, vndbId, displayName) {
      if (this.isFollowed(name)) {
        await api.unfollowMaker(name)
        this.follows = this.follows.filter((f) => f.maker_name !== name)
        return false
      }
      await api.followMaker(name, vndbId, displayName)
      await this.loadFollows()
      return true
    },

    // 标签翻译完成后刷新中文标签显示
    async pollTagTranslate() {
      const st = await api.getTagTranslateStatus()
      this.tagTranslating = !!st.running
      if (st.running) {
        setTimeout(() => this.pollTagTranslate(), 2500)
      }
    },

    async ensureTagTranslate(tags) {
      const r = await api.translateTags(tags)
      if (r && r.ok) this.pollTagTranslate()
    },

    async pollWorkTranslate() {
      const st = await api.getWorkTranslateStatus()
      this.workTranslating = !!st.running
      if (st.running) {
        setTimeout(() => this.pollWorkTranslate(), 2500)
      }
    },
  },
})
