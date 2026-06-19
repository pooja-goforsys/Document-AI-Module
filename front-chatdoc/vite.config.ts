import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',   // force IPv4 — avoids ::1 vs 127.0.0.1 mismatch on Windows
    port: 5173,
    strictPort: true,    // fail clearly if 5173 is taken instead of silently switching
  },
})
