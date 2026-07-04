import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    globals: true,
    // Exclude the Playwright e2e specs (they use @playwright/test and must not
    // be collected by Vitest). Keep Vitest's default include so both tests/ and
    // src/ specs (e.g. the React mount check) are still discovered.
    exclude: ['tests/e2e/**', 'node_modules/**', 'dist/**'],
  },
});
