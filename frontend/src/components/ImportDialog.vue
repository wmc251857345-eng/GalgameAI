<template>
  <div class="wd-overlay" @click.self="$emit('close')">
    <div class="wd-panel imp-panel">
      <button class="wd-close" title="关闭" @click="$emit('close')">✕</button>
      <h2 class="fixer-title">＋ 导入本地游戏</h2>

      <!-- 步骤 1：选文件 -->
      <div class="imp-step-label">① 选择游戏（exe 或整个文件夹）</div>
      <div class="imp-pick-row">
        <button class="btn" :disabled="busy" @click="pick('exe')">📁 选择游戏 exe</button>
        <button class="btn" :disabled="busy" @click="pick('folder')">🗂 选择游戏文件夹</button>
      </div>
      <div v-if="pickedPath" class="imp-picked" :title="pickedPath">
        ✅ {{ pickedPath }}
      </div>

      <!-- 步骤 2：备注 -->
      <div class="imp-step-label" style="margin-top: 14px">② 简单描述（可空，越具体 AI 补得越准）</div>
      <textarea
        v-model="note"
        class="imp-note"
        rows="3"
        placeholder="例如：这是《XX》的汉化版，开发商是 XX 社，纯爱剧情作……"
      ></textarea>

      <!-- 步骤 3：AI 补全 -->
      <div class="imp-actions">
        <button
          class="btn primary"
          :disabled="busy || !pickedPath"
          @click="doImport"
        >{{ importing ? '✨ AI 补全中…' : '✨ AI 补全录入' }}</button>
      </div>

      <p v-if="error" class="wd-err">{{ error }}</p>

      <!-- 结果 -->
      <div v-if="result" class="imp-result">
        <div class="imp-result-head">
          ✅ 已录入《<b>{{ result.title }}</b>》
          <span class="imp-src">{{ result.provider.toUpperCase() }}</span>
        </div>
        <p class="imp-result-sub">
          <template v-if="result.matched">资料来源：{{ result.provider.toUpperCase() }}《{{ result.matched }}》，正在后台补全封面/简介/中文名…</template>
          <template v-else>未搜到外部资料，已按你的描述建条目，可稍后让 AI 管家或详情页补全。</template>
        </p>
        <div v-if="result.alternates && result.alternates.length" class="imp-alt">
          <div class="imp-alt-label">资料好像不太对？换用其他候选：</div>
          <div
            v-for="c in result.alternates"
            :key="c.provider + c.external_id"
            class="imp-alt-item"
            :class="{ switching: switchingId === c.external_id }"
            @click="switchSource(c)"
          >
            <img v-if="c.cover_url" :src="c.cover_url" class="imp-alt-cover" v-imgfb="''" alt="" />
            <div class="imp-alt-info">
              <div>{{ c.title }} <span class="imp-src">{{ c.provider.toUpperCase() }}</span></div>
              <div class="dim">{{ c.maker || '—' }} · {{ c.released || '未知' }}</div>
            </div>
            <span class="imp-alt-btn">{{ switchingId === c.external_id ? '…' : '换用' }}</span>
          </div>
        </div>
        <div class="imp-actions" style="margin-top: 14px">
          <button class="btn primary" @click="openDetail">🔍 打开详情</button>
          <button class="btn" @click="$emit('close')">完成</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'

const emit = defineEmits(['close', 'imported'])
const store = useLibraryStore()

const pickedPath = ref('')
const exePath = ref('')
const folder = ref('')
const note = ref('')
const busy = ref(false)
const importing = ref(false)
const error = ref('')
const result = ref(null)
const switchingId = ref('')

function onKey(e) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

async function pick(kind) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const r = await api.pickGamePath(kind)
    if (r && r.ok) {
      pickedPath.value = kind === 'exe' ? r.path : r.folder
      exePath.value = kind === 'exe' ? r.path : ''
      folder.value = r.folder
      // 文件夹名预填到备注里当参考（可改）
      if (r.title && !note.value.trim()) note.value = r.title
    } else {
      error.value = (r && r.error) || '未选择'
    }
  } catch (e) {
    error.value = e.message || '选择失败'
  } finally {
    busy.value = false
  }
}

async function doImport() {
  if (importing.value || !pickedPath.value) return
  importing.value = true
  error.value = ''
  result.value = null
  try {
    const r = await store.importLocal({ exe_path: exePath.value, folder: folder.value, note: note.value })
    if (r && r.ok) {
      result.value = r
      note.value = ''
    } else {
      error.value = (r && r.error) || '录入失败'
    }
  } catch (e) {
    error.value = e.message || '录入失败（超时或网络异常）'
  } finally {
    importing.value = false
  }
}

async function switchSource(c) {
  if (!result.value) return
  switchingId.value = c.external_id
  try {
    const r = await store.reimportSource(result.value.id, c)
    if (r && r.ok) {
      result.value.matched = c.title
      result.value.provider = c.provider
      result.value.alternates = (result.value.alternates || []).filter((x) => x !== c)
      alert(`已换用 ${c.provider.toUpperCase()}《${c.title}》的资料，正在后台补全…`)
    } else {
      alert((r && r.error) || '换用失败')
    }
  } catch (e) {
    alert(e.message || '换用失败')
  } finally {
    switchingId.value = ''
  }
}

function openDetail() {
  const id = result.value && result.value.id
  emit('close')
  if (id) emit('imported', id)
}
</script>
