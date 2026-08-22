"""Generate the inlined SMJAR brand assets used by the relay login pages.

Two outputs, same bytes:

  gemini-relay/worker/src/brand.ts   — the Cloudflare Worker's login/error pages
  coworker/brand_assets.py           — the sidecar's loopback landing page

Both inline the images as base64 rather than loading files. The Worker has no filesystem;
the sidecar ships as a PyInstaller bundle where an adjacent data directory is one more thing
to get wrong. And both sets of pages must render with no external requests — they are shown
precisely when something in the network path may be broken.

Source images live in `surfaces/gui/src/brand/`. Replace them and re-run:

    .venv\\Scripts\\python.exe gemini-relay\\scripts\\gen_brand_assets.py
"""

import base64
import io
import pathlib

# Paths are resolved from the repo root, wherever this script is invoked from.
ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "surfaces" / "gui" / "src" / "brand"
OUT_TS = ROOT / "gemini-relay" / "worker" / "src" / "brand.ts"
OUT_PY = ROOT / "coworker" / "brand_assets.py"

ASSETS = [
    ("LOGO_LIGHT", "logo.webp", "640x160 黑字，浅色背景用"),
    ("LOGO_DARK", "logo-dark.webp", "640x160 白字，深色背景用"),
    ("FAVICON", "favicon.webp", "64x64 标签页图标"),
]

TS_HEADER = '''/**
 * SMJAR 品牌资源，base64 内联 —— 自动生成，请勿手改。
 *
 * A Worker has no filesystem and the login pages must render without a single external
 * request, so the bytes ride in the bundle. Source files live in
 * `surfaces/gui/src/brand/`; regenerate with `gemini-relay/scripts/gen_brand_assets.py`
 * after replacing them.
 *
 * The same bytes are also served publicly at `/brand/...` so Cloudflare Access's
 * custom-branding setting has a stable URL to point the OTP login page at
 * (see docs/08-Access登录配置.md).
 */

'''

TS_TAIL = '''export const LOGO_LIGHT_DATA_URI = "data:image/webp;base64," + LOGO_LIGHT_B64;
export const LOGO_DARK_DATA_URI = "data:image/webp;base64," + LOGO_DARK_B64;
export const FAVICON_DATA_URI = "data:image/webp;base64," + FAVICON_B64;

const FILES: Record<string, string> = {
  "/brand/logo.webp": LOGO_LIGHT_B64,
  "/brand/logo-dark.webp": LOGO_DARK_B64,
  "/brand/favicon.webp": FAVICON_B64,
};

/** Decode base64 to bytes — atob gives us latin-1 chars, one per byte. */
function bytesFrom(b64: string): Uint8Array {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

/**
 * Serve the brand marks at a stable public URL. Cloudflare Access's custom branding takes a
 * logo URL rather than an upload, and this is the one host in the story guaranteed to be
 * reachable from wherever the login page renders. Returns null for other paths.
 */
export function handleBrandRoutes(url: URL): Response | null {
  const b64 = FILES[url.pathname];
  if (!b64) return null;
  return new Response(bytesFrom(b64), {
    headers: {
      "content-type": "image/webp",
      // A day is long enough to keep the Access login page snappy and short enough that a
      // logo swap propagates without anyone having to purge cache.
      "cache-control": "public, max-age=86400",
    },
  });
}
'''

PY_HEADER = '''"""SMJAR 品牌资源，base64 内联 —— 自动生成，请勿手改。

Regenerate with `gemini-relay/scripts/gen_brand_assets.py` after replacing the source webp
files in `surfaces/gui/src/brand/`. Inlined rather than shipped as data files because the
loopback pages that use them must render with no external requests, and because the
PyInstaller bundle has no reliable notion of an adjacent asset directory.
"""

'''

PY_TAIL = '''LOGO_LIGHT_DATA_URI = "data:image/webp;base64," + _LOGO_LIGHT_B64
LOGO_DARK_DATA_URI = "data:image/webp;base64," + _LOGO_DARK_B64
FAVICON_DATA_URI = "data:image/webp;base64," + _FAVICON_B64
'''


def main() -> None:
    encoded = {}
    for name, filename, _note in ASSETS:
        data = (SRC / filename).read_bytes()
        encoded[name] = (base64.b64encode(data).decode("ascii"), filename, len(data))

    ts_parts = [TS_HEADER]
    for name, filename, note in ASSETS:
        b64, _fn, size = encoded[name]
        ts_parts.append("/** %s (%s, %d bytes) */\n" % (note, filename, size))
        ts_parts.append('const %s_B64 =\n  "%s";\n\n' % (name, b64))
    ts_parts.append(TS_TAIL)
    with io.open(OUT_TS, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(ts_parts))
    print("wrote %s (%d bytes)" % (OUT_TS, OUT_TS.stat().st_size))

    py_parts = [PY_HEADER]
    for name, filename, note in ASSETS:
        b64, _fn, size = encoded[name]
        py_parts.append("# %s (%s, %d bytes)\n" % (note, filename, size))
        py_parts.append('_%s_B64 = "%s"\n\n' % (name, b64))
    py_parts.append(PY_TAIL)
    with io.open(OUT_PY, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(py_parts))
    print("wrote %s (%d bytes)" % (OUT_PY, OUT_PY.stat().st_size))


if __name__ == "__main__":
    main()
