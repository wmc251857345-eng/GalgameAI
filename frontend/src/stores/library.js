import { defineStore } from 'pinia'
import { api } from '../api.js'

export const useLibraryStore = defineStore('library', {
  state: () => ({
    games: [],
    summary: { total: 0, pending: 0, confirmed: 0, playtime_hours: 0, makers: 0 },
    loading: false,
    search: '',
    sort: 'title',
    currentView: 'library', // library | pending | stats | settings
  }),

  getters: {
    filteredGames(state) {
      const q = state.search.trim().toLowerCase()
      let list = state.games
      if (q) {
        list = list.filter((g) =>
          (g.title || '').toLowerCase().includes(q) ||
          (g.title_en || '').toLowerCase().includes(q) ||
          (g.maker || '').toLowerCase().includes(q) ||
          (g.tags || []).join(' ').toLowerCase().includes(q),
        )
      }
      const sort = state.sort
      return [...list].sort((a, b) => {
        if (sort === 'playtime') return (b.playtime_hours || 0) - (a.playtime_hours || 0)
        if (sort === 'score') return (b.score || 0) - (a.score || 0)
        if (sort === 'year') return String(b.year || '').localeCompare(String(a.year || ''))
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
  },
})
