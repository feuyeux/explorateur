#!/usr/bin/env bash
# Render the poster HTML to PNG with headless Chrome, fully deterministic.
# Usage: render_poster.sh <in.html[?query]> <out.png> [css_width] [css_height] [scale]
#   A query string is honored (e.g. cover_src.html?fmt=P for the portrait
#   cover variant) — WITHOUT it make_covers.py's boot script silently renders
#   the LANDSCAPE geometry and every downstream check misfires.
set -euo pipefail
IN=${1:?in.html}
QS=""
case "$IN" in
  *\?*) QS="?${IN#*\?}"; IN="${IN%%\?*}" ;;
esac
OUT=${2:?out.png}
W=${3:-1240}
H=${4:-1754}
S=${5:-2}
# --user-data-dir: isolated profile — a running desktop Chrome would hijack the
# launch and screenshot its Google new-tab page
google-chrome --headless --disable-gpu --no-sandbox \
  --virtual-time-budget=10000 \
  --user-data-dir="/tmp/headless-chrome-$$" \
  --window-size="${W},${H}" \
  --force-device-scale-factor="${S}" \
  --hide-scrollbars \
  --screenshot="${OUT}" \
  "file://$(realpath "${IN}")${QS}"
echo "wrote ${OUT} ($((W*S))x$((H*S)))"
