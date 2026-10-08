#!/usr/bin/env python3
"""Measure Korean syllable-block color patches from real ink — self-verifying.

The Korean in-glyph coloring method (see references/script-coloring.md) paints
each jamo's ink red (vowel) / blue (consonant) with hard-edged background
patches clipped to the glyph via `background-clip:text`. Patch geometry is
glyph-specific: NEVER reuse measured fractions across themes/fonts — measure
each syllable.

Per input syllable this script:
  1. decomposes it into jamo (NFD) → knows which jamo are vowels (medial) and
     which are consonants (initial / final);
  2. builds a measurement page (one huge .ksyl per syllable, font stack and
     subset css IDENTICAL to the real poster — pass --css), renders it with
     headless Chrome (--dump-dom for element rects, --screenshot for ink);
  3. flood-fills ink components and labels each one vowel/consonant using
     the medial jamo's geometry prior (NFD gives the medial codepoint):
       - final (if present): component reaching into the bottom band
         (ymax > top + 80% of the ink height) — the medial never dips that low;
       - vertical medial strokes (ㅏ ㅓ ㅣ ㅐ …) live in the right half:
         a non-final component centered right of 50% of the ink width is vowel;
       - medials U+1169..U+1174 (ㅗ ㅜ ㅡ and compounds ㅘ..ㅢ) also draw
         horizontal ink low: the bottom group of the non-final components
         (centers within 15% of the ink height of the lowest) is vowel;
       - everything else is the initial — which may be several components
         (ㅎ is an arc plus a ring; both are consonant);
     so compound vowels (ㅝ ㅘ …) spanning several components and verticals
     that stop above a final (ㅣ in 일) are handled by the label rules, not
     by a fixed bar height;
  4. covers the vowel ink (grown by --margin, minus the consonant ink grown by
     the same margin) with at most 12 rectangles (greedy largest-rectangle
     cover of the pixel mask) and prints them as a paste-ready CSS rule:
     N red layers (2-value percentage positions, see emit_rule) over one
     full-box blue layer. Fractions are relative to the element box
     (advance × line-height), so they transfer to any font-size;
  5. VERIFY: renders the emitted CSS for real (transparent text + patches)
     and compares every ink pixel's color against the labels — prints
     PASS/FAIL per syllable and exits nonzero on any FAIL, so a bad rule
     (wrong percentage semantics, tight kerning, over-capped rectangles)
     fails loudly instead of mispainting the poster. Note the verify pass
     checks that the CSS reproduces the LABELS in real Chrome — the jamo
     truth of the labels themselves is the printed component table, which
     the operator must sanity-check against the jamo decomposition line.

Hard limits, by design:
  - if vowel ink TOUCHES consonant ink (ㅓ's tick reaches the ㅇ in 어, ㅜ sits
    on the final ㄱ in 국 — both in OBS KR), the syllable renders as ONE
    component and no per-component labeling can split it: the script prints
    the component table and fails loudly. --vowel-comp cannot fix a merged
    component; use a wording that avoids merged syllables, or fall back to
    a whole-syllable treatment for that glyph;
  - ㅛ/ㅠ stack two cups around mid-height; the top cup can fall outside both
    geometry rules — check the table and override with --vowel-comp.

Hand-tightening is allowed but MUST keep: all vowel ink covered, no consonant
ink inside a red rectangle, ≥margin px between red rectangles and consonant
ink, and the verify pass green.

Usage:
    measure_korean.py 차 한 잔 --family "OBS KR" --css fonts.css [--out DIR]
    measure_korean.py 한 --css fonts.css            # family read from css @font-face
    measure_korean.py 원 --css fonts.css --vowel-comp 2,3   # override labels (1-based)

Requires: google-chrome (or $CHROME_BIN), Pillow + numpy (uv run --project usine).
"""
import argparse, json, pathlib, re, subprocess, sys, tempfile, unicodedata

CHROME = None  # resolved in main
RED, BLUE = (0xC9, 0x40, 0x3A), (0x2F, 0x5D, 0x9E)  # --vowel / --cons


def _ensure_deps():
    try:
        import numpy, PIL  # noqa
    except ImportError:
        sys.exit("Pillow + numpy required — run inside the usine uv project "
                  "(uv run --project usine python measure_korean.py …)")


