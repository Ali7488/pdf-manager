/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

/**
 * Vite config.
 *
 * The desktop app loads `dist/index.html` straight from disk as a file:// URL
 * (no web server). Chromium/WebView2 blocks module scripts and font fetches
 * from file://, so the build produces ONE self-contained `dist/index.html`:
 * vite-plugin-singlefile inlines the JS and CSS, and every asset (the Open Sans
 * font files) is inlined as a data URI. `base: "./"` keeps any leftover URL
 * relative.
 */
export default defineConfig({
  base: "./",
  plugins: [react(), viteSingleFile({ removeViteModuleLoader: true })],
  build: {
    // WebView2 on Windows 11 is evergreen Chromium, so modern output is fine.
    target: "es2022",
    // Inline every asset (fonts included) instead of emitting files.
    assetsInlineLimit: Number.MAX_SAFE_INTEGER,
    cssCodeSplit: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
  },
});
