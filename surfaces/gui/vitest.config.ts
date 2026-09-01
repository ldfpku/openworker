import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Standalone test config (kept separate from vite.config.ts so the production `vite build` is
// untouched). Reused by later frontend phases — add new `*.test.tsx` files under src/.
export default defineConfig({
  plugins: [react()],
  // vite.config.ts injects this from tauri.conf.json; tests get a fixed stand-in so the
  // version row renders deterministically instead of depending on the current release number.
  define: { __APP_VERSION__: JSON.stringify("9.9.9") },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    // Mirrors main.tsx's pre-render initI18n() so components under test resolve through the
    // real catalog config (both key styles, separators off) — not a second, English-only init.
    setupFiles: ["src/setupTests.ts"],
  },
});
