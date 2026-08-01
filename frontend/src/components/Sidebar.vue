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
      </button>
    </nav>
    <div class="sidebar-footer">
      <div class="ver">v{{ appInfo.version }} · 本地库 · {{ appInfo.platform }}</div>
    </div>
  </aside>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'

defineProps({ current: String })
defineEmits(['nav'])

const store = useLibraryStore()
const appInfo = ref({ version: '0.1.0', platform: '' })

const items = [
  { id: 'library', icon: '▤', label: '游戏库' },
  { id: 'chat', icon: '💬', label: 'AI 管家' },
  { id: 'makers', icon: '🏭', label: '厂商墙' },
  { id: 'pending', icon: '◷', label: '待确认' },
  { id: 'stats', icon: '◔', label: '统计' },
  { id: 'settings', icon: '⚙', label: '设置' },
]

onMounted(async () => {
  appInfo.value = await api.getAppInfo()
})
</script>
