import { defineConfig } from 'vitest/config';

// Minimal vitest config for A.6's apiFetch smoke. A.9 will expand to
// per-component tests (with happy-dom / jsdom) when the test harness
// proper lands.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.{js,jsx}'],
  },
});
