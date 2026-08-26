<template>
  <div v-if="store.workDetail.vndbId" class="wd-overlay" @click.self="store.closeWorkDetail()">
    <div class="wd-panel">
      <button class="wd-close" title="关闭" @click="store.closeWorkDetail()">✕</button>

      <div v-if="store.workDetail.loading" class="wd-loading">
        <span class="spinner"></span> 加载作品资料…
      </div>

      <div v-else-if="store.workDetail.error" class="wd-loading">
        <p>⚠️ {{ store.workDetail.error }}</p>
        <button class="btn small" @click="store.openWorkDetail(store.workDetail.vndbId)">重试</button>
      </div>

      <template v-else-if="w">
        <p v-if="store.workDetail.refreshError" class="wd-err refresh">
          ⚠ {{ store.workDetail.refreshError }}
          <button class="btn small" @click="store.refreshWorkDetail(store.workDetail.vndbId)">重试</button>
        </p>
        <div class="wd-main">
          <div class="wd-cover-wrap">
            <img
              v-if="w.cover_url"
              :src="w.cover_url"
              class="wd-cover"
              :class="{ hidden: imgFail }"
              @error="imgFail = true"
            />
            <div v-if="!w.cover_url || imgFail" class="wd-cover wd-empty">🖼</div>
          </div>
          <div class="wd-info">
            <h2 class="wd-title">{{ displayTitle }}</h2>
            <div v-if="displayTitle !== w.title" class="wd-sub">{{ w.title }}</div>
            <div v-if="w.title_orig && w.title_orig !== displayTitle" class="wd-sub-jp">{{ w.title_orig }}</div>

            <div class="wd-meta">
              <span v-if="w.released">📅 {{ w.released }}</span>
              <span v-if="w.rating">★ {{ (w.rating / 10).toFixed(1) }}</span>
              <span v-if="lengthText">⏱ {{ lengthText }}</span>
              <span v-if="w.maker">🏢 {{ w.maker }}</span>
            </div>

            <div v-if="(w.tags_zh || w.tags) && (w.tags_zh || w.tags).length" class="wd-tags">
              <span v-for="t in (w.tags_zh || w.tags).slice(0, 8)" :key="t" class="wd-tag">#{{ t }}</span>
            </div>

            <div class="wd-actions">
              <button v-if="w.local_id" class="btn primary" @click="openLocal">🎮 打开本地游戏</button>
              <button class="btn" @click="addWishlist">🎯 加入想玩</button>
              <button v-if="w.vndb_id_series !== undefined" class="btn" @click="openSeries">🧩 系列/前作</button>
              <button v-if="store.workDetail.translating" class="btn" disabled>⏳ 翻译中…</button>
              <button v-else-if="store.workDetail.translateError" class="btn" @click="store.triggerTranslate(w.id)">🔄 重新翻译</button>
            </div>
            <p v-if="wishMsg" class="wd-wish-msg">{{ wishMsg }}</p>
            <p v-if="store.workDetail.translateError" class="wd-err">{{ store.workDetail.translateError }}</p>
          </div>
        </div>

        <div class="wd-desc">
          <h3 class="wd-desc-title">{{ hasZh ? '简介（中文）' : '简介（原文）' }}</h3>
          <p v-if="hasZh">{{ zhSummary }}</p>
          <p v-else-if="w.summary">{{ w.summary }}</p>
          <p v-else class="dim">（无简介）</p>
          <p v-if="!hasZh && store.workDetail.translating" class="wd-translating">⏳ 正在翻译成中文，稍候自动刷新…</p>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useLibraryStore } from '../stores/library.js'

const store = useLibraryStore()
const w = computed(() => store.workDetail.work)
const imgFail = ref(false)

// 打开新作品时重置图片失败标记
watch(() => store.workDetail.vndbId, () => { imgFail.value = false })

const LEN = { 1: '很短', 2: '短', 3: '中等', 4: '长', 5: '很长' }
const lengthText = computed(() => (w.value && LEN[w.value.length_level]) || '')

const hasZh = computed(() => !!(w.value && (w.value.zh_title || w.value.zh_summary)))
const displayTitle = computed(() => {
  if (!w.value) return ''
  return w.value.zh_title || w.value.local_title || w.value.title || ''
})
const zhSummary = computed(() => {
  if (!w.value) return ''
  return w.value.zh_summary || w.value.summary || ''
})

function openLocal() {
  store.closeWorkDetail()
  store.openDetail(w.value.local_id)  // 旧版 openGame 不存在，点击必报错（v1.1 修）
}

// 加入想玩清单（v1.1）：作品名 + vndb id 一键记录
const wishMsg = ref('')
async function addWishlist() {
  if (!w.value) return
  try {
    const r = await store.wishlistAdd(displayTitle.value || w.value.title || '', '', w.value.id || '')
    wishMsg.value = r && r.ok ? '✓ 已加入想玩清单' : (r && r.error) || '加入失败'
    if (r && r.ok) store.loadWishlist()
  } catch (e) {
    wishMsg.value = e.message || '加入失败'
  }
  setTimeout(() => { wishMsg.value = '' }, 4000)
}

function openSeries() {
  store.closeWorkDetail()
  store.openSeries(w.value.id)
}
</script>
