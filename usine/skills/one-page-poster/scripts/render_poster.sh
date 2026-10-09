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
# 隔离：每次运行用**全新的临时 --user-data-dir**。不带它时 Chromium 落到
# 默认 profile，桌面浏览器若已开着，singleton 锁会把启动移交给现有进程、
# 退出 0 且不写截图。实测 macOS + Edge 上挂住不退的是**持久化** profile；
# 空目录规避了它。就算在别的环境再挂，timeout 兜底让它响亮地失败。
# 另：`--force-device-scale-factor` 保留本脚本自己的 $S（海报要 2x 出图），
# textlayer 固定 1 是因为它要 png 尺寸严格等于窗口尺寸。
PROFILE="$(mktemp -d)"
trap 'rm -rf "$PROFILE"' EXIT
BROWSER_CMD=("$BROWSER")
if command -v timeout >/dev/null 2>&1; then
  BROWSER_CMD=(timeout 120 "$BROWSER")
fi
"${BROWSER_CMD[@]}" --headless=new --disable-gpu --no-sandbox \
  --hide-scrollbars \
  --user-data-dir="$PROFILE" \
  --virtual-time-budget=10000 \
  --window-size="${W},${H}" \
  --force-device-scale-factor="${S}" \
  --screenshot="${OUT}" \
  "file://$(realpath "${IN}")${QS}"
if [[ ! -f "$OUT" ]]; then
  echo "浏览器退出 0 但没有写出 ${OUT}——大概率被已开着的桌面浏览器抢占（singleton 移交）。" >&2
  echo "关掉桌面浏览器后重试。" >&2
  exit 1
fi
echo "wrote ${OUT} ($((W*S))x$((H*S)))"
