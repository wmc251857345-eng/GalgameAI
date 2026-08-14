<template>
  <div class="view-page detail">
    <button class="btn back-btn" @click="store.back()">← 返回游戏库</button>

    <div v-if="store.detailLoading" class="loading">加载中…</div>

    <!-- 加载失败：显示原因 + 返回，绝不空白/转圈 -->
    <div v-else-if="store.detailError" class="detail-error">
      <p>⚠ {{ store.detailError }}</p>
      <button class="btn" @click="retry">🔄 重试</button>
      <button class="btn" @click="store.back()">← 返回游戏库</button>
    </div>

    <template v-else-if="g">
      <!-- ================= 头部横幅区 ================= -->
      <div class="detail-hero">
        <div class="hero-cover">
          <img
            v-if="g.cover_url && !heroImgFail"
            :src="g.cover_url"
            alt=""
            @error="heroImgFail = true"
          />
          <div v-else class="cover-grad"></div>
        </div>
        <div class="hero-info">
          <div class="hero-title">{{ g.title }}</div>
          <div class="hero-tags">
            <span v-if="g.status === 2" class="status-badge ok">✓ 已入库</span>
            <span v-else-if="g.status === 1" class="status-badge warn">? 待确认</span>
            <span v-else-if="g.status === 3" class="status-badge skip">已跳过</span>
            <span v-if="g.hanhua" class="status-badge hanhua">汉化</span>
            <span v-if="g.running" class="status-badge running">▶ 运行中</span>
            <span v-if="g.source === 'manual'" class="status-badge manual">手动编辑</span>
          </div>

          <!-- 只读信息表 -->
          <table v-if="!editing" class="info-table">
            <tr><td>中文名</td><td>{{ g.title_zh || '—' }}</td></tr>
            <tr><td>日文名</td><td>{{ g.title_jp || '—' }}</td></tr>
            <tr><td>英文名</td><td>{{ g.title_en || '—' }}</td></tr>
            <tr><td>制作</td><td>
              <span
                v-if="g.maker"
                class="mk-link"
                title="查看该厂商的全部作品"
                @click="store.openMaker(g.maker.split(' / ')[0].trim())"
              >{{ g.maker }}</span>
              <span v-else>—</span>
            </td></tr>
            <tr><td>发售</td><td>{{ g.released || '—' }}</td></tr>
            <tr><td>评分</td><td>{{ g.rating_disp != null ? '★ ' + g.rating_disp : '—' }}</td></tr>
            <tr><td>时长</td><td>{{ lengthText }}</td></tr>
            <tr><td>游玩</td><td>{{ g.playtime_hours }}h<template v-if="g.last_played"> · 最近 {{ g.last_played }}</template></td></tr>
            <tr><td>体积</td><td>{{ sizeText }}</td></tr>
            <tr><td>本地路径</td><td class="path-cell">{{ g.path }}</td></tr>
            <tr v-if="g.exe_path"><td>启动 exe</td><td class="path-cell">{{ g.exe_path }}</td></tr>
            <tr><td>数据源</td><td>{{ sourceText }}<template v-if="g.vndb_id"> · {{ g.vndb_id }}</template></td></tr>
          </table>

          <!-- 编辑表单 -->
          <table v-else class="info-table edit-table">
            <tr><td>中文名</td><td><input v-model="form.title_zh" placeholder="中文常用译名" /></td></tr>
            <tr><td>日文名</td><td><input v-model="form.title_jp" placeholder="日文原名" /></td></tr>
            <tr><td>英文名</td><td><input v-model="form.title_en" placeholder="英文/罗马音" /></td></tr>
            <tr><td>显示标题</td><td><input v-model="form.title" placeholder="列表中显示的标题" /></td></tr>
            <tr><td>制作</td><td><input v-model="form.maker" placeholder="制作公司" /></td></tr>
            <tr><td>发售日</td><td><input v-model="form.released" placeholder="YYYY-MM-DD" /></td></tr>
            <tr><td>评分</td><td><input v-model.number="form.rating" type="number" step="0.1" min="0" max="10" placeholder="0-10" /></td></tr>
            <tr><td>时长(分钟)</td><td><input v-model.number="form.length_minutes" type="number" min="0" placeholder="约多少分钟" /></td></tr>
            <tr><td>启动 exe</td><td><input v-model="form.exe_path" placeholder="exe 绝对路径" /></td></tr>
            <tr><td>工作目录</td><td><input v-model="form.workdir" placeholder="可选，默认 exe 所在目录" /></td></tr>
            <tr><td>启动参数</td><td><input v-model="form.launch_args" placeholder="可选" /></td></tr>
            <tr><td>汉化</td><td><input v-model="form.hanhua" type="checkbox" style="width:auto;height:auto;accent-color:var(--accent)" /></td></tr>
            <tr><td>简介</td><td><textarea v-model="form.description" rows="4" placeholder="中文简介"></textarea></td></tr>
          </table>

          <div class="hero-actions">
            <!-- 只读模式 -->
            <template v-if="!editing">
              <button v-if="!g.running" class="btn primary" @click="launch">▶ 启动游戏</button>
              <button v-else class="btn danger" @click="stop">■ 停止</button>
              <button class="btn" :class="{ 'fav-on': g.favorite }" @click="toggleFav">
                {{ g.favorite ? '♥ 已收藏' : '♡ 收藏' }}
              </button>
              <button class="btn" :disabled="reanalyzing" @click="reanalyze">
                {{ reanalyzing ? '⟳ 分析中…' : '⟳ 重新 AI 分析' }}
              </button>
              <button class="btn" @click="askButler">💬 问管家</button>
              <button v-if="g.vndb_id" class="btn" @click="store.openSeries(g.vndb_id)">🧩 系列/前作</button>
              <button class="btn" @click="startEdit">✏ 编辑</button>
              <label class="le-toggle">
                <input :checked="!!g.use_locale_emu" type="checkbox" @change="toggleLe" />
                Locale Emulator
              </label>
            </template>
            <!-- 编辑模式 -->
            <template v-else>
              <button class="btn primary" :disabled="saving" @click="save">✓ 保存</button>
              <button class="btn" @click="cancelEdit">取消</button>
              <button class="btn danger" @click="del">🗑 删除游戏</button>
            </template>
          </div>

          <!-- exe 失效警告 -->
          <div v-if="!editing && g.exe_path && !g.exe_exists" class="warn-banner">
            <span>⚠ exe 不存在：{{ g.exe_path }}（游戏可能被移动/重命名）</span>
            <button class="btn small" @click="relocate">📂 重新定位目录</button>
          </div>
        </div>
      </div>

      <!-- 封面管理（编辑模式） -->
      <div v-if="editing" class="detail-section cover-edit">
        <h2>封面</h2>
        <div class="cover-tools">
          <button class="btn small" @click="pickLocal">🖼 选择本地图片</button>
          <button class="btn small" @click="refreshCover">⟳ 从 VNDB 补封面</button>
          <input v-model="coverUrlInput" class="url-input" placeholder="或粘贴图片 URL 下载" @keyup.enter="setUrl" />
          <button class="btn small" @click="setUrl" :disabled="downloading">
            {{ downloading ? '下载中…' : '下载' }}
          </button>
        </div>
        <div v-if="coverCands.length" class="cover-cands">
          <span class="dim">候选封面（点击选用）：</span>
          <img
            v-for="(c, i) in coverCands"
            :key="i"
            :src="c.cover_url"
            class="cover-cand"
            :title="(c.provider || '').toUpperCase() + ' · ' + (c.title || '')"
            v-imgfb="'🖼'"
            @click="useCandCover(c.cover_url)"
          />
        </div>
      </div>

      <!-- 标签 -->
      <div class="detail-section">
        <h2>标签</h2>
        <div class="tag-list">
          <template v-if="!editing">
            <span v-for="t in g.tags" :key="t" class="tag-chip">#{{ t }}</span>
            <span v-if="!g.tags?.length" class="dim">暂无标签</span>
          </template>
          <template v-else>
            <span v-for="(t, i) in editTags" :key="t + i" class="tag-chip editable">
              #{{ t }} <button class="tag-x" @click="editTags.splice(i, 1)">×</button>
            </span>
            <span class="tag-add">
              <input v-model="tagInput" placeholder="+ 添加标签" @keyup.enter="addTag" />
              <button class="btn small" @click="addTag">添加</button>
            </span>
          </template>
        </div>
      </div>

      <!-- 简介 -->
      <div class="detail-section">
        <h2>简介</h2>
        <p class="desc">{{ g.description || '暂无简介' }}</p>
        <details v-if="g.text_sample" class="local-info">
          <summary>本地文件信息（readme 等）</summary>
          <pre class="text-sample">{{ g.text_sample }}</pre>
        </details>
      </div>

      <!-- 存档备份 -->
      <div class="detail-section backup-section">
        <h2>存档备份</h2>
        <template v-if="bkEngine && bkEngine.ok">
          <div class="bk-row">
            <button class="btn small" :disabled="bkBusy" @click="detectSaves">
              🔍 自动探测存档位置
            </button>
            <button class="btn small primary" :disabled="bkBusy || !savePaths.length" @click="doSnapshot">
              {{ bkBusy ? '备份中…' : '📸 立即备份快照' }}
            </button>
            <button class="btn small" :disabled="bkBusy" @click="doImport">📥 导入存档</button>
          </div>
          <div v-if="savePaths.length" class="bk-paths">
            <div v-for="p in savePaths" :key="p" class="bk-path">
              <span class="bk-path-text">{{ p }}</span>
              <button class="tag-x" title="移除" @click="removeSavePath(p)">×</button>
            </div>
          </div>
          <div v-else class="bk-hint">
            {{ candidates.length ? '找到候选，点击路径添加：' : '尚未配置存档路径。点「自动探测」扫描游戏目录 / 文档 / AppData，或手动填写。' }}
          </div>
          <div v-if="candidates.length" class="bk-cands">
            <button
              v-for="c in candidates"
              :key="c.path"
              class="bk-cand"
              :class="{ hit: c.exists }"
              :disabled="savePaths.includes(c.path)"
              @click="addSavePath(c.path)"
            >
              <span class="bk-cand-dot">{{ c.exists ? '✓' : '·' }}</span>
              {{ c.reason }}<span class="bk-cand-path">（{{ c.path }}）</span>
            </button>
          </div>
          <div v-if="bkMeta" class="bk-meta">
            <span v-if="bkMeta.last_backup_at">上次引擎备份：{{ bkMeta.last_backup_at }}</span>
            <span v-if="bkMeta.backup_count">共 {{ bkMeta.backup_count }} 次</span>
          </div>
          <h3 style="margin-top: 12px">版本时间线（{{ snapVersions.length }}）</h3>
          <div v-if="snapVersions.length" class="bk-versions">
            <div v-for="v in snapVersions" :key="v.ts" class="bk-version snap-ver">
              <span class="bk-ver-time">{{ fmtSnapTime(v.backed_at) }}</span>
              <span class="bk-ver-kind" :class="v.kind">{{ v.kind === 'auto' ? '自动' : '手动' }}</span>
              <span v-if="v.bytes" class="bk-ver-size">· {{ fmtSize(v.bytes) }}</span>
              <span v-if="!v.exists" class="bk-ver-missing">（目录已清理）</span>
              <button v-if="v.exists" class="btn small bk-ver-restore" :disabled="bkBusy" @click="doRestoreSnap(v.ts)">
                恢复此版本
              </button>
            </div>
          </div>
          <div v-else class="bk-hint">
            暂无版本快照：从 GALA 启动游戏并关闭后会自动备份（可随时回滚）；也可点「📸 立即备份快照」手动保存一份。
          </div>
          <p class="hint" style="margin-top: 6px">
            快照保存在 GALA 数据目录 database/backups/&lt;游戏名&gt;/，每游戏保留 20 份，恢复前会自动保存当前状态。
          </p>
        </template>
        <div v-else class="bk-hint">
          {{ bkEngine ? bkEngine.error : '引擎检测中…' }}
        </div>
      </div>

      <!-- 待确认候选 -->
      <div v-if="g.status === 1 && !editing" class="detail-section">
        <h2>AI 匹配候选（置信度不足，请选择或手动编辑）</h2>
        <div class="cand-row">
          <div v-for="c in g.candidates" :key="c.provider + c.external_id" class="cand-card" :class="'conf-' + confClass(c.score)">
            <img v-if="c.cover_url" :src="c.cover_url" class="cand-img" alt="" />
            <div v-else class="cand-img cand-img-empty"></div>
            <div class="cand-title">{{ c.title }}{{ c.title_orig && c.title_orig !== c.title ? ' / ' + c.title_orig : '' }}</div>
            <div class="cand-meta">{{ c.maker || '' }} {{ c.released || '' }} · {{ c.provider.toUpperCase() }}</div>
            <div class="cand-score">{{ Math.round(c.score * 100) }}%</div>
            <button class="btn primary small" @click="confirm(c)">确认</button>
          </div>
          <div v-if="!g.candidates?.length" class="dim">没有候选，可跳过或重新分析</div>
        </div>
        <button class="btn" @click="skip">跳过（不匹配任何条目）</button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'

