import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    exclude: ["e2e/**", "node_modules/**"],
    globals: true,
    setupFiles: "./vitest.setup.ts",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
