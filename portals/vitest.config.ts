import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Unit tests for the portal (frontend review F6): Vitest + Testing Library on jsdom. `npm test`.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
