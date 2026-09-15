#!/usr/bin/env bash
# Download one platform's prebuilt sherpa-onnx static-link archive, verify it against
# packaging/sherpa-onnx-archives.sha256, and leave it in a directory ready to hand to
# sherpa-onnx-sys as SHERPA_ONNX_ARCHIVE_DIR (build.rs looks for the archive FILE itself in
# that directory — it does its own extraction, so we don't unpack anything here).
#
# Shared by .github/workflows/release.yml, .github/workflows/ci.yml (rust-unit job), and the
# local packaging/build_windows.ps1 / build_dmg.sh scripts, so every caller downloads and
# checks the exact same bytes.
#
# Usage:
#   scripts/fetch-sherpa-archive.sh <platform> [dest-dir]
#
#   <platform>  one of: windows | macos-arm64 | macos-x64 | linux-x64
#   [dest-dir]  where to put the archive (default: $RUNNER_TEMP/sherpa, or ./sherpa when
#               RUNNER_TEMP is unset — e.g. a local run outside CI)
#
# On success prints the destination directory as the LAST line of stdout (all other output
# goes to stderr), so callers can do:
#   DIR="$(scripts/fetch-sherpa-archive.sh windows "$RUNNER_TEMP/sherpa")"
#   echo "SHERPA_ONNX_ARCHIVE_DIR=$DIR" >> "$GITHUB_ENV"
#
# Idempotent: if the destination already holds a file with the expected name AND hash (e.g.
# a locally pre-seeded cache), the download is skipped.
set -euo pipefail

# Must track the `sherpa-onnx = "=X.Y.Z"` pin in stt/Cargo.toml — build.rs derives the
# release download URL from that exact crate version.
SHERPA_ONNX_VERSION="1.13.7"
RELEASE_BASE_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/v${SHERPA_ONNX_VERSION}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECKSUMS_FILE="$REPO_ROOT/packaging/sherpa-onnx-archives.sha256"

PLATFORM="${1:?usage: fetch-sherpa-archive.sh <windows|macos-arm64|macos-x64|linux-x64> [dest-dir]}"
DEST_DIR="${2:-${RUNNER_TEMP:-.}/sherpa}"

log() { echo "$@" >&2; }

case "$PLATFORM" in
  windows)     PATTERN="win-x64-static-MT-Release" ;;
  macos-arm64) PATTERN="osx-arm64-static" ;;
  macos-x64)   PATTERN="osx-x64-static" ;;
  linux-x64)   PATTERN="linux-x64-static" ;;
  *)
    log "ERROR: unknown platform '$PLATFORM' (expected windows|macos-arm64|macos-x64|linux-x64)"
    exit 1
    ;;
esac

[ -f "$CHECKSUMS_FILE" ] || { log "ERROR: checksums file not found: $CHECKSUMS_FILE"; exit 1; }

# Ignore comment/blank lines, match the platform's filename fragment, then require exactly
# one hit — a stale/duplicate entry after a version bump must fail loudly, not pick one at
# random.
MATCHES="$(grep -v '^[[:space:]]*#' "$CHECKSUMS_FILE" | grep -v '^[[:space:]]*$' | grep -- "$PATTERN" || true)"
MATCH_COUNT="$(printf '%s\n' "$MATCHES" | grep -c . || true)"
if [ "$MATCH_COUNT" -ne 1 ]; then
  log "ERROR: expected exactly 1 entry matching '$PATTERN' in $CHECKSUMS_FILE, found $MATCH_COUNT"
  exit 1
fi

EXPECTED_SHA256="$(printf '%s\n' "$MATCHES" | awk '{print $1}')"
FILENAME="$(printf '%s\n' "$MATCHES" | awk '{print $2}')"

sha256_of() {
  local f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$f" | awk '{print $1}'
  else
    openssl dgst -sha256 "$f" | awk '{print $NF}'
  fi
}

mkdir -p "$DEST_DIR"
# Normalize to a forward-slash path (`cd && pwd`, same trick as REPO_ROOT above). On a
# Windows runner/shell, a caller-supplied $RUNNER_TEMP-style dest ("D:\a\_temp\xyz") makes
# GNU coreutils' sha256sum treat the backslashes as needing escaping and prefix its output
# with a stray "\", corrupting the hash comparison below — this sidesteps that entirely.
DEST_DIR="$(cd "$DEST_DIR" && pwd)"
ARCHIVE_PATH="$DEST_DIR/$FILENAME"

# ...but the path we PRINT must be one the CALLER's shell understands, and that is not the
# same string. Under Git-Bash (MINGW64) on a Windows runner the POSIX $DEST_DIR above reads
# "/d/a/_temp/sherpa". Git-Bash rewrites such values when it spawns a native child itself,
# but our callers do not go through Git-Bash: release.yml writes this line into $GITHUB_ENV
# and a later `shell: pwsh` step hands it to cargo.exe, where sherpa-onnx-sys's build.rs
# hard-errors ("SHERPA_ONNX_ARCHIVE_DIR does not contain expected archive") instead of
# falling back to downloading; build_windows.ps1 likewise resolves "/d/a/..." to
# "C:\d\a\..." and silently skips its own sha256 check. So: hash with the POSIX path,
# print the native one.
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) OUT_DIR="$(cygpath -m "$DEST_DIR")" ;;
  *)                    OUT_DIR="$DEST_DIR" ;;
esac

if [ -f "$ARCHIVE_PATH" ]; then
  ACTUAL_SHA256="$(sha256_of "$ARCHIVE_PATH")"
  if [ "$ACTUAL_SHA256" = "$EXPECTED_SHA256" ]; then
    log "==> $FILENAME already present and verified at $OUT_DIR — skipping download"
    echo "$OUT_DIR"
    exit 0
  fi
  log "==> $ARCHIVE_PATH exists but hash does not match — re-downloading"
  rm -f "$ARCHIVE_PATH"
fi

log "==> downloading $FILENAME ($RELEASE_BASE_URL/$FILENAME)"
curl -fSL --retry 3 --retry-delay 2 -o "$ARCHIVE_PATH" "$RELEASE_BASE_URL/$FILENAME"

ACTUAL_SHA256="$(sha256_of "$ARCHIVE_PATH")"
if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
  log "ERROR: sha256 mismatch for $FILENAME"
  log "  expected: $EXPECTED_SHA256"
  log "  actual:   $ACTUAL_SHA256"
  rm -f "$ARCHIVE_PATH"
  exit 1
fi

log "==> sha256 OK: $FILENAME"
echo "$OUT_DIR"
