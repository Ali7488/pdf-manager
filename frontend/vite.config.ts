/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * Vite config.
 *
 * `base: "./"` makes every asset URL relative, so the built `dist/index.html`
 * works when pywebview loads it straight from disk (no web server).
 */
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    // WebView2 on Windows 11 is evergreen Chromium, so modern output is fine.
    target: "es2022",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
  },
});
