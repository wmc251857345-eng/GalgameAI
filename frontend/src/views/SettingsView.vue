<template>
  <div class="view-page settings">
    <div class="library-head">
      <h1>设置</h1>
      <span class="count">{{ bridgeMode }}</span>
    </div>

    <div v-if="!cfg" class="loading">加载中…</div>

    <template v-else>
      <!-- AI 服务 -->
      <section class="card">
        <h2>AI 服务</h2>
        <div class="row">
          <label>提供商</label>
          <select v-model="cfg.provider.name">
            <option>custom</option>
            <option>gemini</option>
            <option>openai</option>
            <option>claude</option>
            <option>deepseek</option>
          </select>
        </div>
        <div class="row">
          <label>模型</label>
          <input v-model="cfg.provider.model" placeholder="如 gcli-gemini-3-flash-preview-search" />
        </div>
        <div class="row">
          <label>API Key</label>
          <input v-model="cfg.provider.api_key" type="password" placeholder="••••••••••" />
        </div>
        <div class="row">
          <label>Base URL</label>
          <input v-model="cfg.provider.base_url" placeholder="OpenAI 兼容地址，如 https://xxx/v1" />
        </div>
        <div class="row">
          <label>VNDB Token</label>
          <input v-model="cfg.vndb_token" type="password" placeholder="可选，填了才有 VNDB 数据（时长/评分）" />
        </div>
        <p class="hint">能力提示：{{ providerHint }}</p>
      </section>

      <!-- 网络 -->
      <section class="card">
        <h2>网络</h2>
        <div class="row">
          <label>启用代理</label>
          <input v-model="cfg.proxy.enabled" type="checkbox" />
        </div>
        <div class="row">
          <label>代理地址</label>
          <input v-model="cfg.proxy.url" placeholder="http://127.0.0.1:7897" />
        </div>
        <p class="hint">代理仅用于 VNDB/AI 中转；Bangumi 走国内直连。</p>
      </section>

      <!-- 游戏库 -->
      <section class="card">
        <h2>游戏库目录</h2>
        <div v-for="r in store.roots" :key="r" class="root-row">
          <span class="root-path">📁 {{ r }}</span>
          <button class="btn small" @click="removeRoot(r)">移除</button>
        </div>
        <div v-if="!store.roots.length" class="dim">尚未添加目录</div>
        <div class="row add-root">
          <input v-model="newRoot" placeholder="如 D:\Games_HDD\GalGame" @keyup.enter="addRoot" />
          <button class="btn" @click="addRoot">添加</button>
        </div>
        <div class="row" style="margin-top: 14px">
          <button class="btn primary" :disabled="store.scan.running" @click="scan">
            {{ store.scan.running ? '扫描中…' : '🔍 扫描新游戏' }}
          </button>
          <button class="btn" :disabled="store.scan.running" @click="store.startAnalyze()">
            🤖 开始 AI 分析
          </button>
        </div>
        <div v-if="store.scan.running" class="progress-card">
          <div class="progress-bar"><div class="progress-fill" :style="{ width: progressPct + '%' }"></div></div>
          <div class="progress-text">{{ store.scan.stage === 'analyze' ? '分析' : '扫描' }}中：
            {{ store.scan.current }}（{{ store.scan.done }}/{{ store.scan.total }}）
          </div>
        </div>
        <div v-if="store.scan.log.length" class="progress-log">
          <div v-for="(l, i) in store.scan.log.slice(-8)" :key="i">{{ l }}</div>
        </div>
      </section>

      <!-- 分析参数 -->
      <section class="card">
        <h2>分析</h2>
        <div class="row">
          <label>自动确认阈值</label>
          <input v-model="cfg.analysis.auto_confirm_threshold" type="range" min="0.5" max="0.99" step="0.01" style="flex: 1" />
          <span style="width: 40px; text-align: right">{{ cfg.analysis.auto_confirm_threshold }}</span>
        </div>
        <div class="row">
          <label>并发数</label>
          <input v-model.number="cfg.analysis.concurrency" type="number" min="1" max="8" style="flex: 0 0 80px" />
        </div>
        <p class="hint">阈值越高越严格：≥阈值自动入库，否则进待确认。</p>
      </section>

      <div class="actions">
        <button class="btn primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存设置' }}
        </button>
        <span v-if="saved" class="saved-ok">✓ 已保存到 config/config.json</span>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'

const store = useLibraryStore()
const cfg = ref(null)
const saving = ref(false)
const saved = ref(false)
const bridgeMode = ref('')
const newRoot = ref('')

const providerHint = computed(() => {
  const m = {
    custom: 'OpenAI 兼容中转（Gemini/任意模型），按中转能力而定',
    gemini: '官方 Gemini，支持视觉 + 联网搜索',
    openai: '支持视觉，搜索需 tool 调用',
    claude: '支持视觉，无搜索',
    deepseek: '文本模型、无视觉（视觉降级到本地封面）',
  }
  return m[cfg.value?.provider?.name] ?? ''
})

const progressPct = computed(() => {
  const { total, done } = store.scan
  return total ? Math.round((done / total) * 100) : 0
})

onMounted(async () => {
  const info = await api.getAppInfo()
  bridgeMode.value =
    info.platform === 'browser-mock'
      ? '浏览器预览模式（mock 数据）'
      : `已连接后端 (Python ${info.python})`
  cfg.value = await api.getConfig()
  await store.loadRoots()
})

async function addRoot() {
  const p = newRoot.value.trim()
  if (!p) return
  const r = await api.addLibraryRoot(p)
  if (r && !r.ok) alert(r.error)
  else newRoot.value = ''
  await store.loadRoots()
}

async function removeRoot(p) {
  await api.removeLibraryRoot(p)
  await store.loadRoots()
}

async function scan() {
  await save()
  store.startScan()
}

async function save() {
  saving.value = true
  try {
    await api.setConfig('provider', cfg.value.provider)
    await api.setConfig('proxy', cfg.value.proxy)
    await api.setConfig('analysis', cfg.value.analysis)
    await api.setConfig('vndb_token', cfg.value.vndb_token || '')
    saved.value = true
    setTimeout(() => (saved.value = false), 2000)
  } finally {
    saving.value = false
  }
}
</script>
