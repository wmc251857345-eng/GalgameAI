import { defineStore } from 'pinia'
import { api } from '../api.js'

export const useLibraryStore = defineStore('library', {
  state: () => ({
    games: [],
    summary: { total: 0, pending: 0, confirmed: 0, playtime_hours: 0, makers: 0 },
    loading: false,
    search: '',
    sort: (() => { try { return localStorage.getItem('gala_sort') || 'company' } catch { return 'company' } })(),
    sortDir: (() => { try { return localStorage.getItem('gala_sortDir') || 'desc' } catch { return 'desc' } })(),
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
    workDetail: { vndbId: null, work: null, loading: false, error: null, translating: false, translateError: null, refreshError: null },
    workDetailCache: {},   // vndbId → 最近一次完整作品数据（重复打开秒开，不再每次等 VNDB）
    selectedGameId: null,
    detail: null,
    detailError: null,
    detailLoading: false,
    libraryScrollTop: 0,   // 离开游戏库时的滚动位置（详情页返回时恢复，不丢列表位置）
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
      // 排序：全部支持中文拼音（zh-Hans-CN locale），空值一律沉底，主键并列时按标题/日文名兜底
      const zh = (x, y) => String(x || '').localeCompare(String(y || ''), 'zh-Hans-CN')
      const byTitle = (a, b) => zh(a.title, b.title) || zh(a.title_jp, b.title_jp)
      const byCompany = (a, b) => {
        const ma = (a.maker || '').trim()
        const mb = (b.maker || '').trim()
        if (!ma && !mb) return byTitle(a, b)
        if (!ma) return 1
        if (!mb) return -1
        return zh(ma, mb) || zh(a.released || '', b.released || '') || byTitle(a, b)
      }
      const byYear = (a, b) => {
        // 按发售时间：新→旧，无日期的沉底
        const ra = (a.released || '').slice(0, 10) || '0000-00-00'
        const rb = (b.released || '').slice(0, 10) || '0000-00-00'
        return rb.localeCompare(ra) || byTitle(a, b)
      }
      const sort = state.sort
      const dir = state.sortDir === 'asc' ? -1 : 1
      return [...list].sort((a, b) => {
        if (sort === 'company') return dir * byCompany(a, b)
        if (sort === 'year') return dir * byYear(a, b)
        if (sort === 'playtime') return dir * ((b.playtime_hours || 0) - (a.playtime_hours || 0) || byTitle(a, b))
        if (sort === 'score') return dir * ((b.score || 0) - (a.score || 0) || byTitle(a, b))
        if (sort === 'favorite') return dir * ((b.favorite || 0) - (a.favorite || 0) || byTitle(a, b))
        return dir * byTitle(a, b)  // title = 按标题首字/拼音
      })
    },
  },

  actions: {
    // 排序设置（持久化到 localStorage，重启保留）
    setSort(sort, dir) {
      this.sort = sort
      if (dir !== undefined) this.sortDir = dir
      try {
        localStorage.setItem('gala_sort', this.sort)
        localStorage.setItem('gala_sortDir', this.sortDir)
      } catch (e) { /* 无 localStorage 时静默 */ }
    },

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

    // 删除游戏（右键菜单 / 详情页）：清库 + 刷新 + 若正打开详情则返回
    async removeGame(id) {
      try {
        await api.removeGame(id)
      } catch (e) {
        return false
      }
      await Promise.all([this.load(), this.loadPending()])
      if (this.detail && this.detail.id === id) this.back()
      return true
    },

    // 导入外部候选（搜索补全流程）
    async importCandidate(candidate) {
      const r = await api.importGameCandidate(candidate)
      if (r && r.ok) {
        await this.load()
        return r
      }
      return r
    },

    // 手动创建占位条目
    async addManual(fields) {
      const r = await api.addGameManual(fields)
      if (r && r.ok) {
        await this.load()
        return r
      }
      return r
    },

    // 本地导入：exe/文件夹 + 备注 → AI 补全录入
    async importLocal(fields) {
      const r = await api.importLocalGame(fields)
      if (r && r.ok) {
        await this.load()
        return r
      }
      return r
    },

    // 导入后换用备选候选的资料
    async reimportSource(id, candidate) {
      const r = await api.reimportGameSource(id, candidate)
      if (r && r.ok) {
        await this.load()
        if (this.detail && this.detail.id === id) this.refreshDetail()
      }
      return r
    },

    // 快捷改资料（聊天页上下文操作）：改完刷新列表 + 若详情开着刷新详情
    async quickUpdateGame(id, fields) {
      const r = await api.updateGame(id, fields)
      if (r && r.ok) {
        await this.load()
        if (this.detail && this.detail.id === id) this.refreshDetail()
      }
      return r
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
    // 滚动容器是共享的 .content（overflow-y:auto）：离开库后内容变矮，scrollTop 会被浏览器
    // 钳制归零，返回时列表就回到第一行。离开前记录位置、返回后恢复。
    _saveLibraryScroll() {
      try {
        const el = document.querySelector('.content')
        this.libraryScrollTop = el ? el.scrollTop : 0
      } catch (e) {
        this.libraryScrollTop = 0
      }
    },

    _restoreLibraryScroll() {
      try {
        const el = document.querySelector('.content')
        if (!el) return
        const t = this.libraryScrollTop || 0
        requestAnimationFrame(() => { el.scrollTop = t })
      } catch (e) { /* 恢复失败不致命 */ }
    },

    async openDetail(id) {
      if (this.currentView === 'library') this._saveLibraryScroll()
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
      this._restoreLibraryScroll()
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
      try {
        const r = await api.getMakerProfile(maker)
        if (r && r.ok) this.maker.profile = r
        else this.maker.error = (r && r.error) || '加载失败'
      } catch (e) {
        // 桥接异常/超时 → 明确报错，绝不永久转圈（卡死主因之一）
        this.maker.error = e.message || '加载失败（超时或网络异常）'
      } finally {
        this.maker.loading = false
      }
    },

    async loadSeriesProfile(vndbId) {
      this.maker = { mode: 'series', key: vndbId, profile: null, loading: true, error: null }
      try {
        const r = await api.getSeriesProfile(vndbId)
        if (r && r.ok) this.maker.profile = r
        else this.maker.error = (r && r.error) || '加载失败'
      } catch (e) {
        this.maker.error = e.message || '加载失败（超时或网络异常）'
      } finally {
        this.maker.loading = false
      }
    },

    openMaker(maker) {
      if (!maker) return
      // 重入保护：同一厂商正在加载/已打开时不重复发起（防连点堆积桥接线程）
      if (this.maker.key === maker && (this.maker.loading || this.maker.profile)) return
      this.currentView = 'maker'
      this.loadMakerProfile(maker)
    },

    openSeries(vndbId) {
      if (!vndbId) return
      if (this.maker.key === vndbId && (this.maker.loading || this.maker.profile)) return
      this.currentView = 'maker'
      this.loadSeriesProfile(vndbId)
    },

    // ---- 厂商墙 / 新作 / 作品详情 ----
    async loadMakersWall() {
      this.makers.loading = true
      try {
        const r = await api.getMakersWall()
        if (r && r.ok) this.makers.list = r.makers || []
        else this.makers.list = []
      } catch (e) {
        this.makers.list = []   // 失败不卡 loading，墙显示空态
      } finally {
        this.makers.loading = false
      }
    },

    async refreshNewReleases() {
      if (this.newReleases.running) return
      try {
        const r = await api.refreshNewReleases()
        if (r && r.ok) this.pollNewReleases()
      } catch (e) {
        this.newReleases.running = false
      }
    },

    async pollNewReleases() {
      let r = null
      try {
        r = await api.getNewReleases()
      } catch (e) {
        this.newReleases.running = false
        return
      }
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
      try {
        await this.pollNewReleases()
      } catch (e) {
        this.newReleases.loading = false
      }
    },

    // 打开作品弹层：有本地缓存/传入的卡片数据 → 秒开渲染，后台再拉全量详情合并
    async openWorkDetail(vndbId, work) {
      if (!vndbId) return
      const cached = this.workDetailCache[vndbId]
      const hasData = !!(cached || work)
      this.workDetail = { vndbId, work: cached || work || null, loading: !hasData, error: null, translating: false, translateError: null, refreshError: null }
      if (hasData) {
        this.refreshWorkDetail(vndbId)   // 不阻塞，后台增强（简介/中文/厂商等）
        return
      }
      try {
        const r = await api.getWorkDetail(vndbId)
        if (r && r.ok) {
          this.workDetail.work = r.work
          this.workDetailCache[vndbId] = r.work
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

    // 后台拉全量详情并合并到已展示的数据上（秒开体验 + 完整数据兼得）
    async refreshWorkDetail(vndbId) {
      if (!vndbId) return
      try {
        const r = await api.getWorkDetail(vndbId)
        if (r && r.ok) {
          const merged = { ...(this.workDetail.work || {}), ...r.work, id: vndbId }
          this.workDetail.work = merged
          this.workDetailCache[vndbId] = merged
          this.workDetail.refreshError = null
          if (!merged.zh_title && !merged.zh_summary) this.triggerTranslate(vndbId)
        } else {
          // 网络失败但已有秒开数据 → 保留数据 + 轻提示，绝不 blank
          this.workDetail.refreshError = (r && r.error) || '详情刷新失败（使用已有数据）'
        }
      } catch (e) {
        this.workDetail.refreshError = e.message || '详情刷新失败（使用已有数据）'
      }
    },

    // 单作品翻译（厂商卡片按钮）：走批量标题翻译槽位，完成自动刷新当前档案
    async translateWork(work) {
      if (!work || !work.id || this.workTranslating) return
      try {
        const r = await api.translateWorks([
          { id: work.id, title: work.title || '', title_jp: work.title_jp || '' },
        ])
        if (!r || !r.ok) return
      } catch (e) {
        return
      }
      this.workTranslating = true
      const deadline = Date.now() + 180000
      const poll = async () => {
        try {
          const st = await api.getWorkTranslateStatus()
          if (st && st.running && Date.now() < deadline) {
            setTimeout(poll, 2000)
            return
          }
          this.workTranslating = false
          // 翻译完成 → 刷新当前档案，中文标题立即上卡片
          if (this.currentView === 'maker' && this.maker.key) {
            this.loadMakerProfile(this.maker.key)
          }
        } catch (e) {
          this.workTranslating = false
        }
      }
      setTimeout(poll, 1500)
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
      this.workDetail = { vndbId: null, work: null, loading: false, error: null, translating: false, translateError: null, refreshError: null }
    },

    // ---- 关注厂商 / 标签翻译 ----
    async loadFollows() {
      try {
        const r = await api.listFollows()
        if (r && r.ok) this.follows = r.follows || []
      } catch (e) {
        /* 关注列表失败不致命，保持现状 */
      }
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
