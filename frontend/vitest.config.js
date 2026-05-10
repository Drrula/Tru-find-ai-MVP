import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Vitest config. Loads @vitejs/plugin-react so .jsx files transform
// correctly (otherwise tests crash with "React is not defined").
//
// Default environment is `node` (fast, no DOM). Component tests opt
// into happy-dom via `// @vitest-environment happy-dom` directive at
// the top of the file (e.g. ResultsPage.test.jsx).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'node',
    include: ['src/**/*.test.{js,jsx}'],
  },
});
