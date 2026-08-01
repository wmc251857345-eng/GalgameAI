import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  // base './'：产物用相对路径，pywebview 以 file:// 加载 dist 时才能找到资源
  base: './',
  plugins: [vue()],
  server: { port: 5173, strictPort: true },
  build: { outDir: 'dist', assetsDir: 'assets', chunkSizeWarningLimit: 1024 },
})
