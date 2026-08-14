<template>
  <div class="library" @click="closeCtx">
    <div class="library-head">
      <h1>游戏库</h1>
      <span class="count">{{ store.filteredGames.length }} / {{ store.summary.total }} 部</span>
      <div class="head-actions">
        <button class="btn small" @click="importOpen = true">＋ 导入游戏</button>
        <button v-if="store.filterStatus === 3" class="btn small danger-soft" @click="clearSkipped">
          🗑 清空已跳过
        </button>
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

    <!-- 排序栏：制作组 / 发售时间 / 标题首字 / 评分 / 时长 / 收藏 + 方向切换 -->
    <div class="sort-bar">
      <span class="sort-label">排序</span>
      <button
        v-for="s in sortOptions"
        :key="s.id"
        class="sort-btn"
        :class="{ active: store.sort === s.id }"
        @click="store.setSort(s.id)"
      >{{ s.label }}</button>
      <button
        class="sort-dir"
        :title="store.sortDir === 'desc' ? '当前降序（新→旧 / 大→小），点击切换升序' : '当前升序（旧→新 / 小→大），点击切换降序'"
        @click="store.setSort(store.sort, store.sortDir === 'desc' ? 'asc' : 'desc')"
      >{{ store.sortDir === 'desc' ? '↓ 降序' : '↑ 升序' }}</button>
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
        @ctx="openCtx"
      />
    </div>

    <!-- 列表视图 -->
    <div v-else class="list-view">
      <div
        v-for="g in store.filteredGames"
        :key="g.id"
        class="list-row"
        @click="store.openDetail(g.id)"
        @contextmenu.prevent="openCtx($event, g)"
      >
        <span class="list-fav" :class="{ on: g.favorite }" @click.stop="store.toggleFavorite(g)">♥</span>
        <img v-if="g.cover_url" :src="g.cover_url" class="list-cover" alt="" v-imgfb="''" />
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
          <span v-if="g.status === 0" class="status-badge analyze">⚙ 待分析</span>
          <span v-if="g.status === 2" class="status-badge ok">✓ 已入库</span>
          <span v-else-if="g.status === 1" class="status-badge warn">待确认</span>
          <span v-else-if="g.status === 3" class="status-badge skip">已跳过</span>
          <span v-if="g.hanhua" class="status-badge hanhua">汉化</span>
          <span v-if="g.exe_path && !g.exe_exists" class="status-badge skip" title="exe 不存在">!路径失效</span>
        </div>
      </div>
    </div>

    <!-- 右键菜单 -->
    <div
      v-if="ctxMenu.visible"
      class="ctx-menu"
      :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
      @click.stop
    >
      <div class="ctx-head">{{ ctxMenu.game.title }}</div>
      <button class="ctx-item" @click="ctxOpenDetail">🔍 打开详情</button>
      <button class="ctx-item" @click="ctxCover">🖼 修改封面</button>
      <button v-if="ctxMenu.game.exe_path" class="ctx-item" @click="ctxLaunch">▶ 启动游戏</button>
      <button class="ctx-item danger" @click="ctxDelete">🗑 删除（仅移出库）</button>
    </div>

    <!-- 导入弹窗 -->
    <ImportDialog v-if="importOpen" @close="importOpen = false" @imported="onImported" />

    <!-- 修改封面弹窗 -->
    <CoverDialog
      v-if="coverOpen && coverGameId"
      :game-id="coverGameId"
      :title="coverGameTitle"
      @close="coverOpen = false"
      @done="onCoverDone"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'
import GameCard from '../components/GameCard.vue'
import ImportDialog from '../components/ImportDialog.vue'
import CoverDialog from '../components/CoverDialog.vue'

const store = useLibraryStore()

const importOpen = ref(false)
const coverOpen = ref(false)
const coverGameId = ref(null)
const coverGameTitle = ref('')
const ctxMenu = reactive({ visible: false, x: 0, y: 0, game: null })

// 右键菜单：点击任意处关闭（含滚动、Esc）
function openCtx(e, g) {
  const maxX = window.innerWidth - 190
  const maxY = window.innerHeight - 160
  ctxMenu.x = Math.min(e.clientX, maxX)
  ctxMenu.y = Math.min(e.clientY, maxY)
  ctxMenu.game = g
  ctxMenu.visible = true
}
function closeCtx() {
  ctxMenu.visible = false
}
function onKey(e) {
  if (e.key === 'Escape') closeCtx()
}
function ctxOpenDetail() {
  closeCtx()
  store.openDetail(ctxMenu.game.id)
}
function ctxCover() {
  const g = ctxMenu.game
  coverGameId.value = g.id
  coverGameTitle.value = g.title || ''
  coverOpen.value = true
  closeCtx()
}
function onCoverDone() {
  // 封面变了：刷新列表（网格/列表缩略图立即更新）
  store.load()
}
function ctxLaunch() {
  const g = ctxMenu.game
  closeCtx()
  api.launchGame(g.id).then((r) => {
    if (r && !r.ok) alert(r.error)
    else store.refreshRunning()
  })
}
async function ctxDelete() {
  const g = ctxMenu.game
  closeCtx()
  if (!confirm(`确定从库中删除「${g.title}」？仅移出库记录，不会动磁盘文件。`)) return
  await store.removeGame(g.id)
}
async function clearSkipped() {
  const skipped = store.filteredGames.filter((x) => x.status === 3)
  if (!skipped.length) return
  if (!confirm(`确定清空全部 ${skipped.length} 个已跳过项目？仅移出库记录，不会动磁盘文件。`)) return
  for (const g of skipped) {
    await api.removeGame(g.id)
  }
  await Promise.all([store.load(), store.loadPending()])
}
function onImported(id) {
  importOpen.value = false
  if (id) store.openDetail(id)
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
})

const tabs = computed(() => [
  { id: 'all', label: '全部', count: store.summary.total },
  { id: 2, label: '已入库', count: store.summary.confirmed },
  { id: 1, label: '待确认', count: store.summary.pending },
  { id: 'fav', label: '♥ 收藏' },
  { id: 3, label: '已跳过' },
])

const sortOptions = [
  { id: 'company', label: '制作组' },
  { id: 'year', label: '发售时间' },
  { id: 'title', label: '标题首字' },
  { id: 'score', label: '评分' },
  { id: 'playtime', label: '时长' },
  { id: 'favorite', label: '收藏' },
]

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
