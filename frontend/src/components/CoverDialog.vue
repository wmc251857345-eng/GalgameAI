<template>
  <div class="wd-overlay" @click.self="$emit('close')">
    <div class="wd-panel cover-panel">
      <button class="wd-close" title="关闭" @click="$emit('close')">✕</button>
      <h2 class="cover-title">🖼 修改封面 — {{ title }}</h2>

      <!-- 当前封面 + 操作 -->
      <div class="cover-preview-row">
        <div class="cover-preview">
          <img v-if="currentUrl" :src="currentUrl" alt="" class="cover-preview-img" />
          <div v-else class="cover-preview-empty">当前无封面</div>
        </div>
        <div class="cover-actions">
          <button class="btn" :disabled="busy" @click="pickLocal">🖼 选择本地图片</button>
          <button class="btn" :disabled="busy" @click="fromVndb">⟳ 从 VNDB 补封面</button>
          <button class="btn" :disabled="busy || !currentUrl" @click="enterCrop">✂ 自定义裁剪区域</button>
          <button
            v-if="hasCrop"
            class="btn"
            :disabled="busy"
            title="恢复为不裁剪的原图（自动适配）"
            @click="resetCrop"
          >↺ 重置为自动适配</button>
          <div class="cover-url-row">
            <input v-model="urlInput" class="url-input" placeholder="或粘贴图片 URL 下载" @keyup.enter="downloadUrl" />
            <button class="btn small" :disabled="busy || !urlInput.trim()" @click="downloadUrl">
              {{ downloading ? '下载中…' : '下载' }}
            </button>
          </div>
          <p v-if="msg" class="cover-msg" :class="{ err: msgErr }">{{ msg }}</p>
        </div>
      </div>

      <!-- 裁剪编辑器：拖动选框选区域，右下角缩放，固定 2:3（封面展示比例） -->
      <div v-if="cropMode" class="crop-editor">
        <div class="crop-stage" ref="stageEl">
          <img
            ref="cropImg"
            :src="cropSrc"
            alt=""
            class="crop-img"
            draggable="false"
            @load="onCropImgLoad"
            @error="onCropImgError"
          />
          <template v-if="cropReady">
            <div
              v-for="(m, i) in masks"
              :key="i"
              class="crop-mask"
              :style="{ left: m.left + 'px', top: m.top + 'px', width: m.w + 'px', height: m.h + 'px' }"
            ></div>
            <div
              class="crop-rect"
              :style="{ left: rect.x + 'px', top: rect.y + 'px', width: rect.w + 'px', height: rect.h + 'px' }"
              @mousedown.prevent="startDrag"
            ></div>
            <div
              class="crop-handle"
              :style="{ left: rect.x + rect.w - 9 + 'px', top: rect.y + rect.h - 9 + 'px' }"
              @mousedown.prevent.stop="startResize"
            ></div>
          </template>
        </div>
        <div class="crop-side">
          <div class="crop-preview-label">预览（2:3）</div>
          <div class="crop-preview" v-if="cropReady">
            <div class="crop-preview-inner" :style="previewStyle"></div>
          </div>
          <div class="crop-tip">拖动选框选区域，右下角缩放；固定 2:3 比例，所有视图统一生效。</div>
          <div class="crop-btns">
            <button class="btn small" :disabled="cropping" @click="cropMode = false">取消</button>
            <button class="btn small primary" :disabled="cropping || !cropReady" @click="doCrop">
              {{ cropping ? '裁剪中…' : '✓ 应用裁剪' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 候选封面（VNDB/BGM/Steam 候选里的图） -->
      <div v-if="cands.length" class="cover-cands">
        <span class="dim">候选封面（点击选用）：</span>
        <img
          v-for="(c, i) in cands"
          :key="i"
          :src="c.cover_url"
          class="cover-cand"
          :title="(c.provider || '').toUpperCase() + ' · ' + (c.title || '')"
          v-imgfb="'🖼'"
          @click="useCand(c.cover_url)"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  gameId: { type: Number, required: true },
  title: { type: String, default: '' },
})
const emit = defineEmits(['close', 'done'])

const currentUrl = ref('')
const origUrl = ref('')        // 裁剪前原图（cover_orig_url），重新裁剪必须画在原图上
const cands = ref([])
const urlInput = ref('')
const busy = ref(false)
const downloading = ref(false)
const msg = ref('')
const msgErr = ref(false)

