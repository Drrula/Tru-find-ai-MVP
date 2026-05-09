import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: forwards both the legacy alias and /v1/* to the local backend.
// Production builds use VITE_API_BASE_URL (set per Railway environment per
// ADR-026) for absolute URLs; the proxy is only for dev convenience.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: true,
    proxy: {
      "/analyze-business": "http://localhost:8000",
      "/v1": "http://localhost:8000",
    },
  },
});
