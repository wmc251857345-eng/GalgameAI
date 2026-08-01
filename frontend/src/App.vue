<template>
  <div class="app">
    <Sidebar :current="store.currentView" @nav="onNav" />
    <div class="main">
      <!-- 全局渲染错误横幅（点击关闭；渲染异常不再静默冻结） -->
      <div v-if="errorBanner" class="error-banner" @click="errorBanner = ''">
        ⚠ {{ errorBanner }}
      </div>
      <TopBar
        v-if="store.currentView === 'library'"
        v-model:search="store.search"
        v-model:sort="store.sort"
      />
      <div class="content">
        <LibraryView v-if="store.currentView === 'library'" />
        <DetailView v-else-if="store.currentView === 'detail'" />
        <ChatView v-else-if="store.currentView === 'chat'" />
        <MakerView v-else-if="store.currentView === 'maker'" />
        <MakersWallView v-else-if="store.currentView === 'makers'" />
        <PendingView v-else-if="store.currentView === 'pending'" />
        <StatsView v-else-if="store.currentView === 'stats'" />
        <SettingsView v-else />
      </div>
      <WorkDetailPanel />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useLibraryStore } from './stores/library.js'
import { apiReady } from './api.js'
import Sidebar from './components/Sidebar.vue'
import TopBar from './components/TopBar.vue'
import LibraryView from './views/LibraryView.vue'
import DetailView from './views/DetailView.vue'
import ChatView from './views/ChatView.vue'
import MakerView from './views/MakerView.vue'
import MakersWallView from './views/MakersWallView.vue'
import WorkDetailPanel from './components/WorkDetailPanel.vue'
import PendingView from './views/PendingView.vue'
import StatsView from './views/StatsView.vue'
import SettingsView from './views/SettingsView.vue'

const store = useLibraryStore()
const errorBanner = ref('')

// main.js 的 errorHandler 会把渲染错误写到这里显示
window.__galaSetError = (msg) => { errorBanner.value = msg }

function onNav(view) {
  store.currentView = view
}

onMounted(async () => {
  await apiReady() // 等 pywebview 桥接注入完成再加载真实数据（修复 mock 竞态）
  store.load()
  store.loadRoots()
  store.refreshRunning()
})
</script>
