<template>
  <div class="view-page chat-page">
    <div class="library-head">
      <h1>AI 管家</h1>
      <span class="count">问它库里的任何问题，或纠正它记错的信息</span>
      <div class="head-actions">
        <button class="btn small" @click="store.chatClear()">🗑 清空对话</button>
      </div>
    </div>

    <div v-if="store.chat.contextGame" class="ctx-chip">
      🎮 上下文：<b>{{ store.chat.contextGame.title }}</b>
      <button class="tag-x" title="取消附带" @click="store.setChatContext(null)">×</button>
    </div>

    <div class="chat-box" ref="chatBox">
      <div v-if="!store.chat.messages.length" class="chat-empty">
        <div class="chat-empty-icon">💬</div>
        <p>我是你的游戏库管家，可以：</p>
        <ul class="chat-cap">
          <li>🔧 纠正错误条目 ——「这个游戏搞错了，应该叫 XX，厂商是 XX」</li>
          <li>🎯 按口味推荐 ——「推荐个纯爱/短时长/高分游戏」</li>
          <li>📊 库管理 ——「库里有多少待确认的游戏？」</li>
          <li>📚 查资料 ——「帮我查一下 Summer Pockets 是什么」</li>
        </ul>
        <div class="chat-suggestions">
          <button v-for="s in suggestions" :key="s" class="btn small" @click="quick(s)">{{ s }}</button>
        </div>
      </div>

      <div v-for="(m, i) in store.chat.messages" :key="i" class="chat-msg" :class="m.role">
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
        <div class="chat-bubble typing">管家思考中<span class="dots"></span></div>
      </div>
    </div>

    <div class="chat-input-row">
      <input
        v-model="input"
        class="chat-input"
        placeholder="例如：推荐一个纯爱游戏 · 这个游戏搞错了，应该叫XX"
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
import { nextTick, ref, watch } from 'vue'
import { useLibraryStore } from '../stores/library.js'

const store = useLibraryStore()
const input = ref('')
const chatBox = ref(null)

const suggestions = [
  '推荐一个纯爱故事的游戏',
  '最近玩过哪些游戏？',
  '库里有多少个游戏？',
]

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
</script>
