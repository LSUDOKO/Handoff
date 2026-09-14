#!/usr/bin/env bash
# Render the film. Uses Playwright's Chromium so nothing else is downloaded.
#   scripts/video/render.sh [out.mp4]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$ROOT/video/out/handoff-demo.mp4}"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac   # absolute, since we cd below
CHROME=$(ls -d "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | tail -1)
cd "$ROOT/video"
mkdir -p "$(dirname "$OUT")"
npx remotion render src/index.ts HandoffDemo "$OUT" --gl=angle --timeout=180000 --concurrency="${CONCURRENCY:-6}" ${CHROME:+--browser-executable="$CHROME"} --log=warn
echo "rendered $OUT"
