import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Standalone test config (kept separate from vite.config.ts so the production `vite build` is
// untouched). Reused by later frontend phases — add new `*.test.tsx` files under src/.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    // Mirrors main.tsx's pre-render initI18n() so components under test resolve through the
    // real catalog config (both key styles, separators off) — not a second, English-only init.
    setupFiles: ["src/setupTests.ts"],
  },
});
