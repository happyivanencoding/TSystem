import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/client/',
  plugins: [react()],
  test: {
    environment: 'jsdom',
  },
  server: {
    proxy: {
      '/api/dashboard': {
        target: 'http://127.0.0.1:8060',
        changeOrigin: true,
      },
    },
  },
})
