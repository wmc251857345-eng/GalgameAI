<template>
  <div class="game-card" @click="$emit('open', game.id)" @contextmenu.prevent="$emit('ctx', $event, game)">
    <div class="cover" :style="{ '--hue': game.hue ?? 220 }">
      <img v-if="game.cover_url" :src="game.cover_url" class="cover-img" alt="" v-imgfb="''" />
      <div v-else class="cover-grad"></div>
      <button
        v-if="game.favorite"
        class="cover-fav on"
        title="取消收藏"
        @click.stop="$emit('fav', game)"
      >♥</button>
      <div class="cover-title">{{ game.title }}</div>
      <div class="cover-hover">
        <div class="ch-maker">{{ game.maker || '未知厂商' }}</div>
        <div class="ch-year">{{ game.released?.slice(0, 4) || '—' }}</div>
        <div class="ch-score">★ {{ game.score ?? '--' }}</div>
        <div class="ch-tags">{{ (game.tags || []).slice(0, 3).join(' · ') }}</div>
        <button class="ch-play" @click.stop="$emit('launch')">{{ game.running ? '运行中…' : '启动' }}</button>
      </div>
      <div v-if="game.playtime_hours > 0" class="cover-time">{{ game.playtime_hours }}h</div>
      <div v-if="game.status === 1" class="cover-pending">待确认</div>
      <div v-if="game.status === 3" class="cover-pending cover-skip">已跳过</div>
    </div>
    <div class="card-title">{{ game.title }}</div>
    <div class="card-sub">{{ (game.tags || []).slice(0, 3).join(' · ') || game.title_en }}</div>
  </div>
</template>

<script setup>
defineProps({ game: Object })
defineEmits(['open', 'fav', 'launch', 'ctx'])
</script>