const store = useLibraryStore()
const g = computed(() => store.detail)

const heroImgFail = ref(false)
// 切换游戏时重置封面失败标记
watch(() => store.selectedGameId, () => { heroImgFail.value = false })

const editing = ref(false)
const saving = ref(false)
const reanalyzing = ref(false)
const downloading = ref(false)
let jobTimer = null
onUnmounted(() => clearTimeout(jobTimer))
const form = reactive({})
const editTags = ref([])
const tagInput = ref('')
const coverUrlInput = ref('')

const lengthText = computed(() => {
  if (!g.value) return ''
  if (g.value.length_minutes) return `约 ${Math.round(g.value.length_minutes / 60)} 小时`
  const lv = g.value.length_level
  return { 1: '很短', 2: '短', 3: '中等', 4: '长', 5: '很长' }[lv] || '—'
})

const sizeText = computed(() => {
  const b = g.value?.size_bytes
  if (!b) return '—'
  const gb = b / 1024 ** 3
  if (gb >= 1) return gb.toFixed(2) + ' GB'
  const mb = b / 1024 ** 2
  if (mb >= 1) return Math.round(mb) + ' MB'
  return Math.round(b / 1024) + ' KB'
})
const sourceText = computed(() => {
  const s = g.value?.source
  return { bgm: 'Bangumi', vndb: 'VNDB', ai: 'AI', manual: '手动编辑' }[s] || '本地扫描'
})

