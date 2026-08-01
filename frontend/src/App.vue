<template>
  <div class="app">
    <Sidebar :current="store.currentView" @nav="store.currentView = $event" />
    <div class="main">
      <TopBar v-if="store.currentView === 'library'" v-model:search="store.search" v-model:sort="store.sort" />
      <div class="content">
        <LibraryView v-if="store.currentView === 'library'" />
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
import Sidebar from './components/Sidebar.vue'
import TopBar from './components/TopBar.vue'
import LibraryView from './views/LibraryView.vue'
import PendingView from './views/PendingView.vue'
import StatsView from './views/StatsView.vue'
import SettingsView from './views/SettingsView.vue'

const store = useLibraryStore()
onMounted(() => store.load())
</script>
