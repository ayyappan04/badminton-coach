import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The dev server proxies /api to the local FastAPI process so the browser
// makes same-origin calls and CORS never enters development. Production does
// the opposite: VITE_API_BASE_URL points at the API container directly, and
// that origin must be listed in the backend's CORS_ORIGINS.
const API_TARGET = process.env.VITE_DEV_API_TARGET ?? 'http://127.0.0.1:8123'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
    // Recharts is the single heaviest dependency and is only reachable from
    // the Progress route. Splitting it out keeps it off the critical path for
    // a signed-out visitor.
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/recharts') || id.includes('node_modules/d3-')) {
            return 'charts'
          }
          // tus is only reachable from the upload flow on the Matches route.
          // supabase-js is deliberately NOT split out: the auth session is
          // read on first paint, so a separate request for it would just add a
          // round trip to the critical path.
          if (id.includes('node_modules/tus-js-client')) {
            return 'tus'
          }
        },
      },
    },
  },
})
