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
  // No manualChunks. An earlier attempt forced recharts into a named `charts`
  // chunk, which pulled it into the ENTRY's static graph -- Vite then emitted
  // a <link rel="modulepreload"> for it, so every visitor downloaded 387 kB of
  // charting library before seeing the landing page. That is the opposite of
  // what the split was for.
  //
  // Vite's automatic splitting already does the right thing: the lazy route
  // imports in App.tsx are the async boundary, and recharts lands inside the
  // Profile chunk where it belongs. Verified by checking index.html emits no
  // modulepreload at all.
})
