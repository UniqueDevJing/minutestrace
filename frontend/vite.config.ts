import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/minutestrace/',
  plugins: [vue()],
  server: {
    proxy: {
      '/minutestrace/api': {
        target: 'http://127.0.0.1:8000',
        rewrite: path => path.replace(/^\/minutestrace\/api/, ''),
      },
    },
  },
})
