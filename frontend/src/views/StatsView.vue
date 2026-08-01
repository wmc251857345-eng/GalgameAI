<template>
  <div class="view-page">
    <div class="library-head">
      <h1>统计</h1>
    </div>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-num">{{ summary.total }}</div>
        <div class="stat-label">游戏总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ summary.playtime_hours }}</div>
        <div class="stat-label">总游玩时长 (h)</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ summary.confirmed }}</div>
        <div class="stat-label">已确认</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ summary.makers }}</div>
        <div class="stat-label">厂商数</div>
      </div>
    </div>
    <p class="empty-sub" style="margin-top: 16px">
      完整统计（厂商 TOP / 标签云 / 年度报告）将在 Phase 3 实现
    </p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLibraryStore } from '../stores/library.js'

const store = useLibraryStore()
const summary = computed(() => store.summary)
</script>
