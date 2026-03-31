import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/agent': 'http://localhost:8001',
      '/sessions': 'http://localhost:8001',
      '/vouchers': 'http://localhost:8001',
      '/oa': 'http://localhost:8001',
    },
  },
})