function confClass(score) {
  return score >= 0.8 ? 'high' : score >= 0.6 ? 'mid' : 'low'
}

function retry() {
  store.openDetail(store.selectedGameId)
}

// ---- 编辑 ----
const coverCands = computed(() =>
  (g.value?.candidates || []).filter((c) => c.cover_url).slice(0, 6),
)

function startEdit() {
  const d = g.value
  Object.assign(form, {
    title: d.title || '', title_zh: d.title_zh || '', title_jp: d.title_jp || '',
    title_en: d.title_en || '', maker: d.maker || '', released: d.released || '',
    rating: d.rating_disp, length_minutes: d.length_minutes, description: d.description || '',
    exe_path: d.exe_path || '', workdir: d.workdir || '', launch_args: d.launch_args || '',
    hanhua: !!d.hanhua,
  })
  editTags.value = [...(d.tags || [])]
  editing.value = true
}

function cancelEdit() {
  editing.value = false
  store.refreshDetail()
}

async function save() {
  saving.value = true
  try {
    const r = await api.updateGame(g.value.id, { ...form })
    if (r && !r.ok) { alert(r.error); return }
    await api.updateTags(g.value.id, editTags.value)
    editing.value = false
    await store.refreshDetail()
    store.load()
  } finally {
    saving.value = false
  }
}

