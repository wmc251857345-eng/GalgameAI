<template>
  <div class="view-page">
    <div class="library-head">
      <h1 v-if="store.maker.mode === 'maker'">{{ store.maker.key }}</h1>
      <h1 v-else>🧩 {{ profileTitle }}</h1>
      <span class="count">{{ headerNote }}</span>
      <div class="head-actions">
        <button class="btn small" :disabled="!prevMaker" @click="goMaker(prevMaker)" title="上一个厂商">‹ 上一个</button>
        <button class="btn small" :disabled="!nextMaker" @click="goMaker(nextMaker)" title="下一个厂商">下一个 ›</button>
        <button class="btn small" @click="store.currentView = 'makers'">🏭 厂商墙</button>
      </div>
    </div>

    <div v-if="store.maker.loading" class="scan-banner">
      <span class="spinner"></span> 正在从 VNDB 拉取资料…
    </div>

    <div v-else-if="store.maker.error" class="maker-error">
      <p>⚠️ {{ store.maker.error }}</p>
      <button class="btn small" @click="retry">重试</button>
    </div>

    <template v-else-if="store.maker.profile">
      <!-- 厂商简介 -->
      <div v-if="store.maker.mode === 'maker' && profile.producer" class="maker-intro">
        <div class="maker-badges">
          <span class="mk-badge">{{ typeLabel(profile.producer.type) }}</span>
          <span class="mk-badge">{{ profile.producer.id }}</span>
        </div>
        <p v-if="profile.producer.description" class="maker-desc">{{ profile.producer.description }}</p>
        <p v-else class="maker-desc dim">（VNDB 暂无简介）</p>
      </div>

      <!-- 作品网格 -->
      <div class="mk-works-head">
        <span>全部作品（{{ profile.total_count }}）</span>
        <span class="mk-owned">已拥有 <b>{{ profile.owned_count }}</b></span>
      </div>
      <div v-if="profile.works && profile.works.length" class="mk-grid">
        <div
          v-for="w in profile.works"
          :key="w.id"
          class="mk-card"
          :class="{ owned: w.owned }"
          @click="openWork(w)"
        >
          <div class="mk-cover-wrap">
            <img v-if="w.cover_url" :src="w.cover_url" class="mk-cover" loading="lazy" />
            <div v-else class="mk-cover mk-cover-empty">🖼</div>
            <span v-if="w.owned" class="mk-owned-badge" title="本地库已拥有">✓ 已有</span>
            <span v-else class="mk-notowned-badge">未拥有</span>
          </div>
          <div class="mk-info">
            <div class="mk-title" :title="w.title">{{ w.title }}</div>
            <div class="mk-meta">
              <span>{{ w.released || '未知日期' }}</span>
              <span v-if="w.rating">★ {{ (w.rating / 10).toFixed(1) }}</span>
              <span>{{ lengthLabel(w.length_level) }}</span>
            </div>
            <div v-if="familyRels(w).length" class="mk-series-chips">
              <span
                v-for="(r, i) in familyRels(w).slice(0, 2)"
                :key="i"
                class="mk-series-chip"
                :title="'查看『' + r.title + '』的系列/前作'"
                @click.stop="store.openSeries(r.id)"
              >
                🔗 {{ r.title }}
              </span>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="dim" style="padding: 20px 0">暂无作品数据</div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLibraryStore } from '../stores/library.js'

const store = useLibraryStore()
const profile = computed(() => store.maker.profile)

const LEN = { 1: '很短', 2: '短', 3: '中等', 4: '长', 5: '很长' }
const FAMILY = new Set(['ser', 'seq', 'preq', 'side', 'fan', 'alt', 'par', 'set', 'orig'])
const REL_LABEL = {
  ser: '同系列', seq: '续作', preq: '前作', side: '外传', fan: '粉丝盘',
  alt: '换版', par: '平行', set: '同设定', orig: '原作',
}

const profileTitle = computed(() => {
  const p = profile.value
  if (!p) return ''
  if (store.maker.mode === 'maker') return p.producer?.name || ''
  return p.series?.name || ''
})

const headerNote = computed(() => {
  const p = profile.value
  if (!p) return ''
  if (store.maker.mode === 'maker') return `厂商资料 · 全部 ${p.total_count} 部作品`
  return `系列/前作全家桶 · ${p.total_count} 部`
})

function typeLabel(t) {
  return { co: '公司', ing: '个人', ng: '同人组织' }[t] || t || '厂商'
}

function lengthLabel(l) {
  return LEN[l] || ''
}

function familyRels(w) {
  return (w.relations || []).filter((r) => FAMILY.has(r.relation))
}

function openWork(w) {
  if (w.local_id) {
    store.openGame(w.local_id)
  } else if (w.id) {
    store.openWorkDetail(w.id)
  }
}

// 厂商墙导航（按墙内顺序找上/下一个）
const makerIndex = computed(() => {
  const key = store.maker.key
  return store.makers.list.findIndex((m) => m.maker === key)
})
const prevMaker = computed(() => {
  const i = makerIndex.value
  return i > 0 ? store.makers.list[i - 1].maker : null
})
const nextMaker = computed(() => {
  const i = makerIndex.value
  return i >= 0 && i < store.makers.list.length - 1 ? store.makers.list[i + 1].maker : null
})
function goMaker(name) {
  if (name) store.openMaker(name)
}

function retry() {
  if (store.maker.mode === 'maker') store.loadMakerProfile(store.maker.key)
  else store.loadSeriesProfile(store.maker.key)
}
</script>
