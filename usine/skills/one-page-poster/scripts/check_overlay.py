#!/usr/bin/env python3
"""Layer-registration check for two-layer overlays (see
references/script-coloring.md). Compares SINGLE-LAYER renders:

  lay render = full text layer alone  (bottom, e.g. red)
  top render = consonant-only layer alone (top, e.g. blue)

Measures, inside the word rectangle: best integer shift of the top mask, the
unmatched top-color fraction at that shift, and red-only/blue-only counts.
Acceptance: best shift (0,0) and unmatched ≈ 0 % (residual = antialiasing).

Usage:
  check_overlay.py <lay.png> <top.png> <x> <y> <w> <h> [--scale 2]
                   [--red c9403a] [--blue 2f5d9e]

x/y/w/h are CSS px (they get multiplied by --scale for the device-pixel PNG).
Produce the single-layer renders by injecting
`.stack .top { visibility:hidden }` (→ lay render) or
`.stack .lay { visibility:hidden }` (→ top render) into the built HTML.

IMPORTANT: never measure registration on the composite (both layers visible) —
the top layer paints over the bottom, so overlap pixels are hidden and every
metric lies. Single-layer renders only.
"""
import argparse

def _ensure_deps():
    try:
        import numpy, PIL  # noqa
        return
    except ImportError:
        pass
    import os, subprocess, sys
    from pathlib import Path
    # portable re-exec: locate the usine uv project (its pyproject pins numpy+Pillow)
    # and run this script there — no machine-specific env layout assumed
    usine = None
    for anc in Path(__file__).resolve().parents:
        if (anc / "pyproject.toml").is_file() and (anc / "src" / "feuille").is_dir():
            usine = anc
            break
        if (anc / "usine" / "pyproject.toml").is_file():
            usine = anc / "usine"
            break
    if usine and subprocess.run(["uv", "--version"], capture_output=True).returncode == 0:
        os.execvp("uv", ["uv", "run", "--project", str(usine), "python",
                         str(Path(__file__).resolve()), *sys.argv[1:]])
    raise SystemExit("need numpy + Pillow: "
                     "install uv and run via `uv run --project usine python <script>`")

_ensure_deps()
import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("lay_png")
ap.add_argument("top_png")
ap.add_argument("x", type=int); ap.add_argument("y", type=int)
ap.add_argument("w", type=int); ap.add_argument("h", type=int)
ap.add_argument("--scale", type=int, default=2)
ap.add_argument("--red", default="c9403a")
ap.add_argument("--blue", default="2f5d9e")
ap.add_argument("--radius", type=int, default=4, help="shift search radius (device px)")
a = ap.parse_args()

def hx(s): return tuple(int(s[i:i+2], 16) for i in range(0, 6, 2))

def mask(path, t):
    im = np.asarray(Image.open(path).convert("RGB")).astype(int)
    x0, y0, w, h = a.x*a.scale, a.y*a.scale, a.w*a.scale, a.h*a.scale
    sub = im[y0:y0+h, x0:x0+w]
    return (np.abs(sub - np.array(t)).max(axis=2) <= 45)

R = mask(a.lay_png, hx(a.red))
B = mask(a.top_png, hx(a.blue))
print(f"bottom ink {R.sum()}  top ink {B.sum()}")
best = sorted((int((np.roll(np.roll(B, dy, 0), dx, 1) & ~R).sum()), dx, dy)
              for dx in range(-a.radius, a.radius+1)
              for dy in range(-a.radius, a.radius+1))
un, dx, dy = best[0]
frac = 100*un/max(int(B.sum()), 1)
print(f"best shift dx={dx} dy={dy}  unmatched_top={un}/{int(B.sum())} ({frac:.2f}%)")
Ronly = int((R & ~B).sum()); Bonly = int((B & ~R).sum())
print(f"bottom-only (vowel glyphs expected): {Ronly}   top-only (misregistration+aa): {Bonly}")
ok = (dx, dy) == (0, 0) and frac < 2.0
print("PASS" if ok else "FAIL — layers misregistered")
raise SystemExit(0 if ok else 1)
