// 轻量 Markdown → HTML 渲染器（聊天用，零依赖）
// 安全策略：先 HTML 转义，再解析结构；代码块/行内代码先占位提取，恢复时再转义
// 支持：**加粗**、*斜体*、`代码`、```代码块```、#/##/### 标题、-/* 无序列表、
//       1. 有序列表、> 引用、[文字](https://链接)、段落与空行分段

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export function md(src) {
  if (!src) return ''
  let text = String(src)

  // 1) 提取代码块与行内代码（占位符 \u0000MD<n>\u0000）
  const blocks = []
  text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
    blocks.push({ type: 'block', lang, code })
    return `\u0000MD${blocks.length - 1}\u0000`
  })
  text = text.replace(/`([^`\n]+)`/g, (m, code) => {
    blocks.push({ type: 'inline', code })
    return `\u0000MD${blocks.length - 1}\u0000`
  })

  // 2) 转义剩余文本（此时代码内容已被占位符隔离，不会双重转义）
  text = esc(text)

  // 3) 行内格式
  text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  text = text.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>',
  )

  // 4) 标题（转义后 # 原样保留）
  text = text.replace(/^###\s+(.+)$/gm, '<h4>$1</h4>')
  text = text.replace(/^##\s+(.+)$/gm, '<h3>$1</h3>')
  text = text.replace(/^#\s+(.+)$/gm, '<h2>$1</h2>')

  // 5) 逐行：列表 / 引用 / 段落 / 空行
  const lines = text.split('\n')
  let html = ''
  let inList = null
  for (const line of lines) {
    const ul = line.match(/^[-*•]\s+(.*)$/)
    const ol = line.match(/^\d+[.、]\s+(.*)$/)
    const quote = line.match(/^&gt;\s?(.*)$/)
    if (ul || ol) {
      const tag = ul ? 'ul' : 'ol'
      if (inList !== tag) {
        if (inList) html += `</${inList}>`
        html += `<${tag}>`
        inList = tag
      }
      html += `<li>${(ul || ol)[1]}</li>`
      continue
    }
    if (inList) {
      html += `</${inList}>`
      inList = null
    }
    if (quote) {
      html += `<blockquote>${quote[1]}</blockquote>`
      continue
    }
    const t = line.trim()
    if (t === '') {
      html += '<div class="md-gap"></div>'
      continue
    }
    if (/^<(h2|h3|h4|ul|ol|blockquote|pre)/.test(t)) {
      html += t // 结构行直接输出
      continue
    }
    html += `<p>${t}</p>`
  }
  if (inList) html += `</${inList}>`

  // 6) 恢复代码占位符
  html = html.replace(/\u0000MD(\d+)\u0000/g, (m, i) => {
    const b = blocks[+i]
    if (!b) return m
    if (b.type === 'block') {
      const lang = b.lang ? `<span class="md-code-lang">${esc(b.lang)}</span>` : ''
      return `<div class="md-code-wrap">${lang}<pre class="md-code"><code>${esc(b.code.trim())}</code></pre></div>`
    }
    return `<code class="md-inline">${esc(b.code)}</code>`
  })
  return html
}

/** 提取纯文本（用于复制/剪贴板）：去代码、去粗体斜体、去链接语法 */
export function mdPlain(src) {
  return String(src || '')
    .replace(/```(\w*)\n?([\s\S]*?)```/g, '\n$2\n')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1$2')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '$1')
}
