#!/usr/bin/env python3
"""Audit: every char rendered by an embedded-first font family must exist in its
fonts.json subset text list — prevents tofu blocks after copy edits.

Usage: audit_charset.py [poster_src.html] [fonts.json]
Depends on fonts.json entries carrying "classes" (CSS classes that render with
that family, e.g. "f-deva"); a family whose classes include the translit row's
class covers the Latin line too.
"""
import re, html, json, sys, pathlib

src_path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "poster_src.html")
spec_path = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "fonts.json")
spec = json.loads(spec_path.read_text())
FAMS = {e["family"]: e["text"] for e in spec}
CLASS2FAM = {}
for e in spec:
    for c in e.get("classes", []):
        CLASS2FAM[c] = e["family"]

src = src_path.read_text()

# strip comments and style/script blocks; walk the body only
body = src.split("<body>", 1)[1] if "<body>" in src else src
body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
body = re.sub(r"<script>.*?</script>", "", body, flags=re.S)
body = re.sub(r"<style>.*?</style>", "", body, flags=re.S)

# tokenise tags, tracking the current family from class attributes
fam = None
use = {}  # fam -> set of chars
for m in re.finditer(r"<(/?)(\w+)([^>]*)>|([^<]+)", body):
    if m.group(1):  # closing tag
        continue
    if m.group(2):
        attrs = m.group(3) or ""
        cm = re.search(r'class="([^"]*)"', attrs)
        if cm:
            newfam = None
            for c in cm.group(1).split():
                if c in CLASS2FAM:
                    newfam = CLASS2FAM[c]; break
            # reset on every class-bearing tag: family state never leaks across
            # sibling subtrees
            fam = newfam
    else:
        text = html.unescape(m.group(4) or "")
        # skip script bodies heuristically
        if "function" in text or "const " in text or "document." in text:
            continue
        if fam:
            use.setdefault(fam, set()).update(ch for ch in text if not ch.isspace())

missing = []
for fam, chars in sorted(use.items()):
    subset_text = FAMS[fam]
    for ch in sorted(chars):
        if ch not in subset_text and ch != " ":
            missing.append((fam, ch, hex(ord(ch))))

if missing:
    print("MISSING from subsets:")
    for fam, ch, code in missing:
        print(f"  {fam}: {ch!r} {code}")
    sys.exit(1)
print("charset audit: all chars covered")
for fam, chars in sorted(use.items()):
    print(f"  {fam}: {len(chars)} distinct chars checked")
