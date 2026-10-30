import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  build:
    mode === 'operator'
      ? { outDir: 'dist-operator', rolldownOptions: { input: 'operator.html' } }
      : {},
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000', '/auth': 'http://127.0.0.1:8000' },
    host: '127.0.0.1',
  },
}))
