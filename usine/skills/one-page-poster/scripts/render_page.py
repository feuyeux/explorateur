#!/usr/bin/env python3
"""Windows render/dump helpers for one-page-poster (Edge headless=new).

Companion to render_poster.sh (macOS/Linux); same two jobs, plus compensation
for a Windows Edge quirk probed on this machine:

  --window-size INCLUDES a constant window-frame overhead of (24, 93) CSS px
  (Win10 x64 Edge --headless=new, double-size probe: inner = window - 24/93;
  content anchors at device (0,0), bg bands sit right/bottom only). We
  over-size the window by the overhead, then crop the PNG back to
  w*scale x h*scale. To re-probe on a new machine/browser: render a page whose
  CSS size is exactly W x H with --window-size=W,H at scale 1 and measure the
  content bounds (solid-color body probe) — do not trust these constants
  blindly on another setup.

Two more Windows traps this helper already handles:

  - --screenshot=<ABSOLUTE path> only: a relative path fails SILENTLY
    (exit 0, no file written);
  - any JS rect probing (fit_diag/verify) must run behind a
    document.fonts.ready gate (+ small setTimeout) or you measure
    fallback-font metrics (probe-font-decode race);
  - `dump` runs the SAME window overhead: pass the page size + (24, 93) —
    e.g. `dump index.html?verify=1 out.txt 1104 1533` for a 1080×1440 page —
    or the DOM lays out 24/93 px smaller than the rendered poster and every
    ?verify=1 rect (fit_diag word boxes) lands offset from the PNG.

Usage (from the poster project dir, resolved via the usine uv project):

  uv run python <skill>/scripts/render_page.py dump <file.html> <out.txt> [w] [h]
  uv run python <skill>/scripts/render_page.py render <file.html> <query|-> <out.png> <w> <h> <scale>

`query` is the part after "?" (e.g. "fmt=T"); pass "-" for none.
"""
import pathlib, subprocess, sys


def chrome():
    from feuille import platform
    return platform.browser_path()


def file_url(p):
    """Split a ?query off the path BEFORE as_uri (it would percent-encode it)."""
    p, _, q = str(p).partition("?")
    return pathlib.Path(p).resolve().as_uri() + (("?%s" % q) if q else "")


def base_cmd(w, h):
    return [chrome(), "--headless=new", "--disable-gpu", "--no-sandbox",
            "--virtual-time-budget=10000",
            "--window-size=%s,%s" % (w, h),
            "--force-device-scale-factor=1",
            "--hide-scrollbars"]


def dump_dom(target, out, w="1080", h="1440"):
    cmd = base_cmd(w, h) + ["--dump-dom", file_url(target)]
    r = subprocess.run(cmd, capture_output=True, timeout=180)
    pathlib.Path(out).write_bytes(r.stdout)
    print("dumped %s (%d bytes)" % (out, len(r.stdout)))


def render(target, query, out, w, h, scale):
    """Over-size the window by the (24, 93) frame overhead, then crop back to
    w*scale x h*scale (content anchors at device (0,0); bands sit right/bottom
    only — see module docstring for the probe method)."""
    url = file_url(target) + (("?%s" % query) if query else "")
    cmd = base_cmd(int(w) + 24, int(h) + 93) + [
        "--force-device-scale-factor=%s" % scale,
        "--screenshot=%s" % pathlib.Path(out).resolve(), url]
    subprocess.run(cmd, capture_output=True, timeout=180)
    if not pathlib.Path(out).is_file():
        sys.exit("screenshot not written: %s" % out)
    from PIL import Image
    im = Image.open(out)
    want = (int(w) * int(scale), int(h) * int(scale))
    if im.size != want:
        if im.size[0] < want[0] or im.size[1] < want[1]:
            sys.exit("render %s smaller than expected: %s < %s" % (out, im.size, want))
        im.crop((0, 0, want[0], want[1])).save(out)
    print("wrote %s (%dx%d)" % (out, want[0], want[1]))


if __name__ == "__main__":
    if sys.argv[1] == "dump":
        dump_dom(sys.argv[2], sys.argv[3],
                 sys.argv[4] if len(sys.argv) > 4 else "1080",
                 sys.argv[5] if len(sys.argv) > 5 else "1440")
    else:
        q = "" if sys.argv[3] in ("-", "") else sys.argv[3]
        render(sys.argv[2], q, sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7])
