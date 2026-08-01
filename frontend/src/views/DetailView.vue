<template>
  <div class="view-page detail">
    <button class="btn back-btn" @click="store.back()">← 返回游戏库</button>

    <div v-if="store.detailLoading" class="loading">加载中…</div>

    <template v-else-if="g">
      <!-- ================= 头部横幅区 ================= -->
      <div class="detail-hero">
        <div class="hero-cover">
          <img v-if="g.cover_url" :src="g.cover_url" alt="" />
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
            <tr><td>制作</td><td>{{ g.maker || '—' }}</td></tr>
            <tr><td>发售</td><td>{{ g.released || '—' }}</td></tr>
            <tr><td>评分</td><td>{{ g.rating_disp != null ? '★ ' + g.rating_disp : '—' }}</td></tr>
            <tr><td>时长</td><td>{{ lengthText }}</td></tr>
            <tr><td>游玩</td><td>{{ g.playtime_hours }}h<template v-if="g.last_played"> · 最近 {{ g.last_played }}</template></td></tr>
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
              <button class="btn" @click="reanalyze">⟳ 重新 AI 分析</button>
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
        </div>
      </div>

      <!-- 封面管理（编辑模式） -->
      <div v-if="editing" class="detail-section cover-edit">
        <h2>封面</h2>
        <div class="cover-tools">
          <button class="btn small" @click="pickLocal">🖼 选择本地图片</button>
          <button class="btn small" @click="refreshCover">⟳ 从 VNDB 补封面</button>
          <input v-model="coverUrlInput" class="url-input" placeholder="或粘贴图片 URL 下载" @keyup.enter="setUrl" />
          <button class="btn small" @click="setUrl">下载</button>
        </div>
        <div v-if="coverCands.length" class="cover-cands">
          <span class="dim">候选封面（点击选用）：</span>
          <img
            v-for="(c, i) in coverCands"
            :key="i"
            :src="c.cover_url"
            class="cover-cand"
            :title="(c.provider || '').toUpperCase() + ' · ' + (c.title || '')"
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
import { computed, reactive, ref } from 'vue'
import { useLibraryStore } from '../stores/library.js'
import { api } from '../api.js'

const store = useLibraryStore()
const g = computed(() => store.detail)

const editing = ref(false)
const saving = ref(false)
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
const sourceText = computed(() => {
  const s = g.value?.source
  return { bgm: 'Bangumi', vndb: 'VNDB', ai: 'AI', manual: '手动编辑' }[s] || '本地扫描'
})

function confClass(score) {
  return score >= 0.8 ? 'high' : score >= 0.6 ? 'mid' : 'low'
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
  if (!url) return
  const r = await api.setCoverUrl(g.value.id, url)
  if (r && !r.ok) alert(r.error)
  else {
    coverUrlInput.value = ''
    store.refreshDetail()
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
  if (r && !r.ok) alert(r.error)
  store.refreshDetail()
  store.load()
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
</script>
