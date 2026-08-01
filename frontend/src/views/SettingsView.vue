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
          <label>视觉（封面识别）</label>
          <input v-model="cfg.provider.vision" type="checkbox" />
          <span class="hint">把本地封面图发给 AI 辅助识别（需模型支持图像）</span>
        </div>
        <div class="row">
          <label>联网搜索</label>
          <input v-model="cfg.provider.search" type="checkbox" />
          <span class="hint">预留开关：AI 自带搜索能力</span>
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
        <div class="row" style="margin-top: 10px">
          <button class="btn small" :disabled="testing" @click="runTest">
            🔌 {{ testing ? '测试中…' : '测试连接' }}
          </button>
          <span v-if="connResult" class="conn-result">
            <span v-for="(v, k) in connResult" :key="k" class="conn-item" :class="connClass(v)">
              {{ connLabel[k] }}: {{ connText(v) }}
            </span>
          </span>
        </div>
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
            {{ store.scan.running ? '任务运行中…' : '🔍 扫描新游戏' }}
          </button>
          <button class="btn" :disabled="store.scan.running" @click="store.startAnalyze()">
            🤖 开始 AI 分析
          </button>
        </div>
        <div class="row" style="margin-top: 6px">
          <button class="btn small" :disabled="store.scan.running" @click="fillCovers">
            🖼 补齐缺失封面
          </button>
          <button class="btn small" @click="exportGames">📤 导出库 JSON</button>
          <button class="btn small" @click="backupDb">💾 备份数据库</button>
          <button class="btn small" @click="checkMissing">🔍 检查失效路径</button>
        </div>
        <div v-if="taskMsg" class="hint" style="margin-top: 8px">{{ taskMsg }}</div>
        <div v-if="store.scan.running" class="progress-card">
          <div class="progress-bar"><div class="progress-fill" :style="{ width: progressPct + '%' }"></div></div>
          <div class="progress-text">{{ stageLabel }}：{{ store.scan.current }}（{{ store.scan.done }}/{{ store.scan.total }}）</div>
          <div style="margin-top: 8px">
            <button class="btn small danger-soft" @click="cancelTask">■ 取消任务</button>
          </div>
        </div>
        <div v-if="store.missingPaths.length" class="missing-list">
          <div class="hint" style="margin-bottom: 6px">以下游戏 exe 已失效（移动/重命名过）：</div>
          <div v-for="m in store.missingPaths" :key="m.id" class="missing-row">
            <span class="missing-title">{{ m.title }}</span>
            <span class="missing-path">{{ m.exe_path || m.path }}</span>
            <button class="btn small" @click="relocateOne(m)">📂 重新定位</button>
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

      <!-- 备份 -->
      <section class="card">
        <h2>备份</h2>
        <div class="row">
          <label>启动时自动备份</label>
          <input v-model="cfg.backup.auto_enabled" type="checkbox" />
        </div>
        <div class="row">
          <label>备份间隔（天）</label>
          <input v-model.number="cfg.backup.interval_days" type="number" min="1" max="90" style="flex: 0 0 80px" />
        </div>
        <p class="hint">自动备份保存在 database/backup/auto_*，保留最近 10 份；手动备份按钮见上方。</p>
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
const taskMsg = ref('')
const testing = ref(false)
const connResult = ref(null)
const connLabel = { bgm: 'Bangumi', vndb: 'VNDB', llm: 'AI' }

const connClass = (v) => (v.ok === true ? 'ok' : v.ok === false ? 'fail' : 'skip')
const connText = (v) => {
  if (v.ok === true) return `✓ ${v.ms}ms`
  if (v.ok === false) return `✗ ${v.ms}ms${v.error ? ' ' + v.error : ''}`
  return v.note || '未配置'
}

const stageLabel = computed(
  () => ({ scan: '扫描', analyze: 'AI分析', covers: '补封面' }[store.scan.stage] || store.scan.stage),
)

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
  await store.loadMissing()
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

async function fillCovers() {
  await save()
  const r = await api.fillMissingCovers()
  if (r && !r.ok) alert(r.error)
  else {
    taskMsg.value = '正在补齐缺失封面…（进度见上方）'
    store.pollScan()
  }
}

async function exportGames() {
  const r = await api.exportGames()
  taskMsg.value = r?.ok ? `已导出 ${r.count} 个游戏 → ${r.path}` : (r?.error || '导出失败')
}

async function backupDb() {
  const r = await api.backupDb()
  taskMsg.value = r?.ok ? `备份完成 → ${r.path}` : (r?.error || '备份失败')
}

async function checkMissing() {
  await save()
  await store.loadMissing()
  taskMsg.value = store.missingPaths.length
    ? `发现 ${store.missingPaths.length} 个失效游戏，可在下方重新定位`
    : '所有游戏的 exe 路径均有效 ✓'
}

async function relocateOne(m) {
  if (await store.relocateGame(m.id)) {
    taskMsg.value = `已重新定位「${m.title}」`
  }
}

async function cancelTask() {
  await store.cancelTask()
  taskMsg.value = '已请求取消，当前任务将在下个循环点停止…'
}

async function runTest() {
  await save()
  testing.value = true
  try {
    connResult.value = await api.testConnection()
  } finally {
    testing.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await api.setConfig('provider', cfg.value.provider)
    await api.setConfig('proxy', cfg.value.proxy)
    await api.setConfig('analysis', cfg.value.analysis)
    await api.setConfig('backup', cfg.value.backup)
    await api.setConfig('vndb_token', cfg.value.vndb_token || '')
    saved.value = true
    setTimeout(() => (saved.value = false), 2000)
  } finally {
    saving.value = false
  }
}
</script>
