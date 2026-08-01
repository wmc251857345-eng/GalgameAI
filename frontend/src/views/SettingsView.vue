<template>
  <div class="view-page settings">
    <div class="library-head">
      <h1>设置</h1>
      <span class="count">{{ bridgeMode }}</span>
    </div>

    <div v-if="!cfg" class="loading">加载中…</div>

    <template v-else>
      <section class="card">
        <h2>AI 服务</h2>
        <div class="row">
          <label>提供商</label>
          <select v-model="cfg.provider.name">
            <option>gemini</option>
            <option>openai</option>
            <option>claude</option>
            <option>deepseek</option>
            <option>custom</option>
          </select>
        </div>
        <div class="row">
          <label>模型</label>
          <input v-model="cfg.provider.model" placeholder="如 gemini-2.5-pro / deepseek-chat" />
        </div>
        <div class="row">
          <label>API Key</label>
          <input v-model="cfg.provider.api_key" type="password" placeholder="••••••••••" />
        </div>
        <div class="row">
          <label>Base URL</label>
          <input v-model="cfg.provider.base_url" placeholder="可选，OpenAI 兼容地址" />
        </div>
        <p class="hint">能力提示：{{ providerHint }}</p>
      </section>

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
      </section>

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
import { api } from '../api.js'

const cfg = ref(null)
const saving = ref(false)
const saved = ref(false)
const bridgeMode = ref('')

const providerHint = computed(() => {
  const m = {
    gemini: '支持视觉 + 联网搜索（识别日文封面最佳）',
    openai: '支持视觉，搜索需 tool 调用',
    claude: '支持视觉，无搜索',
    deepseek: '文本模型、无视觉（视觉任务将降级到本地 OCR）',
    custom: 'OpenAI 兼容接口，能力按模型而定',
  }
  return m[cfg.value?.provider?.name] ?? ''
})

onMounted(async () => {
  const info = await api.getAppInfo()
  bridgeMode.value =
    info.platform === 'browser-mock'
      ? '浏览器预览模式（mock 数据，IPC 未接通）'
      : `已连接后端 (Python ${info.python})`
  cfg.value = await api.getConfig()
})

async function save() {
  saving.value = true
  try {
    await api.setConfig('provider', cfg.value.provider)
    await api.setConfig('proxy', cfg.value.proxy)
    await api.setConfig('analysis', cfg.value.analysis)
    saved.value = true
    setTimeout(() => (saved.value = false), 2000)
  } finally {
    saving.value = false
  }
}
</script>
