<template>
  <div class="view-page chat-page">
    <div class="library-head">
      <h1>AI 管家</h1>
      <span class="count">库内百科、推荐、改资料，一句话搞定</span>
      <div class="head-actions">
        <button class="btn small" @click="store.chatClear()">🗑 清空对话</button>
      </div>
    </div>

    <!-- 布局：左侧上下文面板 + 右侧聊天区 -->
    <div class="chat-layout">
      <aside class="chat-side">
        <div class="chat-side-title">上下文游戏</div>
        <template v-if="store.chat.contextGame">
          <div class="ctx-card">
            <img
              v-if="store.chat.contextGame.cover_url"
              :src="store.chat.contextGame.cover_url"
              class="ctx-cover"
              v-imgfb="''"
              alt=""
            />
            <div v-else class="ctx-cover ctx-cover-empty">🎮</div>
            <div class="ctx-info">
              <div class="ctx-title">{{ store.chat.contextGame.title }}</div>
              <div class="ctx-meta">
                {{ store.chat.contextGame.maker || '未知厂商' }} ·
                {{ (store.chat.contextGame.released || '').slice(0, 4) || '—' }}
              </div>
              <div class="ctx-hint-inline">说「这个游戏」就是指它</div>
            </div>
            <button class="ctx-x" title="取消上下文" @click="store.setChatContext(null)">×</button>
          </div>
          <div class="ctx-quick">
            <button class="btn small" @click="qTitle">✏ 改标题</button>
            <button class="btn small" @click="qMaker">🏢 改厂商</button>
            <button class="btn small" @click="qCover">🖼 换封面</button>
            <button class="btn small" @click="qReanalyze">⟳ AI 补资料</button>
            <button class="btn small primary" @click="store.openDetail(store.chat.contextGame.id)">🔍 详情</button>
          </div>
        </template>
        <template v-else>
          <div class="ctx-search">
            <span class="ctx-search-icon">🔍</span>
            <input
              v-model="ctxQ"
              class="ctx-search-input"
              placeholder="搜索游戏设为上下文…"
              @keydown.enter.prevent="ctxFirst"
            />
          </div>
          <div v-if="ctxCands.length" class="ctx-drop">
            <div
              v-for="g in ctxCands"
              :key="g.id"
              class="ctx-drop-item"
              @click="store.setChatContext(g); ctxQ = ''"
            >
              <img v-if="g.cover_url" :src="g.cover_url" class="ctx-drop-cover" v-imgfb="''" alt="" />
              <div v-else class="ctx-drop-cover ctx-drop-empty">🎮</div>
              <div class="ctx-drop-info">
                <div class="ctx-drop-title">{{ g.title }}</div>
                <div class="ctx-drop-meta">{{ g.maker || '—' }} · {{ (g.released || '').slice(0, 4) || '—' }}</div>
              </div>
            </div>
          </div>
          <div v-if="!ctxCands.length && ctxQ" class="ctx-drop-empty">没有匹配的游戏</div>
          <p class="ctx-side-hint">选一个游戏后，可以说「这个游戏搞错了 / 推荐类似的」；或直接问管家任何问题。</p>
        </template>
      </aside>

      <div class="chat-main">

    <div class="chat-box" ref="chatBox">
      <div v-if="!store.chat.messages.length" class="chat-empty">
        <div class="chat-empty-icon">🤖</div>
        <p class="chat-empty-title">我是你的游戏库管家</p>
        <p class="chat-empty-sub">帮你找游戏、查资料，也能直接修改库里的条目</p>
        <ul class="chat-cap">
          <li><b>🎯 推荐</b> ——「推荐个纯爱 / 短时长 / 高分游戏」</li>
          <li><b>🔧 纠正</b> —— 先选游戏，说「这个游戏搞错了，应该叫 XX」</li>
          <li><b>📊 库管理</b> ——「库里有多少待确认的游戏？」</li>
          <li><b>📚 查资料</b> ——「Summer Pockets 是什么？」</li>
        </ul>
        <div class="chat-suggestions">
          <button v-for="s in suggestions" :key="s" class="chip-sug" @click="quick(s)">{{ s }}</button>
        </div>
      </div>

      <div v-for="(m, i) in store.chat.messages" :key="i" class="chat-msg" :class="[m.role, { error: m.error }]">
        <div class="chat-avatar">{{ m.role === 'user' ? '🙂' : '🤖' }}</div>
        <div class="chat-col">
          <div class="chat-bubble">
            <div v-if="m.actions && m.actions.length" class="chat-actions">
              <span v-for="(a, j) in m.actions" :key="j" class="chat-action" :class="{ done: a.summary }">
                {{ actionLabel(a) }}
                <button
                  v-if="a.undo && !a._undone"
                  class="chat-undo"
                  title="撤销此操作（回滚到执行前）"
                  @click.stop="undoAct(m, a)"
                >↩ 撤销</button>
              </span>
              <!-- 推荐/搜索结果 → 游戏卡片 -->
              <div v-for="(a, j) in m.actions" :key="'rec' + j" v-if="a.extra && a.extra.games" class="chat-rec">
                <div
                  v-for="gd in a.extra.games"
                  :key="gd.id"
                  class="chat-rec-card"
                  @click="store.openDetail(gd.id)"
                >
                  <img v-if="gd.cover_url" :src="gd.cover_url" class="chat-rec-cover" v-imgfb="''" alt="" />
                  <div v-else class="chat-rec-cover chat-rec-empty">🎮</div>
                  <div class="chat-rec-info">
                    <div class="chat-rec-title">{{ gd.title }}</div>
                    <div class="chat-rec-meta">
                      {{ gd.maker || '—' }} · {{ (gd.released || '').slice(0, 4) || '—' }}
                      <template v-if="gd.rating">· {{ gd.rating }} 分</template>
                    </div>
                    <div class="chat-rec-tags">
                      <span v-for="t in (gd.tags || []).slice(0, 4)" :key="t" class="chat-rec-tag">{{ t }}</span>
                      <span v-if="gd.playtime_hours" class="chat-rec-tag">{{ gd.playtime_hours }}h</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <img v-if="m.image" :src="m.image" class="chat-img" alt="聊天图片" />
            <div v-if="m.role === 'assistant' && !m.error" class="chat-text md-body" v-html="md(m.content)"></div>
            <div v-else class="chat-text">{{ m.content }}</div>
          </div>
          <div class="chat-meta">
            <span class="chat-time">{{ fmtTime(m.created_at) }}</span>
            <span v-if="m.error" class="chat-err">⚠ 出错了</span>
            <button v-if="m.role === 'assistant'" class="chat-op" title="复制回复" @click="copyMsg(m)">
              {{ m._copied ? '✓ 已复制' : '📋 复制' }}
            </button>
            <button v-if="m.error" class="chat-op chat-op-retry" @click="store.chatRetry()">↻ 重试</button>
          </div>
        </div>
      </div>

      <div v-if="store.chat.sending" class="chat-msg assistant">
        <div class="chat-avatar">🤖</div>
        <div class="chat-col">
          <div class="chat-bubble typing">
            <span class="typing-dots"><i></i><i></i><i></i></span>
            <span class="typing-text">{{ typingText }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="chat-input-row">
      <button class="chat-attach" title="发送图片（截图/预览图，管家识图认游戏）" @click="fileInput.click()">📎</button>
      <div class="chat-input-wrap">
        <div v-if="pickedImage" class="chat-img-preview">
          <img :src="pickedImage" alt="待发送图片" />
          <button class="chat-img-x" title="移除图片" @click="pickedImage = ''">×</button>
        </div>
        <textarea
          v-model="input"
          ref="inputEl"
          class="chat-input"
          rows="1"
          :placeholder="store.chat.contextGame ? `对《${store.chat.contextGame.title}》说什么？` : '想问管家什么？Enter 发送，Shift+Enter 换行'"
          :disabled="store.chat.sending"
          @keydown.enter.exact.prevent="send"
          @input="autoGrow"
        ></textarea>
      </div>
      <button class="btn primary chat-send-btn" :disabled="store.chat.sending || (!input.trim() && !pickedImage)" @click="send">
        {{ store.chat.sending ? '思考中…' : '➤ 发送' }}
      </button>
      <input ref="fileInput" type="file" accept="image/*" class="hidden-file" @change="onPickFile" />
    </div>
      </div><!-- /chat-main -->
    </div><!-- /chat-layout -->

    <!-- 快捷编辑表单（替代 prompt 弹窗） -->
    <div v-if="editOpen" class="wd-overlay" @click.self="editOpen = false">
      <div class="wd-panel fixer-panel" style="max-width: 460px">
        <button class="wd-close" @click="editOpen = false">✕</button>
        <h2 class="fixer-title">{{ editTitle }}</h2>
        <input
          v-model="editVal"
          class="fixer-search chat-input"
          :placeholder="editPlaceholder"
          autofocus
          @keydown.enter="editOk"
        />
        <div class="edit-actions">
          <button class="btn" @click="editOpen = false">取消</button>
          <button class="btn primary" @click="editOk">确定</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'
import { md, mdPlain } from '../utils/md.js'

const store = useLibraryStore()
const input = ref('')
const chatBox = ref(null)
const inputEl = ref(null)
const ctxQ = ref('')
const fileInput = ref(null)
const pickedImage = ref('')

const suggestions = [
  '推荐一个纯爱故事的游戏',
  '最近玩过哪些游戏？',
  '库里有多少个游戏？',
]

// ---- 思考中动态文案 ----
const typingSteps = ['正在理解你的问题…', '正在搜索游戏库…', '正在整理资料…', '正在生成回复…']
const typingText = ref(typingSteps[0])
let typingTimer = null
watch(
  () => store.chat.sending,
  (v) => {
    if (typingTimer) { clearInterval(typingTimer); typingTimer = null }
    if (v) {
      let i = 0
      typingText.value = typingSteps[0]
      typingTimer = setInterval(() => {
        i = (i + 1) % typingSteps.length
        typingText.value = typingSteps[i]
      }, 2600)
    }
  },
)
onBeforeUnmount(() => { if (typingTimer) clearInterval(typingTimer) })

// 上下文候选：按输入过滤本地库（空输入不弹出，避免遮挡聊天区）
const ctxCands = computed(() => {
  const q = ctxQ.value.trim().toLowerCase()
  if (!q) return []
  let list = store.games
  list = list.filter((g) =>
    (g.title || '').toLowerCase().includes(q) ||
    (g.title_jp || '').toLowerCase().includes(q) ||
    (g.title_zh || '').toLowerCase().includes(q) ||
    (g.maker || '').toLowerCase().includes(q))
  return list.slice(0, 8)
})

function ctxFirst() {
  if (ctxCands.value.length) {
    store.setChatContext(ctxCands.value[0])
    ctxQ.value = ''
  }
}

watch(
  () => store.chat.messages.length + store.chat.sending,
  async () => {
    await nextTick()
    if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
  },
)

function autoGrow() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function send() {
  const text = input.value.trim()
  const img = pickedImage.value
  if ((!text && !img) || store.chat.sending) return
  input.value = ''
  pickedImage.value = ''
  if (inputEl.value) inputEl.value.style.height = 'auto'
  store.chatSend(text, img)
}

// ---- 图片发送（识图认游戏） ----
function onPickFile(e) {
  const f = e.target.files && e.target.files[0]
  e.target.value = ''  // 允许重复选择同一文件
  if (!f) return
  fileToDataURL(f).then((d) => { pickedImage.value = d }).catch(() => alert('图片读取失败，请换一张'))
}

function fileToDataURL(file, maxW = 1280, quality = 0.85) {
  // 压缩成 data URL（限制宽度 + JPEG），避免超大原图直接塞进 LLM 请求
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const img = new Image()
      img.onload = () => {
        let w = img.width, h = img.height
        if (w > maxW) { h = Math.round(h * maxW / w); w = maxW }
        const c = document.createElement('canvas')
        c.width = w; c.height = h
        c.getContext('2d').drawImage(img, 0, 0, w, h)
        resolve(c.toDataURL('image/jpeg', quality))
      }
      img.onerror = () => reject(new Error('图片解码失败'))
      img.src = reader.result
    }
    reader.onerror = () => reject(new Error('文件读取失败'))
    reader.readAsDataURL(file)
  })
}

