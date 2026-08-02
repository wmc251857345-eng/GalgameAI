<template>
  <div class="view-page chat-page">
    <div class="library-head">
      <h1>AI 管家</h1>
      <span class="count">可以聊库里的任何事，也可以让它直接改资料</span>
      <div class="head-actions">
        <button class="btn small" @click="store.chatClear()">🗑 清空对话</button>
      </div>
    </div>

    <!-- 上下文游戏选择器：从本地库选游戏，说话不用找序号 -->
    <div class="ctx-picker">
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
            <div class="ctx-hint">现在说「这个游戏…」就是指它</div>
          </div>
          <button class="ctx-x" title="取消上下文" @click="store.setChatContext(null)">×</button>
        </div>
        <div class="ctx-quick">
          <button class="btn small" @click="qTitle">✏ 改标题</button>
          <button class="btn small" @click="qMaker">🏢 改厂商</button>
          <button class="btn small" @click="qCover">🖼 换封面</button>
          <button class="btn small" @click="qReanalyze">⟳ AI 补资料</button>
          <button class="btn small" @click="store.openDetail(store.chat.contextGame.id)">🔍 详情</button>
        </div>
      </template>

      <template v-else>
        <div class="ctx-search">
          <span class="ctx-search-icon">🔍</span>
          <input
            v-model="ctxQ"
            class="ctx-search-input"
            placeholder="选一个游戏作为聊天上下文（说「这个游戏」就不用找序号）…"
          />
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
            <div v-if="!ctxCands.length && ctxQ" class="ctx-drop-empty">没有匹配的游戏</div>
          </div>
        </div>
        <div class="ctx-hint">没选也行，直接说要找哪个游戏，管家会自己搜库。</div>
      </template>
    </div>

    <div class="chat-box" ref="chatBox">
      <div v-if="!store.chat.messages.length" class="chat-empty">
        <div class="chat-empty-icon">💬</div>
        <p>我是你的游戏库管家，可以：</p>
        <ul class="chat-cap">
          <li>🔧 纠正错误条目 —— 先在上面选游戏，然后说「这个游戏搞错了，应该叫 XX」</li>
          <li>🎯 按口味推荐 ——「推荐个纯爱/短时长/高分游戏」</li>
          <li>📊 库管理 ——「库里有多少待确认的游戏？」</li>
          <li>📚 查资料 ——「帮我查一下 Summer Pockets 是什么」</li>
          <li>➕ 导入 —— 库页点「＋ 导入游戏」，选本地 exe + 描述，AI 自动补全</li>
        </ul>
        <div class="chat-suggestions">
          <button v-for="s in suggestions" :key="s" class="btn small" @click="quick(s)">{{ s }}</button>
        </div>
      </div>

      <div v-for="(m, i) in store.chat.messages" :key="i" class="chat-msg" :class="m.role">
        <div class="chat-avatar">{{ m.role === 'user' ? '🙂' : '🤖' }}</div>
        <div class="chat-bubble">
          <div v-if="m.actions && m.actions.length" class="chat-actions">
            <span v-for="(a, j) in m.actions" :key="j" class="chat-action" :class="{ done: a.summary }">
              {{ a.summary || '🔧 ' + a.name }}
            </span>
          </div>
          <div class="chat-text">{{ m.content }}</div>
        </div>
      </div>

      <div v-if="store.chat.sending" class="chat-msg assistant">
        <div class="chat-avatar">🤖</div>
        <div class="chat-bubble typing">管家思考中<span class="dots"></span></div>
      </div>
    </div>

    <div class="chat-input-row">
      <input
        v-model="input"
        class="chat-input"
        :placeholder="store.chat.contextGame ? `对《${store.chat.contextGame.title}》说什么？` : '例如：推荐一个纯爱游戏 · 这个游戏搞错了，应该叫XX'"
        :disabled="store.chat.sending"
        @keyup.enter="send"
      />
      <button class="btn primary" :disabled="store.chat.sending || !input.trim()" @click="send">
        {{ store.chat.sending ? '思考中…' : '发送' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'

const store = useLibraryStore()
const input = ref('')
const chatBox = ref(null)
const ctxQ = ref('')

const suggestions = [
  '推荐一个纯爱故事的游戏',
  '最近玩过哪些游戏？',
  '库里有多少个游戏？',
]

// 上下文候选：按输入过滤本地库
const ctxCands = computed(() => {
  const q = ctxQ.value.trim().toLowerCase()
  let list = store.games
  if (q) {
    list = list.filter((g) =>
      (g.title || '').toLowerCase().includes(q) ||
      (g.title_jp || '').toLowerCase().includes(q) ||
      (g.title_zh || '').toLowerCase().includes(q) ||
      (g.maker || '').toLowerCase().includes(q))
  }
  return list.slice(0, 8)
})

watch(
  () => store.chat.messages.length + store.chat.sending,
  async () => {
    await nextTick()
    if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
  },
)

function send() {
  const text = input.value.trim()
  if (!text || store.chat.sending) return
  input.value = ''
  store.chatSend(text)
}

function quick(s) {
  input.value = s
  send()
}

// ---- 上下文快捷操作（直接改库，不走聊天） ----
function ctxGame() {
  return store.chat.contextGame
}
async function qTitle() {
  const g = ctxGame()
  if (!g) return
  const v = prompt(`《${g.title}》的新标题（或中文名）：`, g.title)
  if (!v || !v.trim()) return
  const r = await store.quickUpdateGame(g.id, { title: v.trim() })
  if (r && !r.ok) alert(r.error || '修改失败')
  else g.title = v.trim()
}
async function qMaker() {
  const g = ctxGame()
  if (!g) return
  const v = prompt(`《${g.title}》的厂商：`, g.maker || '')
  if (v === null) return
  const r = await store.quickUpdateGame(g.id, { maker: v.trim() })
  if (r && !r.ok) alert(r.error || '修改失败')
  else g.maker = v.trim()
}
async function qCover() {
  const g = ctxGame()
  if (!g) return
  const v = prompt(`《${g.title}》封面图片 URL：`, '')
  if (!v || !v.trim()) return
  const r = await api.setCoverUrl(g.id, v.trim())
  if (r && !r.ok) alert(r.error || '换封面失败')
  else {
    await store.load()
    alert('封面已更新')
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