BUILD_TPL = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
%(css)s
body { margin: 0; background: #fff; }
.row { padding-top: %(rowpad)dpx; padding-left: 100px; }
.ksyl { display: inline-block; font-size: %(fs)dpx; line-height: 1.28;
        font-family: %(family)s; color: #000; }
pre { position: absolute; top: 0; left: -9999px; }
</style></head><body>
%(rows)s
<pre id="rects">RECTS {}</pre>
<script>
const out = {};
for (const el of document.querySelectorAll(".ksyl")) {
  const r = el.getBoundingClientRect();
  out[el.id] = [r.x, r.y, r.width, r.height];
}
document.getElementById("rects").textContent = "RECTS " + JSON.stringify(out);
</script></body></html>"""

VERIFY_TPL = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
%(css)s
:root { --vowel: #c9403a; --cons: #2f5d9e; }
body { margin: 0; background: #fff; }
.row { padding-top: %(rowpad)dpx; padding-left: 100px; }
.ksyl { display: inline-block; font-size: %(fs)dpx; line-height: 1.28;
        font-family: %(family)s; background-repeat: no-repeat; }
.gap { display: inline-block; width: 80px; }
.gt { color: #000; }
.pt { color: transparent; -webkit-background-clip: text; background-clip: text; }
%(rules)s
pre { position: absolute; top: 0; left: -9999px; }
</style></head><body>
%(rows)s
<pre id="rects">RECTS {}</pre>
<script>
const out = {};
for (const el of document.querySelectorAll(".ksyl")) {
  const r = el.getBoundingClientRect();
  out[el.id] = [r.x, r.y, r.width, r.height];
}
document.getElementById("rects").textContent = "RECTS " + JSON.stringify(out);
</script></body></html>"""


def render_chrome(url, w, h, out=None, dom=False):
    cmd = [CHROME, "--headless", "--disable-gpu", "--no-sandbox",
           "--virtual-time-budget=10000",
           "--user-data-dir=" + tempfile.mkdtemp(prefix="mk-chrome-"),
           "--window-size=%d,%d" % (w, h), "--force-device-scale-factor=1",
           "--hide-scrollbars"]
    cmd += (["--dump-dom", url] if dom else ["--screenshot=" + out, url])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        sys.exit(f"chrome failed: {r.stderr[:500]}")
    return r.stdout


def label_components(mask):
    """8-connectivity components; returns list of (ys, xs) index arrays."""
    import numpy as np
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]
        seen[y0, x0] = True
        pts = []
        while stack:
            y, x = stack.pop()
            pts.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] \
                       and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        comps.append((np.array([p[0] for p in pts]), np.array([p[1] for p in pts])))
    return comps


