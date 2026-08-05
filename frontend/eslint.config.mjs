// ESLint 9 flat config. Replaces .eslintrc.js, which ESLint 9 ignores entirely —
// `npm run lint` errored out on startup rather than linting anything, and the
// old config also extended @vue/eslint-config-airbnb, which is not installed.
//
// vue-tsc (npm run type-check) owns type errors; this config covers what the
// type checker cannot see: unused code, Vue template correctness, and the
// no-undef class of mistakes.

import js from '@eslint/js'
import vue from 'eslint-plugin-vue'
import tsParser from '@typescript-eslint/parser'
import tsPlugin from '@typescript-eslint/eslint-plugin'
import vueParser from 'vue-eslint-parser'

export default [
  {
    ignores: ['dist/**', 'node_modules/**', '*.config.js', '*.config.ts'],
  },

  js.configs.recommended,
  ...vue.configs['flat/recommended'],

  {
    files: ['**/*.ts', '**/*.vue'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      parser: vueParser,
      parserOptions: {
        parser: tsParser,
        extraFileExtensions: ['.vue'],
      },
      globals: {
        // Browser APIs the admin UI actually uses.
        window: 'readonly',
        document: 'readonly',
        console: 'readonly',
        fetch: 'readonly',
        FormData: 'readonly',
        Blob: 'readonly',
        URL: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        confirm: 'readonly',
        alert: 'readonly',
        localStorage: 'readonly',
        EventSource: 'readonly',
        HTMLElement: 'readonly',
        HTMLIFrameElement: 'readonly',
      },
    },
    plugins: { '@typescript-eslint': tsPlugin },
    rules: {
      // TypeScript's own checker handles undefined identifiers and shadowed
      // types far better; base no-undef misfires on type-only names.
      'no-undef': 'off',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // Formatting is not enforced here — reviewers, not CI, own style.
      'vue/max-attributes-per-line': 'off',
      'vue/html-indent': 'off',
      'vue/html-self-closing': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-closing-bracket-newline': 'off',
      'vue/first-attribute-linebreak': 'off',
      'vue/attributes-order': 'off',
      // One-word view names (Dashboard.vue, Lists.vue) are the convention here.
      'vue/multi-word-component-names': 'off',
    },
  },
]