function quick(s) {
  input.value = s
  send()
}

// ---- 工具动作展示 ----
const ACTION_NAMES = {
  search_games: '搜索游戏库', get_game: '查游戏资料', get_library_stats: '统计库',
  list_facets: '查筛选维度', search_providers: '搜外部资料', correct_game: '修正资料',
  update_game_info: '更新资料', set_game_cover: '换封面', reanalyze_game: 'AI 补资料',
  import_game: '导入游戏', list_makers: '厂商列表', merge_makers: '合并厂商',
}
function actionLabel(a) {
  return (a.summary ? '✓ ' : '🔧 ') + (ACTION_NAMES[a.name] || a.name)
}

// ---- 撤销 AI 操作（回滚） ----
async function undoAct(m, a) {
  const r = await api.undoAction(a.undo)
  if (r && r.ok) {
    a._undone = true
    a.summary = '已撤销'
    await store.load()          // 刷新库：标题/封面等立刻反映
    if (store.chat.contextGame && r.game_id === store.chat.contextGame.id) {
      store.openDetail(r.game_id)  // 上下文是这游戏 → 刷新详情
    }
  } else {
    alert((r && r.error) || '撤销失败')
  }
}

// ---- 时间 / 复制 ----
function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  const now = new Date()
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return d.toDateString() === now.toDateString()
    ? hm
    : `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`
}

