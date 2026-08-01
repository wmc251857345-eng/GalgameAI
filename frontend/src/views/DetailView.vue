<template>
  <div class="view-page detail">
    <button class="btn back-btn" @click="store.back()">← 返回游戏库</button>

    <div v-if="store.detailLoading" class="loading">加载中…</div>

    <template v-else-if="g">
      <!-- 头部横幅区 -->
      <div class="detail-hero">
        <div class="hero-cover" :style="{ '--hue': 220 }">
          <img v-if="g.cover_url" :src="g.cover_url" alt="" />
          <div v-else class="cover-grad"></div>
        </div>
        <div class="hero-info">
          <div class="hero-title">{{ g.title }}</div>
          <div class="hero-tags">
            <span v-if="g.status === 2" class="status-badge ok">✓ 已入库</span>
            <span v-else-if="g.status === 1" class="status-badge warn">? 待确认</span>
            <span v-else-if="g.status === 3" class="status-badge skip">已跳过</span>
            <span v-if="g.hanhua" class="status-badge hanhua">汉化</span>
            <span v-if="g.running" class="status-badge running">▶ 运行中</span>
          </div>
          <table class="info-table">
            <tr><td>制作</td><td>{{ g.maker || '—' }}</td></tr>
            <tr><td>发售</td><td>{{ g.released || '—' }}</td></tr>
            <tr><td>评分</td><td>{{ g.rating != null ? '★ ' + g.rating : '—' }}</td></tr>
            <tr><td>时长</td><td>{{ lengthText }}</td></tr>
            <tr><td>游玩</td><td>{{ g.playtime_hours }}h<template v-if="g.last_played"> · 最近 {{ g.last_played }}</template></td></tr>
            <tr><td>本地路径</td><td class="path-cell">{{ g.path }}</td></tr>
            <tr v-if="g.exe_path"><td>启动 exe</td><td class="path-cell">{{ g.exe_path }}</td></tr>
            <tr><td>数据源</td><td>{{ sourceText }}</td></tr>
          </table>
          <div class="hero-actions">
            <button v-if="!g.running" class="btn primary" @click="launch">▶ 启动游戏</button>
            <button v-else class="btn danger" @click="stop">■ 停止</button>
            <button class="btn" @click="reanalyze">⟳ 重新 AI 分析</button>
            <label class="le-toggle">
              <input v-model="useLe" type="checkbox" @change="toggleLe" />
              Locale Emulator
            </label>
          </div>
        </div>
      </div>

      <!-- 标签 + 简介 -->
      <div class="detail-section">
        <h2>标签</h2>
        <div class="tag-list">
          <span v-for="t in g.tags" :key="t" class="tag-chip">#{{ t }}</span>
          <span v-if="!g.tags?.length" class="dim">暂无标签（重新分析生成）</span>
        </div>
      </div>

      <div class="detail-section">
        <h2>简介</h2>
        <p class="desc">{{ g.description || '暂无简介' }}</p>
        <details v-if="g.text_sample" class="local-info">
          <summary>本地文件信息（readme 等）</summary>
          <pre class="text-sample">{{ g.text_sample }}</pre>
        </details>
      </div>

      <!-- 待确认候选 -->
      <div v-if="g.status === 1" class="detail-section">
        <h2>AI 匹配候选（置信度不足，请选择）</h2>
        <div class="cand-row">
          <div v-for="c in g.candidates" :key="c.provider + c.external_id" class="cand-card" :class="'conf-' + confClass(c.score)">
            <img v-if="c.cover_url" :src="c.cover_url" class="cand-img" alt="" />
            <div v-else class="cand-img cand-img-empty"></div>
            <div class="cand-title">{{ c.title }}{{ c.title_orig && c.title_orig !== c.title ? ' / ' + c.title_orig : '' }}</div>
            <div class="cand-meta">{{ c.maker || '' }} {{ c.released || '' }} · {{ c.provider.toUpperCase() }}</div>
            <div class="cand-score">{{ Math.round(c.score * 100) }}%</div>
            <button class="btn primary small" @click="confirm(c)">确认</button>
          </div>
          <div v-if="!g.candidates?.length" class="dim">没有候选，可跳过或重新分析</div>
        </div>
        <button class="btn" @click="skip">跳过（不匹配任何条目）</button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'

const store = useLibraryStore()
const g = computed(() => store.detail)
const useLe = ref(false)

const lengthText = computed(() => {
  if (!g.value) return ''
  if (g.value.length_minutes) return `约 ${Math.round(g.value.length_minutes / 60)} 小时`
  const lv = g.value.length_level
  return { 1: '很短', 2: '短', 3: '中等', 4: '长', 5: '很长' }[lv] || '—'
})
const sourceText = computed(() => {
  const s = g.value?.source
  return { bgm: 'Bangumi', vndb: 'VNDB', ai: 'AI', manual: '手动' }[s] || '本地扫描'
})

function confClass(score) {
  return score >= 0.8 ? 'high' : score >= 0.6 ? 'mid' : 'low'
}

async function launch() {
  const r = await api.launchGame(g.value.id)
  if (r && !r.ok) alert(r.error)
  else store.refreshRunning()
}
async function stop() {
  await api.stopGame(g.value.id)
  store.refreshRunning()
  store.refreshDetail()
}
async function reanalyze() {
  const r = await api.reanalyzeGame(g.value.id)
  if (r && !r.ok) alert(r.error)
  store.refreshDetail()
  store.load()
}
async function confirm(c) {
  const r = await api.confirmMatch(g.value.id, c.provider, c.external_id)
  if (r && !r.ok) alert(r.error)
  store.refreshDetail()
  store.load()
}
async function skip() {
  await api.markUnmatched(g.value.id)
  store.back()
  store.load()
}
async function toggleLe() {
  await api.setLocaleEmu(g.value.id, useLe.value)
}
</script>
