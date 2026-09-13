import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: './',
  plugins: [
    react(),
    {
      name: 'mariana-vite-development-csp',
      transformIndexHtml(html, context) {
        if (!context.server) return html
        // Vite's React refresh preamble is an inline development-only module.
        return html.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")
      },
    },
  ],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rolldownOptions: {
      output: {
        // Keep stable renderer dependencies cacheable across application edits.
        strictExecutionOrder: true,
        codeSplitting: {
          groups: [
            { name: 'react-runtime', test: /node_modules[\\/](?:react|react-dom|scheduler)[\\/]/ },
            { name: 'terminal-webgl', test: /node_modules[\\/]@xterm[\\/]addon-webgl[\\/]/, priority: 20 },
            { name: 'terminal-runtime', test: /node_modules[\\/]@xterm[\\/]/ },
          ],
        },
      },
    },
  },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['desktop/test/setup.ts'],
    include: ['desktop/**/*.test.{ts,tsx}'],
  },
})
