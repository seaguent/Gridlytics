import { defineConfig } from "vitest/config";

export default defineConfig({
  define: { __API_BASE_URL__: JSON.stringify("http://127.0.0.1:8001") },
  test: {
    setupFiles: ["./tests/setup.ts"],
  },
});
