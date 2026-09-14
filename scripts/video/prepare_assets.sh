#!/usr/bin/env bash
# Gather everything the film needs into video/public (all of it regenerable).
#   scripts/video/prepare_assets.sh <scratch-video-dir>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${1:?scratch video dir with audio/, clips/, Inspired.mp3}"
P="$ROOT/video/public"
mkdir -p "$P/audio" "$P/clips" "$P/music" "$P/fonts" "$P/screens/terminal" "$P/screens/aws" "$P/screens/ui" "$P/stills" "$ROOT/video/src/data"
cp "$SRC"/audio/*.mp3 "$P/audio/"
cp "$SRC"/audio/narration.json "$ROOT/video/src/data/narration.json"
cp "$SRC"/clips/*.mp4 "$P/clips/"
cp "$SRC"/Inspired.mp3 "$P/music/inspired.mp3"
cp "$ROOT"/docs/screens/terminal/*.png "$P/screens/terminal/"
cp "$ROOT"/docs/screens/aws/*.png "$P/screens/aws/"
cp "$ROOT"/docs/screens/ui/site-hero.png "$ROOT"/docs/screens/ui/orb-graph.png "$P/screens/ui/"
cp "$ROOT"/docs/screens/orb.png "$P/screens/orb.png"
cp "$ROOT"/docs/architecture.png "$P/stills/architecture.png"
# Fonts: the same three the app uses, fetched once from Google Fonts as woff2.
if [ ! -f "$P/fonts/InstrumentSans.woff2" ]; then
  UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
  css=$(curl -sA "$UA" "https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400..700&family=Comfortaa:wght@600..700&family=JetBrains+Mono:wght@400..500&display=swap")
  fetch() { url=$(printf '%s' "$css" | awk -v fam="$1" 'BEGIN{RS="@font-face"} $0 ~ "font-family: \x27"fam"\x27" && /U\+0000-00FF/ {match($0, /url\([^)]*\)/); print substr($0, RSTART+4, RLENGTH-5); exit}'); curl -sL "$url" -o "$P/fonts/$2"; }
  fetch "Instrument Sans" InstrumentSans.woff2; fetch "Comfortaa" Comfortaa.woff2; fetch "JetBrains Mono" JetBrainsMono.woff2
fi
ls -la "$P/fonts" | awk '{print $5, $NF}' | tail -3
echo "assets ready in video/public"