function addTag() {
  const t = tagInput.value.trim()
  if (t && !editTags.value.includes(t)) editTags.value.push(t)
  tagInput.value = ''
}

async function del() {
  if (!confirm(`确定删除「${g.value.title}」？仅从库中移除，不会动磁盘文件。`)) return
  await api.removeGame(g.value.id)
  store.back()
  store.load()
}

// ---- 封面 ----
async function pickLocal() {
  const r = await api.chooseCover(g.value.id)
  if (r && !r.ok) alert(r.error)
  else store.refreshDetail()
}

async function setUrl() {
  const url = coverUrlInput.value.trim()
  if (!url || downloading.value) return
  downloading.value = true
  try {
    const r = await api.setCoverUrl(g.value.id, url)
    if (r && !r.ok) alert(r.error)
    else {
      coverUrlInput.value = ''
      store.refreshDetail()
    }
  } finally {
    downloading.value = false
  }
}

async function refreshCover() {
  const r = await api.refreshCover(g.value.id)
  if (r && !r.ok) alert(r.error)
  else store.refreshDetail()
}

async function useCandCover(url) {
  const r = await api.setCoverUrl(g.value.id, url)
  if (r && !r.ok) alert(r.error)
  else store.refreshDetail()
}

// ---- 动作 ----
async function toggleFav() {
  await store.toggleFavorite(g.value)
  store.load()
}

function askButler() {
  store.setChatContext(g.value)
  store.currentView = 'chat'
}

async function relocate() {
  if (await store.relocateGame(g.value.id)) {
    await store.refreshDetail()
  }
}

async function launch() {
  const r = await api.launchGame(g.value.id)
  if (r && !r.ok) alert(r.error)
  else store.refreshRunning()
}
async function stop() {
  await api.stopGame(g.value.id)
  store.refreshRunning()
  store.refreshDetail()
}
async function reanalyze() {
  const r = await api.reanalyzeGame(g.value.id)
  if (r && !r.ok) {
    alert(r.error)
    return
  }
  reanalyzing.value = true
  pollJob()
}

