#!/usr/bin/env python3
"""Pixel verification of the rendered poster.png: grid detection + per-cell
color statistics. Catches empty cells, missing colors, tofu (no ink where a
big word should be).

Usage: verify_colors.py <poster.png> [--cols 3] [--rows 4] [--langs a,b,c]
                          [--line d9cdb7]
(grid-line detection is scale-agnostic — works on any render scale)
Color targets (tol 45): --red c9403a --blue 2f5d9e --gray a2967f --ink 2c2620
Edit the targets to the poster's palette. A cell with zero red or zero blue
is reported as a problem (pass --allow-missing blue for red-only posters).
"""
import argparse

def _ensure_deps():
    try:
        import PIL  # noqa
        return
    except ImportError:
        pass
    import os, subprocess, sys
    from pathlib import Path
    # portable re-exec: locate the usine uv project (its pyproject pins Pillow)
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
    raise SystemExit("need Pillow (and numpy for check_overlay.py): "
                     "install uv and run via `uv run --project usine python <script>`")

_ensure_deps()
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("png")
ap.add_argument("--cols", type=int, default=3)
ap.add_argument("--rows", type=int, default=4)
ap.add_argument("--langs", default="")
ap.add_argument("--line", default="d9cdb7")
ap.add_argument("--red", default="c9403a")
ap.add_argument("--blue", default="2f5d9e")
ap.add_argument("--gray", default="a2967f")
ap.add_argument("--ink", default="2c2620")
ap.add_argument("--allow-missing", default="", help="comma list: red,blue,gray,ink")
a = ap.parse_args()

def hx(s): return tuple(int(s[i:i+2], 16) for i in range(0, 6, 2))
TARGETS = {"red": hx(a.red), "blue": hx(a.blue), "gray": hx(a.gray), "ink": hx(a.ink)}
LANGS = a.langs.split(",") if a.langs else [f"cell{i+1}" for i in range(a.cols*a.rows)]

im = Image.open(a.png).convert("RGB")
W, H = im.size
px = im.load()

def close(p, t, tol=45):
    return all(abs(p[i]-t[i]) <= tol for i in range(3))

# ---- grid line detection ----
LINE = hx(a.line)
ys_probe = range(int(H*0.25), int(H*0.95), 7)
vcols = [x for x in range(W) if sum(close(px[x, y], LINE, 18) for y in ys_probe) > len(list(ys_probe))*0.6]
def cluster(vals):
    out = []
    for v in vals:
        if out and v - out[-1][-1] <= 2: out[-1].append(v)
        else: out.append([v])
    return [sum(c)/len(c) for c in out]
vlines = cluster(vcols)
xs_probe = range(int(W*0.05), int(W*0.95), 7)
hrows = [y for y in range(H) if sum(close(px[x, y], LINE, 18) for x in xs_probe) > len(list(xs_probe))*0.6]
hlines = cluster(hrows)
print(f"vertical lines: {[round(v,1) for v in vlines]}")
print(f"horizontal lines: {[round(v,1) for v in hlines]}")

assert len(vlines) >= a.cols + 1 and len(hlines) >= a.rows + 1, "grid not found"

problems = []
k = 0
for r in range(a.rows):
    for c in range(a.cols):
        x0, x1 = int(vlines[c])+3, int(vlines[c+1])-3
        y0, y1 = int(hlines[r])+3, int(hlines[r+1])-3
        cnt = {kk: 0 for kk in TARGETS}
        for yy in range(y0, y1, 2):      # step 2: sample, enough for presence stats
            for xx in range(x0, x1, 2):
                p = px[xx, yy]
                for kk, t in TARGETS.items():
                    if close(p, t):
                        cnt[kk] += 1
                        break
        name = LANGS[k] if k < len(LANGS) else f"cell{k+1}"
        k += 1
        print(f"{name:10s} red={cnt['red']:6d} blue={cnt['blue']:6d} gray={cnt['gray']:5d} ink={cnt['ink']:6d}")
        allow = a.allow_missing.split(",") if a.allow_missing else []
        for kk in ("red", "blue", "gray", "ink"):
            if cnt[kk] == 0 and kk not in allow:
                problems.append(f"{name}: NO {kk} pixels")

print()
if problems:
    print("PROBLEMS:")
    for p in problems: print(" -", p)
    raise SystemExit(1)
print("all cells OK")
