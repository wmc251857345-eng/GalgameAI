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
        <h3 class="card-sub">当前提供商（优先使用，失败/限速自动切换）</h3>
        <div class="row">
          <label>名称</label>
          <input v-model="cfg.provider.name" placeholder="如 catiecli / ggchan" />
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

        <h3 class="card-sub" style="margin-top: 16px">提供商池（轮询：当前失败/限速 → 自动切下一个）</h3>
        <div v-if="providerPool.length" class="prov-list">
          <div v-for="(p, i) in providerPool" :key="p.name + '_' + i" class="prov-row">
            <input v-model="p.name" class="prov-in prov-name" placeholder="名称" :title="p.name === cfg.provider.name ? '当前活动' : ''" />
            <input v-model="p.model" class="prov-in prov-model" placeholder="模型" />
            <input v-model="p.base_url" class="prov-in prov-url" placeholder="Base URL" />
            <input v-model="p.api_key" type="password" class="prov-in prov-key" placeholder="API Key" />
            <label class="prov-enable" title="启用后才参与轮询">
              <input type="checkbox" v-model="p.enabled" />启用
            </label>
            <button class="btn small" :disabled="p.name === cfg.provider.name" @click="setActive(p)">设为当前</button>
            <button class="btn small" :disabled="testing" @click="testProv(p)">测试</button>
            <button class="btn small danger-soft" @click="removeProv(i)">删除</button>
          </div>
        </div>
        <div v-else class="dim" style="margin: 6px 0">暂无池内提供商，可添加（当前提供商会在保存时自动入池）</div>
        <div class="row" style="margin-top: 8px">
          <button class="btn small" @click="addProv">➕ 添加提供商</button>
          <span v-if="provTest" class="conn-result">
            <span v-for="(v, k) in provTest" :key="k" class="conn-item"
                  :class="v.ok === true ? 'ok' : v.ok === false ? 'fail' : 'skip'">
              {{ k }}: {{ v.ok === true ? '✓ ' + v.ms + 'ms' : (v.ok === false ? '✗ ' + (v.error || '') : (v.note || '未测试')) }}
            </span>
          </span>
        </div>
        <div class="row" style="margin-top: 12px">
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

      <!-- 转区启动 -->
      <section class="card">
        <h2>转区启动（Locale Emulator）</h2>
        <div class="row">
          <label>LEProc.exe 路径</label>
          <input v-model="cfg.locale_emulator.path" placeholder="留空=自动探测 G:\tools\LocaleEmulator" />
        </div>
        <p class="hint">
          游戏详情页可给每款游戏选「转区运行」（如日文 ja-JP）；不选则直接启动。
          需要 LE 已安装（LEProc.exe + LEConfig.xml 同目录）。
        </p>
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
        <div v-if="store.lastScan" class="scan-result">
          <div class="scan-result-head">
            <span v-if="store.lastScan.new_count > 0">🆕 本次扫描新增 {{ store.lastScan.new_count }} 款游戏</span>
            <span v-else>✓ 扫描完成，无新增游戏</span>
            <span class="scan-result-meta" v-if="store.lastScan.missing_count > 0">
              另有 {{ store.lastScan.missing_count }} 个失效路径
            </span>
            <button class="btn small" style="margin-left: auto" @click="store.lastScan = null">✕</button>
          </div>
          <div v-if="store.lastScan.new_count > 0" class="scan-result-list">
            <span v-for="ng in store.lastScan.new_games.slice(0, 6)" :key="ng.id" class="scan-result-item">
              {{ ng.title }}<i class="scan-result-status" :class="'s' + ng.status">{{
                ng.status === 2 ? '已入库' : (ng.status === 1 ? '待确认' : '扫描到') }}</i>
            </span>
            <span v-if="store.lastScan.new_count > 6" class="dim">…等 {{ store.lastScan.new_count }} 款</span>
          </div>
          <div style="margin-top: 8px" v-if="store.lastScan.new_count > 0">
            <button class="btn small primary" @click="store.currentView = 'pending'">📋 去待确认列表</button>
          </div>
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

      <!-- 目录自动整理 -->
      <section class="card">
        <h2>📂 目录自动整理</h2>
        <p class="hint">按你的整理习惯（品牌桶 + Uncategorized 兜底），把散落在库根/【PC】包装层的新游戏移入对应桶目录。
          引擎会从现有目录结构学习厂商→桶映射（如 Atelier_Kaguya 桶），不会为每个厂商乱建新桶。</p>
        <div class="row" style="margin-top: 10px">
          <button class="btn primary" :disabled="store.organize.applying" @click="store.generateOrganizePlan()">
            🔍 {{ store.organize.applying ? '处理中…' : '生成整理计划' }}
          </button>
          <button class="btn small" @click="store.loadOrganizeHistory()">🕘 整理历史</button>
        </div>
        <p v-if="store.organize.error" class="error-text" style="margin-top: 8px">⚠ {{ store.organize.error }}</p>

        <!-- 整理计划（dry-run 待确认列表） -->
        <div v-if="store.organize.plan && store.organize.plan.length" style="margin-top: 12px">
          <div class="hint" style="margin-bottom: 6px">
            发现 {{ store.organize.plan.length }} 个未整理的游戏（勾选后一键执行，全部同盘移动，可安全预览）：
          </div>
          <div class="organize-plan">
            <label v-for="it in store.organize.plan" :key="it.game_id" class="organize-item">
              <input type="checkbox" v-model="it.selected" />
              <span class="organize-title">{{ it.title }}</span>
              <span class="organize-maker" v-if="it.maker">{{ it.maker }}</span>
              <span class="organize-arrow">→</span>
              <code class="organize-to">{{ it.to }}</code>
              <span class="scan-result-status" :class="it.reason.startsWith('包装') ? 's0' : 's1'">{{ it.reason }}</span>
            </label>
          </div>
          <div class="row" style="margin-top: 10px">
            <button class="btn primary" :disabled="store.organize.applying"
                    @click="store.applyOrganizePlan(store.organize.plan.filter(x => x.selected))">
              ✅ 执行所选整理（{{ store.organize.plan.filter(x => x.selected).length }} 项）
            </button>
            <button class="btn" :disabled="store.organize.applying" @click="store.organize.plan = null">取消</button>
          </div>
        </div>
        <div v-else-if="store.organize.plan && !store.organize.plan.length" class="hint" style="margin-top: 8px">
          ✓ 没有需要整理的游戏，目录结构已经很整洁。
        </div>

        <!-- 执行结果 -->
        <div v-if="store.organize.results && store.organize.results.length" class="organize-results" style="margin-top: 12px">
          <div v-for="r in store.organize.results" :key="r.game_id" class="organize-result"
               :class="r.ok ? 'ok' : 'fail'">
            {{ r.ok ? '✅' : '❌' }} {{ r.title || ('#' + r.game_id) }}
            <span v-if="r.ok && r.moved">: {{ r.from }} → {{ r.to }}</span>
            <span v-else-if="r.ok && !r.moved">: {{ r.note || '无需移动' }}</span>
            <span v-else>: {{ r.error }}</span>
          </div>
        </div>

        <!-- 整理历史 -->
        <div v-if="store.organize.history.length" class="organize-history" style="margin-top: 12px">
          <div class="hint" style="margin-bottom: 6px">最近整理记录（{{ store.organize.history.length }} 条）：</div>
          <div v-for="h in store.organize.history.slice(0, 8)" :key="h.id" class="organize-result" :class="h.ok ? 'ok' : 'fail'">
            {{ h.ok ? '✅' : '❌' }} {{ h.title }}: {{ h.from_path }} → {{ h.to_path }}
            <span class="dim" style="margin-left: 8px">{{ h.moved_at }}</span>
          </div>
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

      <!-- 关于与更新（v1.1） -->
      <section class="card" id="about-update">
        <h2>关于与更新</h2>
        <div class="row" style="align-items: center">
          <span>当前版本 <b>v{{ updCurrent }}</b><span v-if="updGit" class="dim"> · {{ updGit }}</span></span>
          <button class="btn small" :disabled="store.update.checking" @click="doCheckUpdate">
            {{ store.update.checking ? '检查中…' : '🔄 检查更新' }}
          </button>
        </div>
        <p v-if="updateMsg" class="hint" :class="{ 'upd-new': hasUpdate }">{{ updateMsg }}</p>
        <p v-if="hasUpdate" class="hint">
          升级方法：下载新版压缩包，解压覆盖（或并排放置）——数据库、封面、存档备份、配置全在
          exe 旁边的目录里，不会被覆盖丢失。
        </p>
      </section>

      <!-- 备份 -->
      <section class="card">
        <h2>存档备份（ludusavi 引擎）</h2>
        <div class="row">
          <label>引擎路径</label>
          <input v-model="bkEnginePath" placeholder="如 G:\tools\ludusavi-master\ludusavi.exe（留空自动探测）" style="flex: 1" />
          <button class="btn small" @click="probeEngine">🔍 探测</button>
        </div>
        <div v-if="bkStatus" class="bk-status" :class="bkStatus.ok ? 'ok' : 'fail'">
          {{ bkStatus.ok ? `✓ 引擎就绪：${bkStatus.engine_path}` : `✗ ${bkStatus.error}` }}
        </div>
        <div v-if="bkNeverBackedUp" class="bk-status fail" style="margin-top: 8px">
          ⚠️ 存档备份从未执行过：请先在「某款游戏详情页 → 备份」为该游戏配置存档路径，
          再点下方「☁ 立即备份全部存档」才会真正备份存档（"备份数据库"只备份资料库，不包含存档）。
        </div>

        <h3 class="card-sub" style="margin-top: 14px">备份目标（可多选 = 双线/多线备份）</h3>
        <div v-for="t in bkTargets" :key="t.path" class="bk-target-row">
          <input
            type="checkbox"
            :checked="t.enabled"
            @change="toggleTarget(t)"
          />
          <span class="bk-target-kind">{{ kindLabel(t.kind) }}</span>
          <span class="bk-target-path" :title="t.path">{{ t.path }}</span>
          <span v-if="t.free_gb" class="bk-target-free">{{ t.free_gb }} GB 可用</span>
          <span v-if="!t.exists" class="bk-target-missing">（目录不存在）</span>
        </div>
        <div class="row" style="margin-top: 8px">
          <input v-model="newTargetPath" placeholder="添加自定义备份目录，如 I:\GALABackup" style="flex: 1" @keyup.enter="addTarget" />
          <button class="btn small" @click="addTarget">添加</button>
        </div>

        <h3 class="card-sub" style="margin-top: 14px">自动备份</h3>
        <div class="row">
          <label>启动时自动备份</label>
          <input v-model="cfg.backup.auto_enabled" type="checkbox" />
        </div>
        <div class="row">
          <label>关闭游戏时自动备份存档</label>
          <input v-model="cfg.backup.auto_backup_on_close" type="checkbox" />
          <span class="dim" style="font-size: 12px">从 GALA 启动的游戏退出后，存档自动保存为版本快照（可随时回滚）</span>
        </div>
        <div class="row">
          <label>备份间隔（天）</label>
          <input v-model.number="cfg.backup.interval_days" type="number" min="1" max="90" style="flex: 0 0 80px" />
        </div>
        <div v-if="snapRoot" class="row">
          <label>快照目录</label>
          <span class="bk-target-path" style="font-size: 12px" :title="snapRoot">{{ snapRoot }}</span>
          <span class="dim" style="font-size: 12px">（按游戏名分类，每游戏保留 {{ snapKeep }} 份）</span>
        </div>
        <div class="row" style="margin-top: 10px">
          <button class="btn primary" :disabled="bkBusy" @click="backupAllNow">
            {{ bkBusy ? '备份中…' : '☁ 立即备份全部存档' }}
          </button>
          <button class="btn small" @click="bkRefresh">🔄 刷新状态</button>
        </div>
        <div v-if="bkResult" class="bk-status">
          <div v-for="(t, i) in bkResult.targets || []" :key="i" :class="t.ok ? 'ok' : 'fail'">
            {{ t.label }}：{{ t.ok ? `✓ ${t.overall?.processedGames || 0} 款游戏` : `✗ ${t.error}` }}
          </div>
        </div>
        <p class="hint" style="margin-top: 8px">
          数据库备份保留最近 10 份在 database/backup/auto_*；存档备份写入上述目标（增量：未变化文件自动跳过）。
        </p>
      </section>

      <div class="actions">
        <button class="btn primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存设置' }}
        </button>
        <button class="btn" @click="showLog">📋 查看日志</button>
        <span v-if="saved" class="saved-ok">✓ 已保存到 config/config.json</span>
      </div>
    </template>

    <!-- 日志弹层 -->
    <div v-if="logOpen" class="wd-overlay" @click.self="logOpen = false">
      <div class="wd-panel log-panel">
        <button class="wd-close" @click="logOpen = false">✕</button>
        <h2 class="fixer-title">📋 日志（logs/app.log 尾部）</h2>
        <p class="dim" style="font-size: 12px; margin-bottom: 8px">
          卡死/报错时查看这里：红色 ERROR 行即异常原因（前端 JS 错误也会自动上报到这里）。
        </p>
        <textarea class="log-view" readonly :value="logText" spellcheck="false"></textarea>
        <div class="row" style="margin-top: 10px">
          <button class="btn small" @click="refreshLog">🔄 刷新</button>
          <button class="btn small" @click="copyLog">📄 复制</button>
        </div>
      </div>
    </div>
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
const provTest = ref(null)
const connLabel = { bgm: 'Bangumi', vndb: 'VNDB', llm: 'AI' }

