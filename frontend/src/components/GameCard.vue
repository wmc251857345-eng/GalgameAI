<template>
  <div class="game-card">
    <div class="cover" :style="{ '--hue': game.hue ?? 220 }">
      <div class="cover-title">{{ game.title }}</div>
      <div class="cover-hover">
        <div class="ch-maker">{{ game.maker || '未知厂商' }}</div>
        <div class="ch-year">{{ game.year || '—' }}</div>
        <div class="ch-score">★ {{ game.score?.toFixed(1) ?? '--' }}</div>
        <button class="ch-play" disabled>启动</button>
      </div>
      <div v-if="game.playtime_hours > 0" class="cover-time">{{ game.playtime_hours }}h</div>
      <div v-if="game.status === 1" class="cover-pending">待确认</div>
    </div>
    <div class="card-title">{{ game.title }}</div>
    <div class="card-sub">{{ (game.tags || []).slice(0, 3).join(' · ') || game.title_en }}</div>
  </div>
</template>

<script setup>
defineProps({ game: Object })
</script>
