#!/usr/bin/env python3
"""Inject fonts.css into the poster template at the /*__FONTS__*/ marker.

Usage: assemble.py [src.html] [out.html]
Defaults: poster_src.html -> ../index.html (relative to this script's cwd).
The marker can be overridden in the template by using a different
`/*__FONTS__*/`-style comment; keep it inside a <style> block.
"""
import pathlib, sys

here = pathlib.Path.cwd()
src = here / (sys.argv[1] if len(sys.argv) > 1 else "poster_src.html")
out = here / (sys.argv[2] if len(sys.argv) > 2 else "../index.html")
marker = "/*__FONTS__*/"

fonts_css = (src.parent / "fonts.css").read_text()
body = src.read_text()
assert marker in body, f"marker {marker} not found in {src}"
out.write_text(body.replace(marker, fonts_css))
print(f"wrote {out} ({out.stat().st_size//1024} KB)")
