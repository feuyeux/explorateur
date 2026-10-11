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

# Support locating fonts.css and shared base stylesheets
fonts_file = src.parent / "fonts.css"
fonts_css = fonts_file.read_text("utf-8") if fonts_file.is_file() else ""

body = src.read_text("utf-8")

# Multi-theme & shared typography support:
skills_root = here.parent if here.name in ("scripts", "assets") else here
theme_file = skills_root / "theme-tokens.css"
typo_file = skills_root / "typography-base.css"

# Optional theme argument: --theme <name>
theme_name = None
for i, arg in enumerate(sys.argv):
    if arg == "--theme" and i + 1 < len(sys.argv):
        theme_name = sys.argv[i + 1]
        break

if theme_name:
    # Inject data-theme on <body> or <html> if not present
    if 'data-theme="' not in body:
        body = body.replace("<body", f'<body data-theme="{theme_name}"', 1)

injected = []
if theme_file.is_file():
    injected.append(f"/* Extracted Theme Tokens */\n{theme_file.read_text('utf-8')}")
if typo_file.is_file():
    injected.append(f"/* Extracted Typography & Component Base */\n{typo_file.read_text('utf-8')}")
if fonts_css:
    injected.append(fonts_css)

replacement = "\n\n".join(injected) if injected else "/* No extra CSS injected */"

if marker in body:
    out.write_text(body.replace(marker, replacement), "utf-8")
else:
    out.write_text(body, "utf-8")

print(f"wrote {out} ({out.stat().st_size//1024} KB)" + (f" [theme: {theme_name}]" if theme_name else ""))


