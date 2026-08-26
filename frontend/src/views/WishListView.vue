<template>
  <div class="view-page wishlist">
    <div class="library-head">
      <h1>🎯 想玩清单</h1>
      <span class="count">{{ store.wishlist.items.length }} 条</span>
    </div>

    <!-- 添加条 -->
    <div class="wish-add">
      <input
        v-model="title"
        class="wish-title-input"
        placeholder="游戏名（必填），回车快速添加"
        @keyup.enter="add"
      />
      <input v-model="note" class="wish-note-input" placeholder="备注：为什么想玩 / 在哪看到的" />
      <button class="btn small primary" :disabled="adding" @click="add">{{ adding ? '添加中…' : '＋ 加入' }}</button>
    </div>
    <p v-if="hint" class="wish-hint" :class="{ warn: hintWarn }">{{ hint }}</p>

    <div v-if="store.wishlist.loading" class="loading">加载中…</div>

    <div v-else-if="!store.wishlist.items.length" class="empty">
      <div class="empty-icon">🎯</div>
      <p>清单还是空的</p>
      <p class="empty-sub">看到想玩的 Galgame 就先记下来，别到时候忘了名字</p>
    </div>

    <div v-else class="wish-list">
      <div v-for="w in store.wishlist.items" :key="w.id" class="wish-row">
        <template v-if="editId === w.id">
          <input v-model="editTitle" class="wish-title-input" />
          <input v-model="editNote" class="wish-note-input" placeholder="备注" />
          <button class="btn small primary" @click="saveEdit(w)">✓ 保存</button>
          <button class="btn small" @click="cancelEdit">取消</button>
        </template>
        <template v-else>
          <div class="wish-main">
            <span class="wish-title">{{ w.title }}</span>
            <span v-if="w.in_library === false && libHas(w.title)" class="status-badge ok" title="库里有同名游戏，去搜一下">已在库</span>
          </div>
          <div class="wish-sub">
            <span v-if="w.note" class="wish-note">{{ w.note }}</span>
            <span class="wish-date">{{ (w.created_at || '').slice(0, 10) }}</span>
          </div>
          <div class="wish-actions">
            <button class="btn small" @click="startEdit(w)">✏</button>
            <button class="btn small danger-soft" title="移除" @click="remove(w)">🗑</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useLibraryStore } from '../stores/library.js'

const store = useLibraryStore()
const title = ref('')
const note = ref('')
const adding = ref(false)
const hint = ref('')
const hintWarn = ref(false)

// 行内编辑
const editId = ref(null)
const editTitle = ref('')
const editNote = ref('')

function libHas(t) {
  return store.games.some((g) => (g.title || '').toLowerCase() === String(t || '').toLowerCase())
}

async function add() {
  const t = title.value.trim()
  if (!t) return
  adding.value = true
  hint.value = ''
  try {
    const r = await store.wishlistAdd(t, note.value.trim())
    if (r && r.ok) {
      if (r.in_library) {
        hint.value = `提示：《${t}》已经在你的游戏库里了`
        hintWarn.value = true
      } else {
        hint.value = `已加入《${t}》`
        hintWarn.value = false
      }
      title.value = ''
      note.value = ''
      await store.loadWishlist()
    } else {
      hint.value = (r && r.error) || '添加失败'
      hintWarn.value = true
    }
  } catch (e) {
    hint.value = e.message || '添加失败'
    hintWarn.value = true
  } finally {
    adding.value = false
  }
}

function startEdit(w) {
  editId.value = w.id
  editTitle.value = w.title || ''
  editNote.value = w.note || ''
}

function cancelEdit() {
  editId.value = null
}

async function saveEdit(w) {
  const r = await store.wishlistUpdate(w.id, { title: editTitle.value.trim(), note: editNote.value.trim() })
  if (r && !r.ok) { alert(r.error); return }
  editId.value = null
}

async function remove(w) {
  if (!confirm(`从想玩清单移除「${w.title}」？`)) return
  await store.wishlistRemove(w.id)
}
</script>

<style scoped>
.wish-add {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.wish-title-input {
  flex: 0 0 260px;
}
.wish-note-input {
  flex: 1;
}
.wish-add input {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  color: var(--text, #e8eaed);
  padding: 7px 10px;
  font-size: 13px;
}
.wish-hint {
  font-size: 12px;
  margin: 0 0 8px;
  opacity: 0.85;
}
.wish-hint.warn {
  color: #ffd166;
}
.wish-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.wish-row {
  display: grid;
  grid-template-columns: minmax(200px, 1fr) minmax(120px, 1.4fr) auto;
  align-items: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 10px;
  padding: 10px 14px;
}
.wish-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.wish-title {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wish-sub {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.wish-note {
  font-size: 12px;
  opacity: 0.75;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wish-date {
  font-size: 11px;
  opacity: 0.5;
}
.wish-actions {
  display: flex;
  gap: 6px;
}
.status-badge.ok {
  background: rgba(46, 160, 67, 0.2);
  color: #56d364;
  padding: 1px 8px;
  border-radius: 9px;
  font-size: 11px;
}
@media (max-width: 900px) {
  .wish-row { grid-template-columns: 1fr; }
}
</style>
