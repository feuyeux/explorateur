#!/usr/bin/env python3
"""Parse the per-cell fit diagnostics dumped by the template's ?verify=1 mode.

Usage (two steps, or pipe):
  uv run --project usine python -c "from feuille import platform; print(platform.browser_path())" \
    → 用该路径替换下面的 $BROWSER，然后：
  $BROWSER --headless=new --disable-gpu --no-sandbox \
    --virtual-time-budget=10000 --window-size=1240,1754 --dump-dom \
    "file://$PWD/index.html?verify=1" | fit_diag.py

Reads the `DIAG {...}` block from stdin or a file argument and prints one line
per cell: font size, word rect (CSS px), overflow flags. Exits 1 on any
overflow or unloaded font. The word rects feed check_overlay.py directly.
"""
import json, re, sys

raw = open(sys.argv[1]).read() if len(sys.argv) > 1 else sys.stdin.read()
m = re.search(r"DIAG (\{.*?\})\s*</", raw, re.S)
if not m:
    print("no DIAG block found — render with ?verify=1 and --dump-dom"); sys.exit(1)
d = json.loads(m.group(1))

bad = [s for s in d["fonts"].split(",") if s and not s.endswith("loaded")]
for f in bad: print("UNLOADED FONT:", f)

fail = bool(bad)
for c in d["cells"]:
    flag = ""
    if c["overflowX"]: flag += " <-- OVERFLOW-X"; fail = True
    if c["overflowY"]: flag += " <-- OVERFLOW-Y"; fail = True
    print(f"{c['lang']:10s} fs={c['fs']:6.1f} word={c['word']}{flag}")
print("fit diag: OK" if not fail else "fit diag: PROBLEMS")
sys.exit(1 if fail else 0)
