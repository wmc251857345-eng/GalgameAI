<template>
  <div class="view-page">
    <div class="library-head">
      <h1 v-if="store.maker.mode === 'maker'">{{ store.maker.key }}</h1>
      <h1 v-else>🧩 {{ profileTitle }}</h1>
      <span class="count">{{ headerNote }}</span>
      <div class="head-actions">
        <button
          v-if="store.maker.mode === 'maker' && store.maker.profile"
          class="btn small"
          :class="{ followed: isFollowed }"
          @click="toggleFollow"
        >
          {{ isFollowed ? '★ 已关注' : '☆ 关注' }}
        </button>
        <button v-if="store.maker.mode === 'maker' && store.maker.profile" class="btn small" @click="openFixer">
          🔧 更正厂商
        </button>
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
      <div class="maker-error-actions">
        <button class="btn small" @click="retry">重试</button>
        <button v-if="store.maker.error.includes('没找到')" class="btn small" @click="openFixer">🔧 手动指定厂商</button>
      </div>
    </div>

    <template v-else-if="store.maker.profile">
      <!-- 厂商简介 + 当前映射信息 -->
      <div v-if="store.maker.mode === 'maker' && profile.producer" class="maker-intro">
        <div class="maker-badges">
          <span class="mk-badge">{{ typeLabel(profile.producer.type) }}</span>
          <span class="mk-badge">{{ profile.producer.id }}</span>
          <span v-if="profile.mapped" class="mk-badge mapped" title="该映射已被记住，下次直接命中">✓ 已记忆</span>
          <span v-if="store.tagTranslating" class="mk-badge">标签翻译中…</span>
        </div>
        <p v-if="profile.producer.description" class="maker-desc">{{ profile.producer.description }}</p>
        <p v-else class="maker-desc dim">（VNDB 暂无简介）</p>
      </div>

      <!-- 标签筛选条 -->
      <div v-if="allTagNames.length" class="tag-filter">
        <span class="tag-filter-label">筛选：</span>
        <button
          class="tf-chip"
          :class="{ active: tagFilter === '' }"
          @click="tagFilter = ''"
        >全部（{{ profile.works.length }}）</button>
        <button
          v-for="t in allTagNames"
          :key="t"
          class="tf-chip"
          :class="{ active: tagFilter === t }"
          @click="tagFilter = tagFilter === t ? '' : t"
        >{{ t }}</button>
      </div>

      <!-- 作品网格 -->
      <div class="mk-works-head">
        <span>全部作品（{{ filteredWorks.length }}{{ tagFilter ? ' / ' + profile.total_count : '' }}）</span>
        <span class="mk-owned">已拥有 <b>{{ profile.owned_count }}</b></span>
      </div>
      <div v-if="filteredWorks.length" class="mk-grid">
        <div
          v-for="w in filteredWorks"
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
            <div v-if="w.title_jp" class="mk-title-jp" :title="w.title_jp">{{ w.title_jp }}</div>
            <div class="mk-meta">
              <span>{{ w.released || '未知日期' }}</span>
              <span v-if="w.rating">★ {{ (w.rating / 10).toFixed(1) }}</span>
              <span>{{ lengthLabel(w.length_level) }}</span>
            </div>
            <div v-if="w.tags_zh && w.tags_zh.length" class="mk-tags">
              <span v-for="t in w.tags_zh.slice(0, 4)" :key="t" class="mk-tag">#{{ t }}</span>
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
      <div v-else class="dim" style="padding: 20px 0">没有符合该标签的作品</div>
    </template>

    <!-- 更正厂商弹层 -->
    <div v-if="fixerOpen" class="wd-overlay" @click.self="fixerOpen = false">
      <div class="wd-panel fixer-panel">
        <button class="wd-close" @click="fixerOpen = false">✕</button>
        <h2 class="fixer-title">🔧 更正厂商「{{ store.maker.key }}」</h2>
        <p class="dim" style="font-size: 12px; margin-bottom: 10px">
          当前 VNDB 匹配：<b>{{ profile?.producer?.name }}（{{ profile?.producer?.id }}）</b>。搜索正确的厂商并选择，之后会自动记住。
        </p>
        <div class="fixer-search">
          <input
            v-model="fixerKw"
            class="chat-input"
            placeholder="输入厂商名（英文/日文均可）搜索…"
            @keyup.enter="doSearch"
          />
          <button class="btn primary" :disabled="searching" @click="doSearch">
            {{ searching ? '搜索中…' : '搜索' }}
          </button>
        </div>
        <div v-if="fixerCands.length" class="fixer-list">
          <div
            v-for="c in fixerCands"
            :key="c.id"
            class="fixer-item"
            :class="{ active: c.id === (profile?.producer?.id || '') }"
            @click="applyMapping(c)"
          >
            <div class="fixer-item-name">{{ c.name }} <span class="dim">{{ c.id }}</span></div>
            <div v-if="c.aliases && c.aliases.length" class="dim fixer-item-alias">{{ c.aliases.slice(0, 4).join(' · ') }}</div>
          </div>
        </div>
        <p v-if="fixerDone" class="fixer-done">✅ 已更新并记住映射，正在刷新…</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'