function pollJob() {
  clearTimeout(jobTimer)
  jobTimer = setTimeout(async () => {
    let st = null
    try {
      st = await api.getJobStatus()
    } catch (e) {
      st = null
    }
    if (st && st.running) {
      pollJob()
    } else {
      reanalyzing.value = false
      if (st && st.error) alert(`分析失败: ${st.error}`)
      await store.refreshDetail()
      store.load()
    }
  }, 1500)
}
async function confirm(c) {
  const r = await api.confirmMatch(g.value.id, c.provider, c.external_id)
  if (r && !r.ok) alert(r.error)
  store.refreshDetail()
  store.load()
}
async function skip() {
  await api.markUnmatched(g.value.id)
  store.back()
  store.load()
}
async function toggleLe(e) {
  await api.setLocaleEmu(g.value.id, e.target.checked)
}

// ---- 存档备份 ----
const bkEngine = ref(null)
const bkBusy = ref(false)
const savePaths = ref([])
const candidates = ref([])
const bkMeta = ref(null)
const bkVersions = ref([])
const snapVersions = ref([])

// 切换游戏时加载备份状态
watch(() => store.selectedGameId, async () => {
  bkEngine.value = null
  candidates.value = []
  bkVersions.value = []
  snapVersions.value = []
  if (!g.value?.id) return
  try {
    bkEngine.value = await api.backupEngineStatus()
  } catch (e) { bkEngine.value = { ok: false, error: '引擎检测失败' } }
  await loadBackupState()
})

async function loadBackupState() {
  if (!g.value?.id) return
  try {
    const [pathsR, listR, verR, snapR] = await Promise.all([
      api.backupGetSavePaths(g.value.id),
      api.backupList(g.value.id),
      api.backupVersions(g.value.id).catch(() => ({ ok: true, items: [] })),
      api.backupSnapshotVersions(g.value.id).catch(() => ({ ok: true, items: [] })),
    ])
    savePaths.value = pathsR.paths || []
    bkMeta.value = (listR.items || [])[0] || null
    bkVersions.value = verR.items || []
    snapVersions.value = snapR.items || []
  } catch (e) {
    /* 静默 */
  }
}

async function detectSaves() {
  bkBusy.value = true
  try {
    const r = await api.backupDetectSavePaths(g.value.id)
    candidates.value = (r.candidates || []).filter((c) => c.exists)
    if (!candidates.value.length) alert('没有探测到存档位置，可手动填写路径后添加')
  } finally {
    bkBusy.value = false
  }
}

async function addSavePath(p) {
  if (savePaths.value.includes(p)) return
  savePaths.value.push(p)
  await api.backupSavePaths(g.value.id, savePaths.value)
  store.load()
}

async function removeSavePath(p) {
  savePaths.value = savePaths.value.filter((x) => x !== p)
  await api.backupSavePaths(g.value.id, savePaths.value)
}

async function doSnapshot() {
  bkBusy.value = true
  try {
    const r = await api.backupSnapshotGame(g.value.id)
    if (!r.ok) { alert(r.error || '备份失败'); return }
    alert(`✓ 快照已保存（${fmtSize(r.bytes || 0)}）`)
    await loadBackupState()
    store.load()
  } finally {
    bkBusy.value = false
  }
}

async function doImport() {
  const r = await api.backupSnapshotImport(g.value.id)
  if (!r.ok) { alert(r.error || '导入失败'); return }
  alert(`✓ 存档已导入 → ${r.target}`)
  await loadBackupState()
}

async function doRestoreSnap(ts) {
  if (!confirm(`确定恢复 ${ts} 版本？\n当前存档会先自动保存为新版本（可反悔）。`)) return
  bkBusy.value = true
  try {
    const r = await api.backupSnapshotRestore(g.value.id, ts)
    if (!r.ok) { alert(r.error || '恢复失败'); return }
    alert(`✓ 已恢复 ${r.ts} 版本（${r.restored.length} 个存档目录）`)
    await loadBackupState()
  } finally {
    bkBusy.value = false
  }
}

function fmtSize(b) {
  if (!b) return '0 B'
  if (b > 1024 * 1024) return (b / 1024 / 1024).toFixed(1) + ' MB'
  if (b > 1024) return (b / 1024).toFixed(0) + ' KB'
  return b + ' B'
}

function fmtSnapTime(ts) {
  if (!ts) return ''
  const d = new Date(String(ts).replace(' ', 'T'))
  if (isNaN(d.getTime())) return ts || ''
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
</script>
