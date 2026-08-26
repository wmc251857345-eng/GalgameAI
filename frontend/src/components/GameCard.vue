<template>
  <div
    class="game-card"
    :class="{ 'select-mode': selectable, selected }"
    @click="$emit('open', game.id)"
    @contextmenu.prevent="$emit('ctx', $event, game)"
  >
    <div class="cover" :style="{ '--hue': game.hue ?? 220 }">
      <img v-if="game.cover_url" :src="game.cover_url" class="cover-img" alt="" v-imgfb="''" />
      <div v-else class="cover-grad"></div>
      <button
        v-if="game.favorite && !selectable"
        class="cover-fav on"
        title="取消收藏"
        @click.stop="$emit('fav', game)"
      >♥</button>
      <!-- 批量选择角标（v1.1） -->
      <span v-if="selectable" class="select-mark" :class="{ on: selected }">
        {{ selected ? '☑' : '☐' }}
      </span>
      <div class="cover-title">{{ game.title }}</div>
      <div class="cover-hover">
        <div class="ch-maker">{{ game.maker || '未知厂商' }}</div>
        <div class="ch-year">{{ game.released?.slice(0, 4) || '—' }}</div>
        <div class="ch-score">★ {{ game.score ?? '--' }}</div>
        <div class="ch-tags">{{ (game.tags || []).slice(0, 3).join(' · ') }}</div>
        <button v-if="!selectable" class="ch-play" @click.stop="$emit('launch')">{{ game.running ? '运行中…' : '启动' }}</button>
      </div>
      <div v-if="game.user_rating" class="cover-stars" title="我的评分">{{ '★'.repeat(game.user_rating) }}</div>
      <div v-if="game.playtime_hours > 0" class="cover-time">{{ game.playtime_hours }}h</div>
      <div v-if="game.status === 0" class="cover-pending cover-analyze">待分析</div>
      <div v-if="game.status === 1" class="cover-pending">待确认</div>
      <div v-if="game.status === 3" class="cover-pending cover-skip">已跳过</div>
      <BackupBadge v-if="game.backup_meta" :meta="game.backup_meta" />
    </div>
    <div class="card-title">{{ game.title }}</div>
    <div class="card-sub">{{ (game.tags || []).slice(0, 3).join(' · ') || game.title_en }}</div>
  </div>
</template>

<script setup>
import BackupBadge from './BackupBadge.vue'
defineProps({
  game: Object,
  selectable: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
})
defineEmits(['open', 'fav', 'launch', 'ctx', 'toggle-select'])
</script>

<style scoped>
/* 批量选择态：卡片高亮描边 + 角标 */
.game-card.select-mode {
  cursor: pointer;
}
.game-card.selected .cover {
  outline: 2px solid var(--accent, #66c0f4);
  outline-offset: -2px;
  border-radius: inherit;
}
.select-mark {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 4;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.55);
  color: #cfd8e3;
  font-size: 16px;
  pointer-events: none;
}
.select-mark.on {
  background: var(--accent, #66c0f4);
  color: #fff;
}
.cover-stars {
  position: absolute;
  left: 8px;
  bottom: 34px;
  z-index: 3;
  font-size: 11px;
  color: #ffd166;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.9);
  pointer-events: none;
}
</style>