// ---- 日志查看 ----
const logOpen = ref(false)
const logText = ref('')

async function showLog() {
  logOpen.value = true
  await refreshLog()
}

async function refreshLog() {
  const r = await api.getLogTail(300)
  logText.value = (r && r.ok && r.log) || (r && r.error) || '加载失败'
}

async function copyLog() {
  try {
    await navigator.clipboard.writeText(logText.value)
    alert('已复制到剪贴板')
  } catch (e) {
    alert('复制失败，请手动选择文本复制')
  }
}

const providerPool = computed(() => {
  if (!cfg.value) return []
  const pool = cfg.value.providers || []
  return pool.length ? pool : [cfg.value.provider]
})

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

const appBuildInfo = ref(null)

onMounted(async () => {
  try {
    const info = await api.getAppInfo()
    appBuildInfo.value = info.build || null
    bridgeMode.value =
      info.platform === 'browser-mock'
        ? '浏览器预览模式（mock 数据）'
        : `已连接后端 (Python ${info.python})`
    cfg.value = await api.getConfig()
  } catch (e) {
    // 桥接异常也要给出明确提示，绝不永久卡"加载中"
    bridgeMode.value = `后端连接失败：${e.message || e}`
  }
  try { await store.loadRoots() } catch (e) { /* 非致命 */ }
  try { await store.loadMissing() } catch (e) { /* 非致命 */ }
  bkRefresh()
  store.checkUpdate()  // 打开设置页顺带刷新更新状态（后端 24h 缓存，不打爆 API）
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

// ---- 提供商池 ----
async function setActive(p) {
  const r = await api.setActiveProvider(p.name)
  if (r && r.ok && r.provider) {
    cfg.value.provider = r.provider
    saved.value = true
    setTimeout(() => (saved.value = false), 1500)
  } else {
    alert(r?.error || '切换失败')
  }
}

async function testProv(p) {
  testing.value = true
  try {
    const r = await api.testProvider({ ...p })
    provTest.value = { [p.name || 'provider']: r }
  } finally {
    testing.value = false
  }
}

function removeProv(i) {
  // 没配 providers 数组（单提供商模式）时没有可删项，别再 TypeError
  if (!cfg.value?.providers || !cfg.value.providers[i]) return
  cfg.value.providers.splice(i, 1)
  provTest.value = null
}

// ---- 关于与更新（v1.1） ----
const updCurrent = computed(() => String(store.update.info?.current || '').replace(/^v/, '') || '1.1.0')
const updGit = computed(() => appBuildInfo.value?.git || '')
const hasUpdate = computed(() => !!(store.update.info && store.update.info.has_update))
const updateMsg = computed(() => {
  const info = store.update.info
  if (store.update.checking) return ''
  if (!info) return ''
  if (info.has_update) return `🆕 发现新版本 ${info.latest}（当前 v${updCurrent.value}），点击侧栏提示或下方链接获取`
  if (info.ok && info.note) return info.note
  if (info.ok) return '已是最新版本 ✓'
  return `检查失败：${info.error || '网络不可用'}（不影响使用，可稍后再试）`
})

async function doCheckUpdate() {
  await store.checkUpdate(true)
}

function addProv() {
  if (!cfg.value.providers) cfg.value.providers = []
  cfg.value.providers.push({
    name: `新提供商${cfg.value.providers.length + 1}`,
    model: '', api_key: '', base_url: '',
    vision: false, search: false, enabled: true,
  })
}

// ---- 存档备份（ludusavi 引擎） ----
const bkStatus = ref(null)
const bkTargets = ref([])
const bkBusy = ref(false)
const bkResult = ref(null)
const newTargetPath = ref('')
const bkEnginePath = ref('')
const bkNeverBackedUp = ref(false)
const snapRoot = ref('')
const snapKeep = ref(20)

const kindLabel = (k) => ({ default: '本地', usb: 'U盘', onedrive: 'OneDrive', custom: '自定义' }[k] || k)

async function bkRefresh() {
  if (cfg.value?.backup?.engine_path) bkEnginePath.value = cfg.value.backup.engine_path
  const r = await api.backupEngineStatus()
  bkStatus.value = r
  bkTargets.value = r.targets || []
  bkEnginePath.value = r.engine_path || bkEnginePath.value
  // 从未备份过 → 顶部提示首配引导（备份成功过就不再提示）
  try {
    const hist = await api.backupList()
    bkNeverBackedUp.value = !(hist?.items || []).length
  } catch {
    bkNeverBackedUp.value = false
  }
  // 快照根目录 + 保留份数
  try {
    const sr = await api.backupSnapshotRoot()
    if (sr?.ok) { snapRoot.value = sr.root; snapKeep.value = sr.keep || 20 }
  } catch { /* 忽略 */ }
}

async function probeEngine() {
  const p = bkEnginePath.value.trim()
  if (p) await api.setConfig('backup.engine_path', p)
  await bkRefresh()
}

async function toggleTarget(t) {
  const list = bkTargets.value.map((x) => ({
    path: x.path, enabled: x.path === t.path ? !x.enabled : x.enabled,
    label: x.label || x.path,
  }))
  const r = await api.backupSetTargets(list)
  if (r && r.ok) bkTargets.value = r.targets || []
}

async function addTarget() {
  const p = newTargetPath.value.trim()
  if (!p) return
  const list = bkTargets.value.map((x) => ({
    path: x.path, enabled: x.enabled, label: x.label || x.path,
  }))
  list.push({ path: p, enabled: true, label: '自定义' })
  const r = await api.backupSetTargets(list)
  if (r && r.ok) {
    bkTargets.value = r.targets || []
    newTargetPath.value = ''
  }
}

async function backupAllNow() {
  await save()
  bkBusy.value = true
  bkResult.value = null
  try {
    const r = await api.backupAll()
    bkResult.value = r
    if (!r.ok && !(r.targets || []).length) alert(r.error || '备份失败')
    await bkRefresh()
  } finally {
    bkBusy.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await api.setConfig('provider', cfg.value.provider)
    await api.setConfig('providers', cfg.value.providers || [])
    await api.setConfig('proxy', cfg.value.proxy)
    await api.setConfig('locale_emulator', cfg.value.locale_emulator || { path: '' })
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