async function copyMsg(m) {
  const text = mdPlain(m.content)
  let done = false
  try {
    // clipboard API 在部分环境(权限/挂起)不可靠 → 800ms 超时保护
    await Promise.race([
      navigator.clipboard.writeText(text),
      new Promise((_, rej) => setTimeout(() => rej(new Error('clipboard timeout')), 800)),
    ])
    done = true
  } catch { /* 走 fallback */ }
  if (!done) {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    } catch { /* 乐观反馈：绝大多数桌面环境可成功 */ }
  }
  m._copied = true
  setTimeout(() => { m._copied = false }, 1500)
}

// ---- 上下文快捷操作（直接改库，不走聊天） ----
function ctxGame() {
  return store.chat.contextGame
}

// 通用编辑表单（替代 prompt()：带取消/回车确认）
const editOpen = ref(false)
const editTitle = ref('')
const editPlaceholder = ref('')
const editVal = ref('')
let editCb = null
function openEdit(title, placeholder, initial, cb) {
  editTitle.value = title
  editPlaceholder.value = placeholder
  editVal.value = initial || ''
  editCb = cb
  editOpen.value = true
}
async function editOk() {
  const cb = editCb
  editCb = null
  editOpen.value = false
  if (cb) await cb(editVal.value.trim())
}