def dilate(mask, r):
    """Boolean dilation by a square structuring element of radius r."""
    import numpy as np
    if r <= 0:
        return mask.copy()
    H, W = mask.shape
    out = np.zeros_like(mask)
    for dy in range(-r, r + 1):
        ys0, ys1 = max(0, dy), min(H, H + dy)
        for dx in range(-r, r + 1):
            xs0, xs1 = max(0, dx), min(W, W + dx)
            out[ys0:ys1, xs0:xs1] |= mask[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


def largest_rect(mask):
    """Largest all-True axis-aligned rectangle: (area, x0, y0, x1, y1) or None."""
    H, W = mask.shape
    h = [0] * (W + 1)
    best = None
    for y in range(H):
        row = mask[y]
        for x in range(W):
            h[x] = h[x] + 1 if row[x] else 0
        stack = []
        for x in range(W + 1):
            cur = h[x] if x < W else 0
            start = x
            while stack and stack[-1][1] > cur:
                sx, sh = stack.pop()
                area = sh * (x - sx)
                if best is None or area > best[0]:
                    best = (area, sx, y - sh + 1, x - 1, y)
                start = sx
            if not stack or stack[-1][1] < cur:
                stack.append((start, cur))
    return best


def rect_cover(mask, cap=12):
    """Greedy largest-rectangle cover, then horizontal-strip fallback for the
    thin-stroke slivers the greedy pass leaves; returns (rects, uncovered)."""
    import numpy as np
    rects = []
    m = mask.copy()
    while m.any() and len(rects) < cap:
        r = largest_rect(m)
        if not r or r[0] == 0:
            break
        _, x0, y0, x1, y1 = r
        rects.append([x0, y0, x1, y1])
        m[y0:y1 + 1, x0:x1 + 1] = False
    H, W = m.shape
    while m.any() and len(rects) < cap:
        ys, xs = np.nonzero(m)
        i = np.lexsort((xs, ys))[0]          # topmost, then leftmost pixel
        y, x = int(ys[i]), int(xs[i])
        x0 = x
        while x0 > 0 and m[y, x0 - 1]:
            x0 -= 1
        x1 = x
        while x1 + 1 < W and m[y, x1 + 1]:
            x1 += 1
        y1 = y
        while y1 + 1 < H and m[y1 + 1, x0:x1 + 1].all():
            y1 += 1
        rects.append([x0, y, x1, y1])
        m[y:y1 + 1, x0:x1 + 1] = False
    return rects, m


def expand_rects(rects, forbidden, shape):
    """Grow each rect by any amount on each edge, but only into ~forbidden
    area (empty space or own-color room); keeps the safety margin intact."""
    H, W = shape
    f = forbidden
    for r in rects:
        x0, y0, x1, y1 = r
        while x0 > 0 and not f[y0:y1 + 1, x0 - 1].any():
            x0 -= 1
        while y0 > 0 and not f[y0 - 1, x0:x1 + 1].any():
            y0 -= 1
        while x1 + 1 < W and not f[y0:y1 + 1, x1 + 1].any():
            x1 += 1
        while y1 + 1 < H and not f[y1 + 1, x0:x1 + 1].any():
            y1 += 1
        r[0], r[1], r[2], r[3] = x0, y0, x1, y1


def erode(mask, r):
    """Boolean erosion (inverse of dilate)."""
    return ~dilate(~mask, r)


def dedupe_rects(rects):
    """Drop rects fully contained in another (expansion often makes strips
    converge to the same maximal band)."""
    keep = []
    for r in sorted(rects, key=lambda r: -((r[2] - r[0] + 1) * (r[3] - r[1] + 1))):
        if not any(k[0] <= r[0] and k[1] <= r[1] and k[2] >= r[2] and k[3] >= r[3]
                   for k in keep):
            keep.append(r)
    return keep


def cover_vowel(red, blue, margin):
    """Rect patches painting all `red` ink red, ≥margin clear of `blue` ink.
    Antialiased masks are ragged (1px holes), so cover a closed core first,
    expand into safe space, then strip-cover whatever real ink is still bare.
    Returns (rects, error|None)."""
    import numpy as np
    if (red & blue).any():
        return None, "vowel and consonant ink overlap"
    forbidden = dilate(blue, margin)
    core = erode(dilate(red, 2), 2)
    rects, _ = rect_cover(core, cap=12)
    expand_rects(rects, forbidden, red.shape)

    def uncovered():
        u = np.zeros_like(red)
        for x0, y0, x1, y1 in rects:
            u[y0:y1 + 1, x0:x1 + 1] = True
        return red & ~u

    if uncovered().any():
        extra, _ = rect_cover(uncovered(), cap=4)
        expand_rects(extra, forbidden, red.shape)
        rects += extra
    rects = dedupe_rects(rects)
    if uncovered().any():
        return None, f"{int(uncovered().sum())} vowel px not coverable"
    for x0, y0, x1, y1 in rects:           # blue ink must never sit in a red rect
        if blue[y0:y1 + 1, x0:x1 + 1].any():
            return None, "patch would paint consonant ink red"
    return rects, None


def jamo_decomp(syl):
    """NFD jamo of one Hangul syllable -> (initial, medial, final|None)."""
    d = unicodedata.normalize("NFD", syl)
    if len(d) < 2 or not all(0x1100 <= ord(c) <= 0x11FF for c in d):
        sys.exit(f"{syl!r}: expected one precomposed Hangul syllable")
    L, V = d[0], d[1]
    T = d[2] if len(d) > 2 else None
    if not (0x1100 <= ord(L) <= 0x1112) or not (0x1161 <= ord(V) <= 0x1175) \
       or (T is not None and not 0x11A8 <= ord(T) <= 0x11C2):
        sys.exit(f"{syl!r}: unexpected jamo decomposition {d!r}")
    return L, V, T


def classify(comps, has_t, medial_cp):
    """Label each ink component 'V' or 'C'; returns (labels, error|None).

    Geometry priors from the medial jamo (codepoint U+1161..U+1175):
    - medials U+1169..U+1174 draw at least one horizontal stroke (ㅗ ㅜ ㅡ
      and the compounds ㅘ..ㅢ); the rest (ㅏㅐㅑㅒㅓㅔㅕㅖㅣ) are vertical
      strokes in the right column.
    Rules, in order:
    1. final band: components reaching the bottom 20% of the ink are the
       final jamo (consonant). Skipped when there is no final.
    2. vertical vowel ink lives in the right half: a non-final component
       whose center is right of 50% of the ink width is vowel.
    3. when the medial has a horizontal stroke, vowel ink also sits low:
       the non-final components whose center is within the bottom 15% of
       the ink height (relative to the lowest non-final center) are vowel.
    Everything else is the initial — which may be several components
    (ㅎ is an arc plus a ring; both are consonant).
    Known limitation: ㅛ/ㅠ stack their cups around mid-height at the
    center-right, so the top cup can fall outside rules 2–3; check the
    emitted rules and use --vowel-comp to override if needed.
    """
    n = len(comps)
    left = min(c["x0"] for c in comps)
    top = min(c["y0"] for c in comps)
    wink = max(c["x1"] for c in comps) - left
    hink = max(c["y1"] for c in comps) - top
    has_h = 0x1169 <= medial_cp <= 0x1174
    t_idx = set()
    if has_t:
        thr = top + 0.80 * max(hink, 1)
        t_idx = {i for i in range(n) if comps[i]["y1"] > thr}
        if not t_idx:
            return None, "final jamo present but no component reaches the bottom band"
    labels = ["C"] * n
    rest = [i for i in range(n) if i not in t_idx]
    for i in rest:
        if comps[i]["cx"] - left > 0.50 * wink:
            labels[i] = "V"
    if has_h and rest:
        # horizontal vowel ink is the bottom group of the non-final comps;
        # a relative window beats an absolute threshold because ㅜ/ㅗ prongs
        # pull the bbox center of the cup well above its stroke band.
        cy_max = max(comps[i]["cy"] for i in rest)
        for i in rest:
            if comps[i]["cy"] >= cy_max - 0.15 * max(hink, 1):
                labels[i] = "V"
    if "V" not in labels:
        return None, "no component labeled vowel"
    return labels, None


def emit_rule(cls, rects, w, h):
    """CSS rule. Positions use the 2-value percentage form on purpose:
    percentages follow the alignment formula offset = P% * (area - image),
    which is the behavior Chrome applies to every percentage position (the
    4-value `left X%` form is no plain offset there — measured, don't trust).
    """
    imgs = ", ".join(["linear-gradient(var(--vowel),var(--vowel))"] * len(rects)
                     + ["linear-gradient(var(--cons),var(--cons))"])
    pos = []
    for x0, y0, x1, y1 in rects:
        iw, ih = x1 - x0 + 1, y1 - y0 + 1
        px = (100.0 * x0 / (w - iw)) if w > iw else 0.0
        py = (100.0 * y0 / (h - ih)) if h > ih else 0.0
        pos.append(f"{px:.1f}% {py:.1f}%")
    size = ", ".join(f"{((x1 - x0 + 1) / w) * 100:.1f}% {((y1 - y0 + 1) / h) * 100:.1f}%"
                     for x0, y0, x1, y1 in rects) + ", 100% 100%"
    return (f".{cls} {{\n"
            f"  background-image: {imgs};\n"
            f"  background-position: {', '.join(pos)}, 0 0;\n"
            f"  background-size: {size};\n"
            f"}}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("syllables", nargs="+", help="hangul syllables, e.g. 차 한 잔")
    ap.add_argument("--family", default=None,
                    help="CSS font-family stack for the samples (default: last "
                         "@font-face family in --css)")
    ap.add_argument("--css", default=None,
                    help="fonts.css with the @font-face subsets the real poster "
                         "uses — measurements are only valid for that font")
    ap.add_argument("--out", default="k_measure", help="work dir (kept for inspection)")
    ap.add_argument("--font-size", type=int, default=200, help="measurement size (px)")
    ap.add_argument("--margin", type=int, default=2,
                    help="ink safety margin around the patches (px)")
    ap.add_argument("--vowel-comp", default=None, metavar="I,J",
                    help="override auto labels: 1-based component indices (in the "
                         "printed table) to paint as vowels — single syllable only")
    a = ap.parse_args()
    if a.vowel_comp and len(a.syllables) != 1:
        sys.exit("--vowel-comp needs exactly one syllable")

    _ensure_deps()
    global CHROME
    CHROME = subprocess.run(["bash", "-lc", "command -v ${CHROME_BIN:-google-chrome}"],
                             capture_output=True, text=True).stdout.strip()
    if not CHROME:
        sys.exit("google-chrome not found (set $CHROME_BIN)")

    import numpy as np
    from PIL import Image

    css = ""
    if a.css:
        css = pathlib.Path(a.css).read_text()
    if not a.family:
        fams = re.findall(r"font-family:\s*['\"]([^'\"]+)", css)
        if not fams:
            sys.exit("pass --family (no @font-face found in --css)")
        a.family = "'%s'" % fams[-1]

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rowpad, fs = 100, a.font_size
    box_h = round(fs * 1.28)

    # ---- pass 1: black-ink measurement ------------------------------------
    rows = "\n".join(
        f'<div class="row"><span class="ksyl" id="k{i}">{s}</span></div>'
        for i, s in enumerate(a.syllables))
    build = out / "measure_build.html"
    build.write_text(BUILD_TPL % {"css": css, "rows": rows, "rowpad": rowpad,
                                  "fs": fs, "family": a.family})
    url = "file://" + str(build.resolve())
    win_w, win_h = 100 + fs * 2, (rowpad + box_h) * len(a.syllables) + 100
    dom = render_chrome(url, win_w, win_h, dom=True)
    m = re.search(r"RECTS (\{.*?\})", dom, re.S)
    if not m:
        sys.exit("rect dump not found in DOM — chrome may not have run the JS")
    rects = {k: v for k, v in json.loads(m.group(1)).items()}
    shot = out / "measure_ink.png"
    render_chrome(url, win_w, win_h, out=str(shot))
    ink = np.asarray(Image.open(shot).convert("L")) < 128

    print(f"# measured on {a.family} @ {fs}px  (ink mask: {shot})")
    # per-syllable record: comps/labels/rule for the verify pass
    recs = []
    for i, syl in enumerate(a.syllables):
        cls = "k%04X" % ord(syl[0])
        L, V, T = jamo_decomp(syl)
        x, y, w, h = rects[f"k{i}"]
        sub = ink[int(round(y)):int(round(y + h)), int(round(x)):int(round(x + w))]
        if sub.sum() == 0:
            sys.exit(f"{syl}: no ink in element box — wrong rect?")
        comps = []
        for j, (ys, xs) in enumerate(label_components(sub)):
            cm = np.zeros_like(sub)
            cm[ys, xs] = True
            comps.append({"mask": cm, "x0": int(xs.min()), "x1": int(xs.max()),
                          "y0": int(ys.min()), "y1": int(ys.max()),
                          "cx": float((xs.min() + xs.max()) / 2),
                          "cy": float((ys.min() + ys.max()) / 2)})
        print(f"# {syl} (.{cls}) = {L} + {V}" + (f" + {T}" if T else "") +
              f"  (box {w:.2f}x{h:.0f})")
        rec = {"syl": syl, "err": None, "rule": None, "w": w, "h": h}
        recs.append(rec)
        if a.vowel_comp:
            sel = {int(t) - 1 for t in a.vowel_comp.split(",")}
            labels = ["V" if j in sel else "C" for j in range(len(comps))]
        else:
            labels, err = classify(comps, T is not None, ord(V))
            if err:
                rec["err"] = f"LABEL FAIL: {err}"
                print(f"#   !! {err} — rerun with --vowel-comp")
                for j, c in enumerate(comps):
                    print(f"#   comp{j + 1}: x[{c['x0']},{c['x1']}] y[{c['y0']},{c['y1']}]"
                          f" → ?")
                continue
        rec["comps"], rec["labels"] = comps, labels
        for j, c in enumerate(comps):
            print(f"#   comp{j + 1}: x[{c['x0']},{c['x1']}] y[{c['y0']},{c['y1']}]"
                  f" → {labels[j]}")
        red = np.zeros_like(sub)
        blue = np.zeros_like(sub)
        for c, lab in zip(comps, labels):
            if lab == "V":
                red |= c["mask"]
            else:
                blue |= c["mask"]
        if (red & dilate(blue, 1)).any() or (blue & dilate(red, 1)).any():
            print("#   !! ink of different labels within 1px — margin at risk")
        if (red & dilate(blue, a.margin)).any():
            print("#   !! vowel ink lies within the margin of consonant ink")
        rrects, err = cover_vowel(red, blue, a.margin)
        if err:
            rec["err"] = f"COVER FAIL: {err}"
            print(f"#   !! {err}")
            continue
        rec["red"], rec["rule"] = red, emit_rule(cls, rrects, w, h)
        print(f"#   patches: {len(rrects)} red rect(s) over full-box blue")

    ok = [r for r in recs if r["rule"]]
    if not ok:
        sys.exit("no syllable produced a rule")
    print()
    for r in ok:
        print(r["rule"])
        print()

    # ---- pass 2: verify the emitted rules with a real render --------------
    for i, r in enumerate(recs):
        if r["rule"] is None:
            continue
        cls = "k%04X" % ord(r["syl"][0])
        r["vrow"] = (f'<div class="row"><span class="ksyl gt" id="g{i}">{r["syl"]}</span>'
                     f'<span class="gap"></span>'
                     f'<span class="ksyl pt {cls}" id="p{i}">{r["syl"]}</span></div>')
    vrows = "\n".join(r["vrow"] for r in recs if r["rule"])
    vbuild = out / "verify_build.html"
    vbuild.write_text(VERIFY_TPL % {"css": css, "rules": "\n".join(r["rule"] for r in ok),
                                    "rows": vrows, "rowpad": rowpad,
                                    "fs": fs, "family": a.family})
    vurl = "file://" + str(vbuild.resolve())
    v_h = (rowpad + box_h) * len(recs) + 100
    vdom = render_chrome(vurl, win_w + 300, v_h, dom=True)
    m = re.search(r"RECTS (\{.*?\})", vdom, re.S)
    if not m:
        sys.exit("verify rect dump not found — chrome may not have run the JS")
    vrects = {k: v for k, v in json.loads(m.group(1)).items()}
    vshot = out / "verify_ink.png"
    render_chrome(vurl, win_w + 300, v_h, out=str(vshot))
    rgb = np.asarray(Image.open(vshot).convert("RGB")).astype(int)
    gray = np.asarray(Image.open(vshot).convert("L")) < 128

    failed = False
    for r in recs:
        if r["err"]:
            print(f"{r['syl']}: {r['err']}")
            failed = True
        elif r["rule"] is None:
            failed = True
    for i, r in enumerate(recs):
        if r["rule"] is None:
            continue
        gx, gy, gw, gh = vrects[f"g{i}"]
        px, py, pw, ph = vrects[f"p{i}"]
        g0x, g0y = int(round(gx)), int(round(gy))
        p0x, p0y = int(round(px)), int(round(py))
        gt = gray[g0y:g0y + int(round(gh)), g0x:g0x + int(round(gw))]
        exp_v = np.zeros_like(gt)
        for c, lab in zip(r["comps"], r["labels"]):
            if lab == "V":
                exp_v |= c["mask"]
        pt_rgb = rgb[p0y:p0y + int(round(ph)), p0x:p0x + int(round(pw))]
        if pt_rgb.shape[:2] != gt.shape:
            r["err"] = f"VERIFY FAIL: box {pt_rgb.shape[:2]} != {gt.shape}"
            print(f"{r['syl']}: {r['err']}")
            failed = True
            continue
        d_red = np.abs(pt_rgb - np.array(RED)).sum(axis=2)
        d_blue = np.abs(pt_rgb - np.array(BLUE)).sum(axis=2)
        is_v = d_red < d_blue
        bad_v = int((gt & exp_v & ~dilate(is_v, 1)).sum())
        bad_c = int((gt & ~exp_v & ~dilate(~is_v, 1)).sum())
        tag = "PASS" if (bad_v + bad_c) == 0 else "FAIL"
        if tag == "FAIL":
            failed = True
        print(f"verify {r['syl']}: {tag}  ({bad_v + bad_c} wrong px of "
              f"{int(gt.sum())} ink px — vowel {bad_v}, consonant {bad_c})")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
