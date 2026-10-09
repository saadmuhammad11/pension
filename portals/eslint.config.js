// ESLint for the portal (frontend review F6, 9 Oct 2026): TypeScript rules and the React hooks
// rules, exhaustive-deps on. `npm run lint`. The demo tree is linted with the same rules.
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'

export default tseslint.config(
  { ignores: ['dist/**', 'dist-demo/**', 'node_modules/**', '*.mjs', 'vite.config.ts', 'vite.demo.config.ts', 'eslint.config.js'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    languageOptions: { globals: { ...globals.browser } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-hooks/exhaustive-deps': 'warn',
      // The code base uses `_x` for a value it has to accept and not use.
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // Empty catch blocks with a comment are the project's way of saying "ignore"; keep them.
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
)
