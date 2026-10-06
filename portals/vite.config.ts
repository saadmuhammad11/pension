import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Development server only (:5300). The running system is served by api/portal_server.py, one
// process on every portal's port, from the build in dist/. In development the page asks
// /api/v2/portals for its config and picks the portal named by ?portal=<slug>.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    port: 5300,
    strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8110', changeOrigin: true } },
    // config/case_types.json sits at the repository root, shared with the Python rules.
    fs: { allow: ['..'] },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
