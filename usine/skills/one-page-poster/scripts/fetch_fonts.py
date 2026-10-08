#!/usr/bin/env python3
"""Fetch per-character font subsets from Google Fonts and emit fonts.css with base64 woff2.

Driven by fonts.json (path = argv[1] or ./fonts.json next to this script's caller):
[
  {"family": "OBS Deva", "google": "Noto+Sans+Devanagari:wght@500",
   "text": "एक किताब हिन्दी", "classes": ["f-deva"]}
]
- "family": the @font-face name used in the poster CSS (embed this stack FIRST)
- "google": css2 family spec, URL-escaped (+ for spaces, ;wght@ for weights)
- "text":   every character that will ever be rendered with this family
            (page copy + labels + legend; spaces are implicit)
- "classes": optional — CSS classes that render with this family (used by audit_charset.py)

Output: fonts.css written next to fonts.json.
"""
import base64, json, re, sys, pathlib, urllib.parse, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

def uniq(s):
    return "".join(sorted(set(s) - {" ", "\n"})) + " "

def main():
    spec_path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "fonts.json")
    spec = json.loads(spec_path.read_text())
    css_out = []
    for ent in spec:
        fam, text = ent["family"], ent["text"]
        url = (f"https://fonts.googleapis.com/css2?family={ent['google']}"
               f"&text={urllib.parse.quote(uniq(text))}&display=swap")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        css = urllib.request.urlopen(req, timeout=30).read().decode()
        blocks = re.findall(r"@font-face\s*{[^}]+}", css)
        if not blocks:
            print(f"!! no face for {fam}"); continue
        for block in blocks:
            m = re.search(r"url\((https://[^)]+)\)\s*format\('woff2'\)", block)
            wght = re.search(r"font-weight:\s*(\d+)", block).group(1)
            data = urllib.request.urlopen(
                urllib.request.Request(m.group(1), headers={"User-Agent": UA}), timeout=30).read()
            b64 = base64.b64encode(data).decode()
            block = re.sub(r"url\([^)]+\)\s*format\('woff2'\)",
                           f"url(data:font/woff2;base64,{b64}) format('woff2')", block)
            block = re.sub(r"font-family:\s*'[^']+'", f"font-family: '{fam}'", block)
            css_out.append(block)
            print(f"{fam} w{wght}: {len(data)//1024} KB")

    out = spec_path.parent / "fonts.css"
    out.write_text("\n".join(css_out))
    print(f"\nwrote {out} ({out.stat().st_size//1024} KB)")

if __name__ == "__main__":
    main()
