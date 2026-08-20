import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Standalone test config (kept separate from vite.config.ts so the production `vite build` is
// untouched). Reused by later frontend phases — add new `*.test.tsx` files under src/.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    // Mirrors main.tsx's pre-render initLocale() so react-i18next interpolates in tests
    // exactly as in the app (English output stays byte-identical — keys ARE the strings).
    setupFiles: ["src/setupTests.ts"],
  },
});
