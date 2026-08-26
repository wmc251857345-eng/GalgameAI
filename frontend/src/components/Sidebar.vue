<template>
  <aside class="sidebar">
    <div class="logo">
      <div class="logo-badge">G</div>
      <div class="logo-text">
        <div class="logo-name">GALA</div>
        <div class="logo-sub">Galgame AI Library</div>
      </div>
    </div>
    <nav class="nav">
      <button
        v-for="item in items"
        :key="item.id"
        class="nav-item"
        :class="{ active: current === item.id }"
        @click="$emit('nav', item.id)"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        <span>{{ item.label }}</span>
        <span v-if="item.id === 'pending' && store.summary.pending > 0" class="nav-badge">
          {{ store.summary.pending }}
        </span>
        <span v-if="item.id === 'makers' && newBadge > 0" class="nav-badge" title="近两年未拥有的新作">
          {{ newBadge }}
        </span>
      </button>
    </nav>
    <div class="sidebar-footer">
      <!-- 更新提示（v1.1）：有新版时点击直达设置页的更新区块 -->
      <button v-if="hasUpdate" class="update-pill" @click="$emit('nav', 'settings')">
        🆕 新版本 v{{ updateLatest }} 可用 · 点击查看
      </button>
      <div class="ver" title="版本自检：构建版本 · 日期 · git 提交" @click="$emit('nav', 'settings')">
        v{{ appInfo.version || '?' }}{{ appInfo.build?.build_date ? ' · ' + appInfo.build.build_date : '' }}
        {{ appInfo.build?.git ? ' · ' + appInfo.build.git : '' }}
      </div>
      <div class="ver sub">本地库 · {{ appInfo.platform }}</div>
    </div>
  </aside>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'

defineProps({ current: String })
defineEmits(['nav'])

const store = useLibraryStore()
const appInfo = ref({ version: '', platform: '' })

// 厂商墙角标：未拥有的新作数
const newBadge = computed(() =>
  store.newReleases.items.filter((w) => !w.owned).length,
)

// 更新角标（v1.1）
const hasUpdate = computed(() => !!(store.update.info && store.update.info.has_update))
const updateLatest = computed(() =>
  String(store.update.info?.latest || '').replace(/^v/, ''))

const items = [
  { id: 'library', icon: '▤', label: '游戏库' },
  { id: 'chat', icon: '💬', label: 'AI 管家' },
  { id: 'makers', icon: '🏭', label: '厂商墙' },
  { id: 'wishlist', icon: '🎯', label: '想玩清单' },
  { id: 'pending', icon: '◷', label: '待确认' },
  { id: 'stats', icon: '◔', label: '统计' },
  { id: 'settings', icon: '⚙', label: '设置' },
]

onMounted(async () => {
  try {
    appInfo.value = await api.getAppInfo()
  } catch (e) { /* 版本号拿不到就留空，不再显示假版本 */ }
  store.loadNewReleases()  // 侧栏角标数据
  store.checkUpdate()      // 静默更新检查（后端有 24h 缓存）
})
</script>

<style scoped>
.update-pill {
  width: 100%;
  border: 1px solid rgba(102, 192, 244, 0.45);
  background: rgba(102, 192, 244, 0.12);
  color: #8ecdf8;
  font-size: 11.5px;
  padding: 6px 8px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 6px;
}
.update-pill:hover {
  background: rgba(102, 192, 244, 0.22);
}
</style>
