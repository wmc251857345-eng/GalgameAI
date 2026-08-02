<template>
  <div class="view-page">
    <div class="library-head">
      <h1>🏭 厂商墙</h1>
      <span class="count">{{ store.makers.list.length }} 家厂商 · 点击查看全部作品与新作</span>
      <div class="head-actions">
        <button class="btn small" :disabled="store.newReleases.running" @click="refresh">
          {{ store.newReleases.running ? '抓取中 ' + store.newReleases.done + '/' + store.newReleases.total : '🔄 抓取新作' }}
        </button>
      </div>
    </div>

    <!-- 新作推荐区 -->
    <div class="new-releases">
      <div class="nr-head">
        <span>🔥 新作推荐<span class="nr-sub">（你关注/拥有的厂商，近两年）</span></span>
        <span v-if="store.newReleases.running" class="nr-stage">抓取中 {{ store.newReleases.done }}/{{ store.newReleases.total }} · {{ store.newReleases.stage }}</span>
        <span v-else-if="store.workTranslating" class="nr-stage">标题翻译中…</span>
      </div>
      <div class="nr-strip">
        <div
          v-for="w in store.newReleases.items"
          :key="w.id"
          class="nr-card"
          @click="store.openWorkDetail(w.id, w)"
        >
          <div class="nr-cover-wrap">
            <img v-if="w.cover_url" :src="w.cover_url" class="nr-cover" loading="lazy" v-imgfb="'🖼'" />
            <div v-else class="nr-cover nr-empty">🖼</div>
            <span v-if="w.owned" class="nr-owned" title="本地库已有">✓</span>
            <span v-else class="nr-new" title="新作！">NEW</span>
          </div>
          <div class="nr-title" :title="w.local_title || w.zh_title || w.title">{{ w.local_title || w.zh_title || w.title }}</div>
          <div class="nr-meta"><span v-if="w.maker">{{ w.maker }}</span><span>{{ w.released || '' }}</span><span v-if="w.rating">★ {{ (w.rating / 10).toFixed(1) }}</span></div>
        </div>
      </div>
    </div>

    <!-- 厂商卡片墙 -->
    <div class="wall-search">
      <input v-model="q" class="wall-input" placeholder="🔍 搜索厂商…" />
    </div>
    <div v-if="store.makers.loading" class="scan-banner"><span class="spinner"></span> 加载厂商…</div>
    <div v-else-if="!filtered.length" class="dim" style="padding: 30px 0; text-align: center">
      暂无厂商（游戏库里还没有识别出厂商的游戏）
    </div>
    <div v-else class="wall-grid">
      <div v-for="m in filtered" :key="m.maker" class="wall-card" @click="enterMaker(m)">
        <span v-if="store.isFollowed(m.maker)" class="wall-follow" title="已关注">★</span>
        <span v-if="newCount(m.maker)" class="wall-new" :title="'近两年新作 ' + newCount(m.maker) + ' 部'">{{ newCount(m.maker) }}</span>
        <div class="wall-covers">
          <template v-if="m.covers.length">
            <img
              v-for="(c, i) in m.covers.slice(0, 3)"
              :key="i"
              :src="c"
              class="wall-cover"
              :style="{ zIndex: 3 - i, transform: `translateX(${i * 8}px) rotate(${(i - 1) * 3}deg)` }"
              loading="lazy"
              v-imgfb="'🏢'"
            />
          </template>
          <div v-else class="wall-cover wall-empty">🏢</div>
        </div>
        <div class="wall-name">{{ m.maker }}</div>
        <div class="wall-count">本地 {{ m.local_count }} 款<span v-if="m.sample_title"> · {{ m.sample_title }}</span></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useLibraryStore } from '../stores/library.js'

const store = useLibraryStore()
const q = ref('')

const filtered = computed(() => {
  const kw = q.value.trim().toLowerCase()
  if (!kw) return store.makers.list
  return store.makers.list.filter((m) => m.maker.toLowerCase().includes(kw))
})

function enterMaker(m) {
  store.openMaker(m.maker)
}

function newCount(maker) {
  // 新作区里该厂商未拥有的作品数（粗匹配：以 local_title/maker 近似）
  const mk = maker.toLowerCase()
  return store.newReleases.items.filter((w) => !w.owned && (w.maker || '').toLowerCase() === mk).length
}

function refresh() {
  store.refreshNewReleases()
}

onMounted(() => {
  store.loadMakersWall()
  store.loadNewReleases()
  store.loadFollows()
  store.pollWorkTranslate()
})
</script>
