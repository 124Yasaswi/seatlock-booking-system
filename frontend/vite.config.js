import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The React dev server forwards /api (and the WebSocket) to the FastAPI backend.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8030', ws: true },
    },
  },
})
