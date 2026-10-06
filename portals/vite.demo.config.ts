import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The self-running demo (demo/auto-demo.html): the real screens with a scripted user and no
// backend. Built separately, then folded into ONE html file by demo/build.py.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: 'dist-demo', emptyOutDir: true, assetsInlineLimit: 1024 * 1024 * 64,
    rollupOptions: { input: process.env.DEMO_ENTRY || 'manual.html', output: { inlineDynamicImports: true } },
    chunkSizeWarningLimit: 60000,
  },
})
