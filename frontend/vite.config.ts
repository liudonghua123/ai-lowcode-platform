import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Vite 6 blocks unknown Host headers by default. Allow the ephemeral
    // *.trycloudflare.com host used by `cloudflared tunnel --url`.
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/mcp': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
  },
})