// ---- 裁剪状态 ----
const cropMode = ref(false)
const cropping = ref(false)
const cropSrc = ref('')
const hasCrop = ref(false)      // 有 cover_orig_path → 可重置
const cropReady = ref(false)
const stageEl = ref(null)
const cropImg = ref(null)
const rect = reactive({ x: 0, y: 0, w: 0, h: 0 })   // 显示像素坐标
const disp = reactive({ w: 0, h: 0 })                // 显示尺寸
const RATIO = 2 / 3                                  // 封面固定 2:3

function onKey(e) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => {
  window.addEventListener('keydown', onKey)
  loadGame()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  endDrag()
})

async function loadGame() {
  try {
    const g = await api.getGame(props.gameId)
    if (!g) return
    currentUrl.value = g.cover_url || ''
    origUrl.value = g.cover_orig_url || ''
    hasCrop.value = !!g.cover_orig_url
    cands.value = (g.candidates || [])
      .filter((c) => c.cover_url)
      .filter((c, i, arr) => arr.findIndex((x) => x.cover_url === c.cover_url) === i)
      .slice(0, 8)
  } catch (e) {
    showMsg(e.message || '加载失败', true)
  }
}

function showMsg(text, isErr = false) {
  msg.value = text
  msgErr.value = isErr
}

async function pickLocal() {
  if (busy.value) return
  busy.value = true
  msg.value = ''
  try {
    const r = await api.chooseCover(props.gameId)
    if (r && r.ok) {
      currentUrl.value = r.cover_url
      hasCrop.value = false
      cropMode.value = false
      showMsg('✅ 已更新封面')
      emit('done')
    } else {
      showMsg((r && r.error) || '未选择', true)
    }
  } catch (e) {
    showMsg(e.message || '选择失败', true)
  } finally {
    busy.value = false
  }
}

async function fromVndb() {
  if (busy.value) return
  busy.value = true
  msg.value = ''
  try {
    const r = await api.refreshCover(props.gameId)
    if (r && r.ok) {
      currentUrl.value = r.cover_url
      hasCrop.value = false
      cropMode.value = false
      showMsg('✅ 已从 VNDB 补封面')
      emit('done')
    } else {
      showMsg((r && r.error) || '补封面失败', true)
    }
  } catch (e) {
    showMsg(e.message || '补封面失败（超时或网络异常）', true)
  } finally {
    busy.value = false
  }
}

async function downloadUrl() {
  const url = urlInput.value.trim()
  if (!url || downloading.value) return
  downloading.value = true
  msg.value = ''
  try {
    const r = await api.setCoverUrl(props.gameId, url)
    if (r && r.ok) {
      currentUrl.value = r.cover_url
      hasCrop.value = false
      cropMode.value = false
      urlInput.value = ''
      showMsg('✅ 已下载封面')
      emit('done')
    } else {
      showMsg((r && r.error) || '下载失败', true)
    }
  } catch (e) {
    showMsg(e.message || '下载失败（超时或网络异常）', true)
  } finally {
    downloading.value = false
  }
}

async function useCand(url) {
  if (busy.value) return
  busy.value = true
  msg.value = ''
  try {
    const r = await api.setCoverUrl(props.gameId, url)
    if (r && r.ok) {
      currentUrl.value = r.cover_url
      hasCrop.value = false
      cropMode.value = false
      showMsg('✅ 已选用候选封面')
      emit('done')
    } else {
      showMsg((r && r.error) || '选用失败', true)
    }
  } catch (e) {
    showMsg(e.message || '选用失败', true)
  } finally {
    busy.value = false
  }
}

// ---- 裁剪 ----
function enterCrop() {
  // 编辑用原图（若已裁剪过则用裁剪前原图），保证选框画在完整图上。
  // 旧版始终用 currentUrl：二次裁剪时比例是相对原图算的，却画在已裁剪的
  // 小图上 → 裁出的区域整体偏移（v1.1 修）。
  cropSrc.value = (hasCrop.value && origUrl.value) || currentUrl.value
  cropMode.value = true
  cropReady.value = false
}

function onCropImgError() {
  cropReady.value = false
  showMsg('原图加载失败，无法裁剪', true)
}

function onCropImgLoad() {
  const img = cropImg.value
  if (!img || !img.naturalWidth || !stageEl.value) return
  const natW = img.naturalWidth
  const natH = img.naturalHeight
  // 显示尺寸：280 宽上限 / 340 高上限，保持原比例
  const scale = Math.min(280 / natW, 340 / natH, 1)
  disp.w = Math.round(natW * scale)
  disp.h = Math.round(natH * scale)
  // 初始选框：高 80%，宽按 2:3（超宽图则收窄）
  let h = Math.round(disp.h * 0.8)
  let w = Math.round(h * RATIO)
  if (w > disp.w) {
    w = disp.w
    h = Math.round(w / RATIO)
  }
  rect.x = Math.round((disp.w - w) / 2)
  rect.y = Math.round((disp.h - h) / 2)
  rect.w = w
  rect.h = h
  cropReady.value = true
}

