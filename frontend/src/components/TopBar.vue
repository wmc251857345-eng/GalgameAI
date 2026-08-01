<template>
  <header class="topbar">
    <div class="search">
      <span class="search-icon">⌕</span>
      <input v-model="search" placeholder="搜索游戏 / 厂商 / 标签…" />
    </div>
    <div class="spacer"></div>
    <select v-model="sort" class="sort">
      <option value="title">按名称</option>
      <option value="year">发售年份</option>
      <option value="playtime">游玩时长</option>
      <option value="score">评分</option>
    </select>
  </header>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ search: String, sort: String })
const emit = defineEmits(['update:search', 'update:sort'])

const search = computed({
  get: () => props.search,
  set: (v) => emit('update:search', v),
})
const sort = computed({
  get: () => props.sort,
  set: (v) => emit('update:sort', v),
})
</script>
