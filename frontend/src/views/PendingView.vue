<template>
  <div class="view-page">
    <div class="library-head">
      <h1>待确认</h1>
      <span class="count">AI 匹配置信度不足的游戏，由你拍板</span>
      <div class="head-actions">
        <button class="btn" :disabled="store.scan.running" @click="store.startAnalyze()">
          ⟳ 批量自动分析
        </button>
      </div>
    </div>

    <div v-if="store.scan.running" class="progress-card">
      <div class="progress-bar"><div class="progress-fill" :style="{ width: progressPct + '%' }"></div></div>
      <div class="progress-text">{{ stageLabel }}：{{ store.scan.current }}（{{ store.scan.done }}/{{ store.scan.total }}）</div>
      <div class="progress-log"><div v-for="(l, i) in store.scan.log.slice(-6)" :key="i">{{ l }}</div></div>
    </div>

    <div v-if="store.pendingLoading" class="loading">加载中…</div>

    <div v-else-if="store.pendingGames.length === 0 && !store.scan.running" class="empty">
      <div class="empty-icon">◷</div>
      <p>没有待确认的游戏</p>
      <p class="empty-sub">扫描后无法自动识别的游戏会出现在这里</p>
    </div>

    <div v-else class="pending-list">
      <div v-for="p in store.pendingGames" :key="p.id" class="pending-card">
        <div class="pending-head">
          <span class="pending-folder">📁 {{ p.title }}</span>
          <span class="pending-path">{{ p.path }}</span>
        </div>
        <div class="cand-row">
          <div
            v-for="c in p.candidates"
            :key="c.provider + c.external_id"
            class="cand-card"
            :class="'conf-' + confClass(c.score)"
          >
            <img v-if="c.cover_url" :src="c.cover_url" class="cand-img" alt="" />
            <div v-else class="cand-img cand-img-empty"></div>
            <div class="cand-title">{{ c.title }}{{ c.title_orig && c.title_orig !== c.title ? ' / ' + c.title_orig : '' }}</div>
            <div class="cand-meta">{{ c.maker || '' }} {{ c.released || '' }} · {{ c.provider.toUpperCase() }}</div>
            <div class="cand-score">{{ Math.round(c.score * 100) }}%</div>
            <button class="btn primary small" @click="store.confirmPending(p, c)">确认</button>
          </div>
          <div v-if="!p.candidates?.length" class="dim">无候选</div>
        </div>
        <div class="pending-actions">
          <button class="btn small" @click="store.skipPending(p)">跳过</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLibraryStore } from '../stores/library.js'

const store = useLibraryStore()

const progressPct = computed(() => {
  const { total, done } = store.scan
  return total ? Math.round((done / total) * 100) : 0
})

const stageLabel = computed(
  () => ({ scan: '扫描', analyze: 'AI分析', covers: '补封面' }[store.scan.stage] || store.scan.stage),
)

function confClass(score) {
  return score >= 0.8 ? 'high' : score >= 0.6 ? 'mid' : 'low'
}
</script>
