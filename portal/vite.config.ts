import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' so the built bundle works from a sub-path inside the AG office network and from
// the filesystem during an air-gapped demo.
// /api is proxied to the pilot API, which runs the real pipeline. In production both sit
// behind one origin and the proxy disappears.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    port: 5184,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8110', changeOrigin: true },
    },
  },
})
