<template>
  <div class="library">
    <div class="library-head">
      <h1>游戏库</h1>
      <span class="count">{{ store.filteredGames.length }} / {{ store.summary.total }} 部</span>
      <div class="head-actions">
        <button class="btn small" @click="randomGame">🎲 随机</button>
        <div class="view-toggle">
          <button class="vt-btn" :class="{ active: store.viewMode === 'grid' }" @click="store.viewMode = 'grid'">▦ 网格</button>
          <button class="vt-btn" :class="{ active: store.viewMode === 'list' }" @click="store.viewMode = 'list'">☰ 列表</button>
        </div>
      </div>
    </div>

    <!-- 状态 Tabs -->
    <div class="tabs">
      <button
        v-for="t in tabs"
        :key="t.id"
        class="tab"
        :class="{ active: store.filterStatus === t.id }"
        @click="store.filterStatus = t.id"
      >
        {{ t.label }}<span v-if="t.count != null" class="tab-count">{{ t.count }}</span>
      </button>
    </div>

    <!-- 筛选行 -->
    <div class="filters">
      <div class="tag-chips">
        <span class="chip" :class="{ active: !store.filterTag }" @click="store.filterTag = ''">全部标签</span>
        <span
          v-for="t in store.facets.tags.slice(0, 14)"
          :key="t.name"
          class="chip"
          :class="{ active: store.filterTag === t.name }"
          @click="toggleTag(t.name)"
        >#{{ t.name }} <b class="chip-c">{{ t.c }}</b></span>
      </div>
      <select v-model="store.filterMaker" class="sort">
        <option value="">全部厂商</option>
        <option v-for="m in store.facets.makers" :key="m.maker" :value="m.maker">{{ m.maker }} ({{ m.c }})</option>
      </select>
      <select v-model="store.filterYear" class="sort">
        <option value="">全部年份</option>
        <option v-for="y in store.facets.years" :key="y.y" :value="y.y">{{ y.y }} ({{ y.c }})</option>
      </select>
    </div>

    <div v-if="store.loading" class="loading">加载中…</div>

    <div v-else-if="store.filteredGames.length === 0" class="empty">
      <div class="empty-icon">▤</div>
      <p>没有找到游戏</p>
      <p class="empty-sub">去「设置」添加游戏库目录并扫描，或调整筛选条件</p>
    </div>

    <!-- 网格视图 -->
    <div v-else-if="store.viewMode === 'grid'" class="grid">
      <GameCard
        v-for="g in store.filteredGames"
        :key="g.id"
        :game="g"
        @open="store.openDetail"
        @fav="store.toggleFavorite"
        @launch="launch(g)"
      />
    </div>

    <!-- 列表视图 -->
    <div v-else class="list-view">
      <div v-for="g in store.filteredGames" :key="g.id" class="list-row" @click="store.openDetail(g.id)">
        <span class="list-fav" :class="{ on: g.favorite }" @click.stop="store.toggleFavorite(g)">♥</span>
        <img v-if="g.cover_url" :src="g.cover_url" class="list-cover" alt="" />
        <div v-else class="list-cover list-cover-empty"></div>
        <div class="list-main">
          <div class="list-title">{{ g.title }}</div>
          <div class="list-sub">{{ g.title_jp || g.title_en || '—' }}</div>
        </div>
        <div class="list-cell list-maker">{{ g.maker || '—' }}</div>
        <div class="list-cell list-year">{{ (g.released || '').slice(0, 4) || '—' }}</div>
        <div class="list-cell list-score">{{ g.score != null ? '★ ' + g.score : '—' }}</div>
        <div class="list-cell list-time">{{ g.playtime_hours }}h</div>
        <div class="list-badges">
          <span v-if="g.status === 2" class="status-badge ok">✓ 已入库</span>
          <span v-else-if="g.status === 1" class="status-badge warn">待确认</span>
          <span v-else-if="g.status === 3" class="status-badge skip">已跳过</span>
          <span v-if="g.hanhua" class="status-badge hanhua">汉化</span>
          <span v-if="g.exe_path && !g.exe_exists" class="status-badge skip" title="exe 不存在">!路径失效</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'
import GameCard from '../components/GameCard.vue'

const store = useLibraryStore()

const tabs = computed(() => [
  { id: 'all', label: '全部', count: store.summary.total },
  { id: 2, label: '已入库', count: store.summary.confirmed },
  { id: 1, label: '待确认', count: store.summary.pending },
  { id: 'fav', label: '♥ 收藏' },
  { id: 3, label: '已跳过' },
])

function toggleTag(name) {
  store.filterTag = store.filterTag === name ? '' : name
}

function randomGame() {
  const g = store.randomGame()
  if (g) store.openDetail(g.id)
}

async function launch(g) {
  const r = await api.launchGame(g.id)
  if (r && !r.ok) alert(r.error)
}
</script>
