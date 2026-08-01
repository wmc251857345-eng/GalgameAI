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

createApp(App).use(createPinia()).mount('#app')