const store = useLibraryStore()
const profile = computed(() => store.maker.profile)

const LEN = { 1: '很短', 2: '短', 3: '中等', 4: '长', 5: '很长' }
const FAMILY = new Set(['ser', 'seq', 'preq', 'side', 'fan', 'alt', 'par', 'set', 'orig'])

const tagFilter = ref('')
const fixerOpen = ref(false)
const fixerKw = ref('')
const fixerCands = ref([])
const searching = ref(false)
const fixerDone = ref(false)

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

const isFollowed = computed(() => store.isFollowed(store.maker.key))

// 标签聚合（去重，含中文名）
const allTagNames = computed(() => {
  const set = new Set()
  for (const w of profile.value?.works || []) {
    for (const t of w.tags_zh || w.tags || []) set.add(t)
  }
  return [...set].sort()
})

const filteredWorks = computed(() => {
  const works = profile.value?.works || []
  if (!tagFilter.value) return works
  return works.filter((w) => (w.tags_zh || w.tags || []).includes(tagFilter.value))
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

// 厂商墙导航
const makerIndex = computed(() => store.makers.list.findIndex((m) => m.maker === store.maker.key))
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

async function toggleFollow() {
  const p = profile.value?.producer
  await store.toggleFollow(store.maker.key, p?.id || '', p?.name || '')
}

// 更正厂商
function openFixer() {
  fixerOpen.value = true
  fixerCands.value = []
  fixerDone.value = false
  fixerKw.value = ''
  setTimeout(() => {
    const input = document.querySelector('.fixer-search input')
    if (input) input.focus()
  }, 50)
}

async function doSearch() {
  if (!fixerKw.value.trim() || searching.value) return
  searching.value = true
  fixerCands.value = []
  try {
    const r = await api.searchProducers(fixerKw.value.trim())
    if (r && r.ok) fixerCands.value = r.candidates || []
  } finally {
    searching.value = false
  }
}

async function applyMapping(c) {
  const r = await api.setMakerMapping(store.maker.key, c.id, c.name)
  if (r && r.ok) {
    fixerDone.value = true
    setTimeout(async () => {
      fixerOpen.value = false
      await store.loadMakerProfile(store.maker.key)
      store.loadMakersWall()
    }, 600)
  }
}

function retry() {
  if (store.maker.mode === 'maker') store.loadMakerProfile(store.maker.key)
  else store.loadSeriesProfile(store.maker.key)
}

onMounted(() => {
  store.loadFollows()
  // 触发未翻译标签的批量翻译
  const tags = new Set()
  for (const w of profile.value?.works || []) {
    for (const t of w.tags || []) tags.add(t)
  }
  if (tags.size) store.ensureTagTranslate([...tags])
})

// 标签翻译完成 → 刷新档案（后端缓存命中会实时应用最新中文标签）
watch(
  () => store.tagTranslating,
  (v, old) => {
    if (old && !v && store.currentView === 'maker' && profile.value) {
      store.loadMakerProfile(store.maker.key)
    }
  },
)

onBeforeUnmount(() => {
  tagFilter.value = ''
})
</script>