async function qTitle() {
  const g = ctxGame()
  if (!g) return
  openEdit(`《${g.title}》的新标题（或中文名）`, '输入新标题', g.title, async (v) => {
    if (!v) return
    const r = await store.quickUpdateGame(g.id, { title: v })
    if (r && !r.ok) alert(r.error || '修改失败')
    else {
      g.title = v
      await store.load()
    }
  })
}
async function qMaker() {
  const g = ctxGame()
  if (!g) return
  openEdit(`《${g.title}》的厂商`, '输入厂商名（如 Eushully）', g.maker || '', async (v) => {
    if (!v) return
    const r = await store.quickUpdateGame(g.id, { maker: v })
    if (r && !r.ok) alert(r.error || '修改失败')
    else {
      g.maker = v
      await store.load()
    }
  })
}
async function qCover() {
  const g = ctxGame()
  if (!g) return
  const r = await api.chooseCover(g.id)
  if (r && !r.ok) alert(r.error || '换封面失败')
  else {
    await store.load()
    if (store.chat.contextGame) {
      store.chat.contextGame.cover_url = r?.cover_url || store.chat.contextGame.cover_url
    }
  }
}
async function qReanalyze() {
  const g = ctxGame()
  if (!g) return
  const r = await api.reanalyzeGame(g.id)
  if (r && !r.ok) alert(r.error || '启动失败')
  else alert('已触发后台 AI 补全资料，稍候刷新可见')
}
</script>
