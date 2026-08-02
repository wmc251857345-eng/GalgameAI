<template>
  <div class="view-page">
    <div class="library-head">
      <h1>统计</h1>
      <span class="count" v-if="stats">共 {{ stats.overview.total }} 部 · {{ stats.overview.playtime_hours }}h</span>
      <button class="btn small" @click="load" :disabled="loading">⟳ 刷新</button>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="!stats" class="empty">
      <p>统计加载失败</p>
      <button class="btn" @click="load">🔄 重试</button>
    </div>

    <template v-else>
      <!-- 总览卡片 -->
      <div class="stats-grid">
        <div class="stat-card"><div class="stat-num">{{ stats.overview.total }}</div><div class="stat-label">游戏总数</div></div>
        <div class="stat-card"><div class="stat-num">{{ stats.overview.playtime_hours }}</div><div class="stat-label">总游玩 (h)</div></div>
        <div class="stat-card"><div class="stat-num">{{ stats.overview.played_count }}</div><div class="stat-label">玩过的</div></div>
        <div class="stat-card"><div class="stat-num">{{ stats.overview.confirmed }}</div><div class="stat-label">已确认</div></div>
        <div class="stat-card"><div class="stat-num">{{ stats.overview.pending }}</div><div class="stat-label">待确认</div></div>
        <div class="stat-card"><div class="stat-num">{{ stats.overview.favorites }}</div><div class="stat-label">♥ 收藏</div></div>
        <div class="stat-card"><div class="stat-num">{{ stats.overview.hanhua }}</div><div class="stat-label">汉化</div></div>
        <div class="stat-card"><div class="stat-num">{{ stats.overview.total_size_gb }}</div><div class="stat-label">总占用 (GB)</div></div>
      </div>

      <!-- 数据源分布 -->
      <div class="stats-section">
        <h2>数据源分布</h2>
        <div class="source-bar">
          <div
            v-for="(c, src) in stats.sources"
            :key="src"
            class="source-seg"
            :style="{ width: pct(c) + '%', background: sourceColor(src) }"
            :title="sourceLabel(src) + ' ' + c + ' 部'"
          ></div>
        </div>
        <div class="source-legend">
          <span v-for="(c, src) in stats.sources" :key="src" class="source-legend-item">
            <i :style="{ background: sourceColor(src) }"></i>{{ sourceLabel(src) }} {{ c }}
          </span>
        </div>
      </div>

      <div class="stats-cols">
        <!-- 厂商 TOP -->
        <div class="stats-section">
          <h2>厂商 TOP</h2>
          <div v-if="stats.makers.length" class="maker-rank">
            <div v-for="(m, i) in stats.makers" :key="m.name" class="maker-row">
              <span class="mk-rank">{{ i + 1 }}</span>
              <span class="mk-name" :title="m.aliases?.join(' / ')">{{ m.name }}</span>
              <span class="mk-bar-wrap"><span class="mk-bar" :style="{ width: barW(m.count, stats.makers[0].count) + '%' }"></span></span>
              <span class="mk-count">{{ m.count }}</span>
              <span class="mk-sub" v-if="m.avg_rating">★{{ m.avg_rating }}</span>
            </div>
          </div>
          <p v-else class="dim">暂无厂商数据</p>
        </div>

        <!-- 标签云 -->
        <div class="stats-section">
          <h2>标签云</h2>
          <div v-if="stats.tags.length" class="tag-cloud">
            <span
              v-for="t in stats.tags"
              :key="t.name"
              class="cloud-tag"
              :style="{ fontSize: cloudSize(t.count, maxTag) + 'px', opacity: cloudOp(t.count, maxTag) }"
              :title="t.name + ' × ' + t.count"
            >#{{ t.name }}<b class="cloud-c">{{ t.count }}</b></span>
          </div>
          <p v-else class="dim">暂无标签</p>
        </div>
      </div>

      <!-- 年份分布 -->
      <div class="stats-section">
        <h2>发售年份分布</h2>
        <div v-if="stats.years.length" class="year-bar">
          <div v-for="y in stats.years" :key="y.year" class="year-col">
            <span class="year-count">{{ y.count }}</span>
            <span class="year-stick" :style="{ height: barH(y.count, maxYear) + 'px' }"></span>
            <span class="year-label">{{ y.year }}</span>
          </div>
        </div>
        <p v-else class="dim">暂无发售日期数据</p>
      </div>

      <!-- 时长榜 -->
      <div class="stats-section">
        <h2>游玩时长榜</h2>
        <div v-if="stats.top_played.length" class="played-rank">
          <div v-for="(t, i) in stats.top_played" :key="t.id" class="played-row" @click="store.openDetail(t.id)">
            <span class="mk-rank">{{ i + 1 }}</span>
            <span class="mk-name">{{ t.title }}</span>
            <span class="played-hours">{{ t.hours }}h</span>
            <span class="dim" v-if="t.last_played">最近 {{ t.last_played.slice(0, 10) }}</span>
          </div>
        </div>
        <p v-else class="dim">还没有游玩记录，启动游戏就会开始统计</p>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'

const store = useLibraryStore()
const stats = ref(null)
const loading = ref(false)

const maxTag = computed(() => Math.max(1, ...(stats.value?.tags || []).map((t) => t.count)))
const maxYear = computed(() => Math.max(1, ...(stats.value?.years || []).map((y) => y.count)))

function pct(c) {
  const total = Object.values(stats.value.sources || {}).reduce((s, x) => s + x, 0)
  return total ? Math.round((c / total) * 1000) / 10 : 0
}
function barW(c, max) {
  return max ? Math.round((c / max) * 100) : 0
}
function barH(c, max) {
  return max ? Math.round((c / max) * 80) + 8 : 8
}
function cloudSize(c, max) {
  return Math.round(12 + (c / max) * 12)
}
function cloudOp(c, max) {
  return 0.55 + (c / max) * 0.45
}
function sourceLabel(src) {
  return { vndb: 'VNDB', bgm: 'Bangumi', ai: 'AI', manual: '手动', local: '本地' }[src] || src
}
function sourceColor(src) {
  return { vndb: '#66c0f4', bgm: '#f0ab6c', ai: '#a78bfa', manual: '#7dd87d', local: '#888' }[src] || '#888'
}

async function load() {
  loading.value = true
  try {
    stats.value = await api.getStats()
  } catch (e) {
    stats.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