// 遮罩：选框四周压暗
const masks = computed(() => {
  if (!cropReady.value) return []
  const t = rect.y
  const b = disp.h - (rect.y + rect.h)
  const l = rect.x
  const r = disp.w - (rect.x + rect.w)
  return [
    { top: 0, left: 0, w: disp.w, h: t },
    { top: rect.y + rect.h, left: 0, w: disp.w, h: b },
    { top: rect.y, left: 0, w: l, h: rect.h },
    { top: rect.y, left: rect.x + rect.w, w: r, h: rect.h },
  ]
})

// 预览：100×150 内用绝对定位 img 显示选框区域
const previewStyle = computed(() => {
  if (!cropReady.value) return {}
  return {
    width: (100 / (rect.w / disp.w)) + '%',
    height: (100 / (rect.h / disp.h)) + '%',
    left: (-(rect.x / disp.w) * 100 / (rect.w / disp.w)) + '%',
    top: (-(rect.y / disp.h) * 100 / (rect.h / disp.h)) + '%',
    backgroundImage: `url("${cropSrc.value}")`,
    backgroundSize: '100% 100%',
    backgroundRepeat: 'no-repeat',
  }
})

// ---- 拖拽/缩放（window 级监听，鼠标移出选框也不断） ----
let dragState = null

function startDrag(e) {
  dragState = { mode: 'move', sx: e.clientX, sy: e.clientY, ox: rect.x, oy: rect.y }
  window.addEventListener('mousemove', onDrag)
  window.addEventListener('mouseup', endDrag)
}

function startResize(e) {
  dragState = { mode: 'resize', sx: e.clientX, sy: e.clientY, ox: rect.x, oy: rect.y, ow: rect.w, oh: rect.h }
  window.addEventListener('mousemove', onDrag)
  window.addEventListener('mouseup', endDrag)
}

function onDrag(e) {
  if (!dragState || !cropReady.value) return
  const dx = e.clientX - dragState.sx
  const dy = e.clientY - dragState.sy
  if (dragState.mode === 'move') {
    rect.x = clamp(dragState.ox + dx, 0, disp.w - rect.w)
    rect.y = clamp(dragState.oy + dy, 0, disp.h - rect.h)
  } else {
    // 缩放：右下角，保持 2:3
    let h = clamp(dragState.oh + dy, 48, disp.h - dragState.oy)
    let w = Math.round(h * RATIO)
    if (w > disp.w - dragState.ox) {
      w = disp.w - dragState.ox
      h = Math.round(w / RATIO)
    }
    rect.w = w
    rect.h = h
  }
}

function endDrag() {
  window.removeEventListener('mousemove', onDrag)
  window.removeEventListener('mouseup', endDrag)
  dragState = null
}

function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v))
}

async function doCrop() {
  if (cropping.value || !cropReady.value) return
  cropping.value = true
  msg.value = ''
  try {
    // 显示像素 → 原图 0~1 比例
    const x = rect.x / disp.w
    const y = rect.y / disp.h
    const w = rect.w / disp.w
    const h = rect.h / disp.h
    const r = await api.setCoverCrop(props.gameId, x, y, w, h)
    if (r && r.ok) {
      currentUrl.value = r.cover_url
      hasCrop.value = true
      cropMode.value = false
      showMsg('✅ 已应用裁剪')
      emit('done')
    } else {
      showMsg((r && r.error) || '裁剪失败', true)
    }
  } catch (e) {
    showMsg(e.message || '裁剪失败（超时或网络异常）', true)
  } finally {
    cropping.value = false
  }
}

async function resetCrop() {
  if (busy.value) return
  busy.value = true
  msg.value = ''
  try {
    const r = await api.clearCoverCrop(props.gameId)
    if (r && r.ok) {
      currentUrl.value = r.cover_url
      hasCrop.value = false
      cropMode.value = false
      showMsg('✅ 已重置为自动适配（原图）')
      emit('done')
    } else {
      showMsg((r && r.error) || '重置失败', true)
    }
  } catch (e) {
    showMsg(e.message || '重置失败', true)
  } finally {
    busy.value = false
  }
}
</script>
