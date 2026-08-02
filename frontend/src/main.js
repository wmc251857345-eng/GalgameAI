import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './styles/main.css'
import { api } from './api.js'

// 全局错误上报：JS 异常/未捕获 Promise → 写 logs/app.log（节流，防循环）
let _lastErr = 0
function reportError(msg) {
  const now = Date.now()
  if (now - _lastErr < 1000) return // 每秒最多 1 条
  _lastErr = now
  api.logError(msg)
}
window.addEventListener('error', (e) => reportError(e.message || 'JS error'))
window.addEventListener('unhandledrejection', (e) => {
  reportError('未捕获的 Promise 异常: ' + (e.reason?.message || String(e.reason || '').slice(0, 200)))
})

const app = createApp(App)

// 全局图片加载失败降级：远程封面失败/挂起时隐藏 img，插入占位块（防破图/空白）
app.directive('imgfb', {
  mounted(el, binding) {
    el.addEventListener('error', () => {
      try {
        if (el._imgfbDone) return
        el._imgfbDone = true
        el.style.display = 'none'
        const ph = document.createElement('div')
        ph.className = 'img-fb'
        ph.textContent = binding.value || ''
        if (el.parentNode) el.parentNode.insertBefore(ph, el.nextSibling)
      } catch (e) { /* 占位失败不致命 */ }
    })
  },
})

app.use(createPinia())
// Vue 渲染/生命周期错误（onerror 抓不到）→ 上报日志 + 全局横幅
app.config.errorHandler = (err, _instance, info) => {
  const msg = `[Vue渲染] ${info || ''} ${err?.message || err}`
  reportError(msg)
  if (window.__galaSetError) {
    window.__galaSetError((err?.message || err) + '（详情见 设置→查看日志）')
  }
}
app.mount('#app')
