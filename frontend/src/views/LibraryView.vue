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
      <p class="empty-sub">Phase 1 接入扫描后，这里会显示你磁盘上的游戏</p>
    </div>

    <div v-else class="grid">
      <GameCard v-for="g in store.filteredGames" :key="g.id" :game="g" />
    </div>
  </div>
</template>

<script setup>
import { useLibraryStore } from '../stores/library.js'
import GameCard from '../components/GameCard.vue'

const store = useLibraryStore()
</script>
