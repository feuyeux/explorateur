#!/usr/bin/env bash
# Render the poster HTML to PNG with headless Chromium, fully deterministic.
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

# 浏览器解析**走 library 这一个事实源**（feuille.platform），不自己写死名字。
# 原版硬编码 `google-chrome`：SKILL.md 却写着「可用 $CHROME_BIN 覆盖」——
# 既不支持覆盖，又在只有 Edge 的机器（如本机）上直接失败。
# 优先级：$CHROME_BIN > library 的 platform.browser_path()。
if [[ -n "${CHROME_BIN:-}" ]]; then
  BROWSER="$CHROME_BIN"
else
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
  BROWSER="$(uv run --project "$REPO_ROOT" python -c \
    'from feuille import platform; print(platform.browser_path() or "")' 2>/dev/null || true)"
fi
if [[ -z "$BROWSER" ]]; then
  echo "找不到可用的 Chromium 系浏览器。" >&2
  echo "装 Chrome 或 Edge，或设 CHROME_BIN 指向浏览器可执行文件。" >&2
  exit 1
fi

# 参数与 library 的 `textlayer._shot_args` 对齐（实测过的组合）。
# ⚠️ **不要加 --user-data-dir**：实测在 macOS + Edge 上，带它截图能出图但
# **进程永不退出**（脚本永久挂住）。原注释说它是防止桌面浏览器抢占启动——
# 但 `--headless=new` 下不需要，textlayer 一直没有它。
# 另：`--force-device-scale-factor` 保留本脚本自己的 $S（海报要 2x 出图），
# textlayer 固定 1 是因为它要 png 尺寸严格等于窗口尺寸。
"$BROWSER" --headless=new --disable-gpu --no-sandbox \
  --hide-scrollbars \
  --virtual-time-budget=10000 \
  --window-size="${W},${H}" \
  --force-device-scale-factor="${S}" \
  --screenshot="${OUT}" \
  "file://$(realpath "${IN}")${QS}"
echo "wrote ${OUT} ($((W*S))x$((H*S)))"
