"""Generate the inlined SMJAR brand assets used by the relay login pages.

Two outputs, same bytes:

  gemini-relay/worker/src/brand.ts   — the Cloudflare Worker's login/error pages
  coworker/brand_assets.py           — the sidecar's loopback landing page

Both inline the images as base64 rather than loading files. The Worker has no filesystem;
the sidecar ships as a PyInstaller bundle where an adjacent data directory is one more thing
to get wrong. And both sets of pages must render with no external requests — they are shown
precisely when something in the network path may be broken.

**Why PNG copies exist.** Our own pages use the webp originals (smaller, and we control the
browser). But Cloudflare's own settings fields validate the file extension and reject webp:

    logo_url must match the following: "/[^]+(.png|.svg|.jpg|.jpeg)$/"

That bites both the App Launcher logo and the Access login-page branding. So every mark is
also served as PNG, converted here at generation time. Nobody has to keep a second set of
source files in sync — there is still exactly one source image per mark.

Source images live in `surfaces/gui/src/brand/`. Replace them and re-run:

    .venv\\Scripts\\python.exe gemini-relay\\scripts\\gen_brand_assets.py

Requires Pillow (`uv pip install --python .venv/Scripts/python.exe pillow`). It is a
build-time-only dependency — nothing at runtime imports it.
"""

import base64
import io
import pathlib

from PIL import Image

# Paths are resolved from the repo root, wherever this script is invoked from.
ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "surfaces" / "gui" / "src" / "brand"
OUT_TS = ROOT / "gemini-relay" / "worker" / "src" / "brand.ts"
OUT_PY = ROOT / "coworker" / "brand_assets.py"

# name, source file, note. `inline` marks the three our own HTML pages embed as data URIs;
# the rest are only ever served over /brand/.
ASSETS = [
    ("LOGO_LIGHT", "logo.webp", "640x160 黑字，浅色背景用", True),
    ("LOGO_DARK", "logo-dark.webp", "640x160 白字，深色背景用", True),
    ("FAVICON", "favicon.webp", "64x64 标签页图标", True),
    ("LOGO_MARK", "logo-mark.webp", "256x256 方形徽标，App Launcher 用", False),
]

TS_HEADER = '''/**
 * SMJAR 品牌资源，base64 内联 —— 自动生成，请勿手改。
 *
 * A Worker has no filesystem and the login pages must render without a single external
 * request, so the bytes ride in the bundle. Source files live in
 * `surfaces/gui/src/brand/`; regenerate with `gemini-relay/scripts/gen_brand_assets.py`
 * after replacing them.
 *
 * The same marks are also served publicly at `/brand/...` so Cloudflare's branding settings
 * have a stable URL to point at (see docs/08-Access登录配置.md). Each is served as BOTH
 * webp and png: Cloudflare validates the file extension and rejects webp outright
 * (`logo_url must match the following: "/[^]+(.png|.svg|.jpg|.jpeg)$/"`), so the png copies
 * are the ones to hand to the App Launcher and the login-page branding.
 */

'''

TS_TAIL = '''export const LOGO_LIGHT_DATA_URI = "data:image/webp;base64," + LOGO_LIGHT_B64;
export const LOGO_DARK_DATA_URI = "data:image/webp;base64," + LOGO_DARK_B64;
export const FAVICON_DATA_URI = "data:image/webp;base64," + FAVICON_B64;

interface BrandFile {
  b64: string;
  type: string;
}

const FILES: Record<string, BrandFile> = {
%(files)s};

/** Decode base64 to bytes — atob gives us latin-1 chars, one per byte. */
function bytesFrom(b64: string): Uint8Array {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

/**
 * Serve the brand marks at a stable public URL. Cloudflare's branding settings take a logo
 * URL rather than an upload, and this is the one host in the story guaranteed to be
 * reachable from wherever the login page renders. Returns null for other paths.
 */
export function handleBrandRoutes(url: URL): Response | null {
  const file = FILES[url.pathname];
  if (!file) return null;
  return new Response(bytesFrom(file.b64), {
    headers: {
      "content-type": file.type,
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


def to_png(path: pathlib.Path) -> bytes:
    """The same image as PNG. `optimize` costs a moment here and saves bytes in every
    Worker deploy; the alpha channel is kept so the mark sits on any background."""
    buf = io.BytesIO()
    Image.open(path).convert("RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def main() -> None:
    encoded: dict[str, tuple[str, int]] = {}
    routes: list[tuple[str, str, str]] = []  # url path, const name, mime

    for name, filename, _note, _inline in ASSETS:
        stem = filename.rsplit(".", 1)[0]
        webp = (SRC / filename).read_bytes()
        png = to_png(SRC / filename)
        encoded[name] = (base64.b64encode(webp).decode("ascii"), len(webp))
        encoded[name + "_PNG"] = (base64.b64encode(png).decode("ascii"), len(png))
        routes.append(("/brand/%s.webp" % stem, name + "_B64", "image/webp"))
        routes.append(("/brand/%s.png" % stem, name + "_PNG_B64", "image/png"))

    files_block = "".join(
        '  "%s": { b64: %s, type: "%s" },\n' % (path, const, mime)
        for path, const, mime in routes
    )

    ts_parts = [TS_HEADER]
    for name, filename, note, _inline in ASSETS:
        stem = filename.rsplit(".", 1)[0]
        for suffix, ext in (("", "webp"), ("_PNG", "png")):
            b64, size = encoded[name + suffix]
            ts_parts.append("/** %s (%s.%s, %d bytes) */\n" % (note, stem, ext, size))
            ts_parts.append('const %s%s_B64 =\n  "%s";\n\n' % (name, suffix, b64))
    ts_parts.append(TS_TAIL % {"files": files_block})
    with io.open(OUT_TS, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(ts_parts))
    print("wrote %s (%d bytes)" % (OUT_TS, OUT_TS.stat().st_size))

    # The sidecar only ever renders the three inline marks; it has no /brand/ routes and no
    # need for the png copies.
    py_parts = [PY_HEADER]
    for name, filename, note, inline in ASSETS:
        if not inline:
            continue
        b64, size = encoded[name]
        py_parts.append("# %s (%s, %d bytes)\n" % (note, filename, size))
        py_parts.append('_%s_B64 = "%s"\n\n' % (name, b64))
    py_parts.append(PY_TAIL)
    with io.open(OUT_PY, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(py_parts))
    print("wrote %s (%d bytes)" % (OUT_PY, OUT_PY.stat().st_size))

    print("\n/brand/ 路由：")
    for path, _const, mime in routes:
        size = encoded[_const[:-4]][1]
        print("  %-28s %-11s %7d B" % (path, mime, size))


if __name__ == "__main__":
    main()
