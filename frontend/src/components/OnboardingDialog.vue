<template>
  <div class="ob-overlay" v-if="visible">
    <div class="ob-panel">
      <button class="wd-close" @click="dismiss" title="稍后再说">✕</button>
      <h2 class="ob-title">👋 欢迎使用 GALA</h2>
      <p class="ob-sub">你的 Galgame 资料管家。开始之前，建议完成下面几步：</p>

      <div class="ob-steps">
        <div class="ob-step" :class="{ ok: st.has_roots }">
          <span class="ob-step-ico">{{ st.has_roots ? '✅' : '1️⃣' }}</span>
          <div>
            <div class="ob-step-t">添加游戏库目录</div>
            <div class="ob-step-d">
              <template v-if="st.has_roots">已配置，去「游戏库 → 扫描」即可入库</template>
              <template v-else>去「设置」添加存放游戏的硬盘目录（如 D:\Games）</template>
            </div>
          </div>
          <button v-if="st.has_roots" class="btn small" @click="goScan">去扫描</button>
          <button v-else class="btn small" @click="goSettings">去设置</button>
        </div>

        <div class="ob-step" :class="{ ok: st.has_keys }">
          <span class="ob-step-ico">{{ st.has_keys ? '✅' : '2️⃣' }}</span>
          <div>
            <div class="ob-step-t">配置 AI 管家（可选）</div>
            <div class="ob-step-d">
              <template v-if="st.has_keys">已配置，可直接对话补全资料/问推荐</template>
              <template v-else>填入 LLM API Key 后，管家能自动补全简介、识别游戏、推荐作品</template>
            </div>
          </div>
          <button v-if="!st.has_keys" class="btn small" @click="goSettings">去配置</button>
        </div>

        <div class="ob-step" :class="{ ok: st.total > 0 }">
          <span class="ob-step-ico">{{ st.total > 0 ? '✅' : '3️⃣' }}</span>
          <div>
            <div class="ob-step-t">扫描入库</div>
            <div class="ob-step-d">
              <template v-if="st.total > 0">库中已有 {{ st.total }} 部游戏</template>
              <template v-else>扫描完成后游戏自动入库，可逐个确认或批量分析</template>
            </div>
          </div>
        </div>
      </div>

      <div class="ob-actions">
        <button class="btn" @click="dismiss">稍后再说</button>
        <button class="btn primary" @click="finish">完成引导，开始使用</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api.js'
import { useLibraryStore } from '../stores/library.js'

const emit = defineEmits(['close'])
const store = useLibraryStore()
const visible = ref(false)
const st = reactive({ done: false, has_roots: false, has_keys: false, total: 0 })

onMounted(async () => {
  try {
    const r = await api.onboardingStatus()
    if (r && !r.done) {
      Object.assign(st, r)
      visible.value = true
    }
  } catch (e) { /* 桥接未就绪等异常：不打扰 */ }
})

function markDone() { api.onboardingComplete().catch(() => {}) }
function dismiss() { markDone(); emit('close') }
function finish() { markDone(); emit('close') }
function goSettings() { store.currentView = 'settings'; emit('close') }
function goScan() {
  store.currentView = 'library'
  store.loadRoots()
  setTimeout(() => store.startScan(), 300)
  emit('close')
}
</script>

<style scoped>
.ob-overlay {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(8, 10, 14, .82); backdrop-filter: blur(6px);
  display: flex; align-items: center; justify-content: center;
}
.ob-panel {
  width: 520px; max-width: 92vw;
  background: var(--bg-2, #161a22);
  border: 1px solid var(--border, #2a3040);
  border-radius: 14px; padding: 26px 28px; position: relative;
  box-shadow: 0 18px 60px rgba(0, 0, 0, .5);
}
.ob-title { margin: 0 0 6px; font-size: 20px; }
.ob-sub { color: var(--text-dim); font-size: 13px; margin: 0 0 18px; }
.ob-steps { display: flex; flex-direction: column; gap: 10px; }
.ob-step {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px; border-radius: 10px;
  background: rgba(255, 255, 255, .03); border: 1px solid var(--border, #2a3040);
}
.ob-step.ok { border-color: rgba(46, 204, 113, .35); }
.ob-step-ico { font-size: 18px; }
.ob-step-t { font-weight: 600; font-size: 13.5px; }
.ob-step-d { color: var(--text-dim); font-size: 12px; margin-top: 2px; }
.ob-step .btn { margin-left: auto; flex-shrink: 0; }
.ob-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
.wd-close { position: absolute; top: 14px; right: 16px; }
</style>
