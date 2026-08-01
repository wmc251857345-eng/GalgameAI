<template>
  <div class="app">
    <Sidebar :current="store.currentView" @nav="store.currentView = $event" />
    <div class="main">
      <TopBar
        v-if="store.currentView === 'library'"
        v-model:search="store.search"
        v-model:sort="store.sort"
      />
      <div class="content">
        <LibraryView v-if="store.currentView === 'library'" />
        <DetailView v-else-if="store.currentView === 'detail'" />
        <PendingView v-else-if="store.currentView === 'pending'" />
        <StatsView v-else-if="store.currentView === 'stats'" />
        <SettingsView v-else />
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useLibraryStore } from './stores/library.js'
import { apiReady } from './api.js'
import Sidebar from './components/Sidebar.vue'
import TopBar from './components/TopBar.vue'
import LibraryView from './views/LibraryView.vue'
import DetailView from './views/DetailView.vue'
import PendingView from './views/PendingView.vue'
import StatsView from './views/StatsView.vue'
import SettingsView from './views/SettingsView.vue'

const store = useLibraryStore()
onMounted(async () => {
  await apiReady() // 等 pywebview 桥接注入完成再加载真实数据（修复 mock 竞态）
  store.load()
  store.loadRoots()
  store.refreshRunning()
})
</script>
