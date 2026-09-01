import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// `base: "./"` makes built asset URLs relative, so the bundle loads from the `tauri://`
// origin in the desktop shell (absolute `/assets` 404s there); a server-hosted build is
// unaffected. Dev runs on a fixed port (1420) with strictPort so the Tauri webview always
// loads the vite instance Tauri itself spawns (a drifting port would make the window load a
// stale/other server). `tauri.conf.json` devUrl must match this.

// The version the user is actually running. Read from tauri.conf.json, NOT package.json:
// `Bump and tag` edits tauri.conf.json and release.yml refuses to build unless the git tag
// equals it, so that file is the one number that cannot drift from what shipped.
// Resolved against this config file, not the working directory, so it holds however the
// build is invoked (`npm run build --prefix surfaces/gui`, tauri's own spawn, or from the
// repo root).
function appVersion(): string {
  try {
    const conf = new URL("./src-tauri/tauri.conf.json", import.meta.url);
    return String(JSON.parse(fs.readFileSync(conf, "utf8")).version || "");
  } catch {
    // Loud, because the failure mode is otherwise invisible: the version row simply never
    // renders and the build still succeeds. Anyone moving this file should see why.
    console.warn("[vite] tauri.conf.json unreadable — the app-version row will be hidden");
    return "";
  }
}

export default defineConfig(({ command }) => {
  let devToken = "";
  if (command === "serve") {
    const state =
      process.env.COWORKER_STATE_DIR ||
      (process.platform === "win32"
        ? path.join(process.env.APPDATA || os.homedir(), "coworker")
        : path.join(os.homedir(), ".config", "coworker"));
    try {
      devToken = fs.readFileSync(path.join(state, "sidecar-8765.token"), "utf8").trim();
    } catch {
      // The Tauri dev shell injects its in-memory token at runtime. Plain browser dev
      // shows the normal startup retry until the standalone server/token file exists.
    }
  }
  return {
    base: "./",
    plugins: [react()],
    server: { port: 1420, strictPort: true },
    define: {
      __COWORKER_DEV_TOKEN__: JSON.stringify(devToken),
      __APP_VERSION__: JSON.stringify(appVersion()),
    },
    // Tauri CLI looks for these; harmless for the browser build.
    clearScreen: false,
    envPrefix: ["VITE_", "TAURI_"],
  };
});
