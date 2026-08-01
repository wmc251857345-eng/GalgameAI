<template>
  <div class="library">
    <div class="library-head">
      <h1>游戏库</h1>
      <span class="count">{{ store.filteredGames.length }} / {{ store.summary.total }} 部</span>
    </div>

    <div v-if="store.loading" class="loading">加载中…</div>

    <div v-else-if="store.filteredGames.length === 0" class="empty">
      <div class="empty-icon">▤</div>
      <p>没有找到游戏</p>
      <p class="empty-sub">去「设置」添加游戏库目录并扫描，或调整搜索条件</p>
    </div>

    <div v-else class="grid">
      <GameCard
        v-for="g in store.filteredGames"
        :key="g.id"
        :game="g"
        @open="store.openDetail"
        @launch="launch(g)"
      />
    </div>
  </div>
</template>

<script setup>
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'
import GameCard from '../components/GameCard.vue'

const store = useLibraryStore()

async function launch(g) {
  const r = await api.launchGame(g.id)
  if (r && !r.ok) alert(r.error)
}
</script>
