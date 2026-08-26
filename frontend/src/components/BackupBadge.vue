<template>
  <div
    v-if="state"
    class="backup-badge"
    :class="state"
    :title="title"
  >
    <span v-if="state === 'backed'">☁ {{ timeText }}</span>
    <span v-else-if="state === 'dirty'">▲ 存档有变动</span>
    <span v-else>○ 未备份</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // { last_backup_at, total_bytes, backup_count, save_paths }
  meta: { type: Object, default: null },
})

const state = computed(() => {
  if (!props.meta) return null
  if (props.meta.save_paths && props.meta.save_paths.length && props.meta.last_backup_at) {
    // 有配置且有备份 → 已备份
    return 'backed'
  }
  if (props.meta.save_paths && props.meta.save_paths.length) {
    return 'dirty' // 已配置但从未备份成功
  }
  return null
})

const timeText = computed(() => {
  if (!props.meta || !props.meta.last_backup_at) return ''
  const t = new Date(props.meta.last_backup_at.replace(' ', 'T'))
  if (isNaN(t.getTime())) return '' // 非法时间不渲染（防 "Invalid Date"）
  const diff = Date.now() - t.getTime()
  const days = Math.floor(diff / 86400000)
  if (days <= 0) return '今天'
  if (days === 1) return '昨天'
  if (days < 7) return `${days}天前`
  const weeks = Math.floor(days / 7)
  if (weeks < 5) return `${weeks}周前`
  return t.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
})

const title = computed(() => {
  if (!props.meta) return ''
  const parts = []
  if (props.meta.last_backup_at) parts.push(`上次备份: ${props.meta.last_backup_at}`)
  if (props.meta.backup_count) parts.push(`已备份 ${props.meta.backup_count} 次`)
  if (props.meta.total_bytes) parts.push(`约 ${(props.meta.total_bytes / 1024).toFixed(0)} KB`)
  return parts.join('\n')
})
</script>

<style scoped>
.backup-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 3;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  backdrop-filter: blur(4px);
  pointer-events: none;
  user-select: none;
  white-space: nowrap;
}
.backup-badge.backed {
  background: rgba(46, 160, 67, 0.85);
  color: #fff;
}
.backup-badge.dirty {
  background: rgba(219, 151, 21, 0.9);
  color: #fff;
}
</style>
