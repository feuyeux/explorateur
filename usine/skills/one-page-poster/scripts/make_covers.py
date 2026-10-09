#!/usr/bin/env python3
"""Generate the fullscreen cover variants (landscape 1920x1080 4x3 grid,
portrait 1080x1920 3x4 grid) from poster_src.html — same cells, same fit JS,
different page geometry. Never rotate: each orientation lays out natively so
it fills the screen edge to edge (rotation/padding leaves dead bands).

Usage: make_covers.py [poster_src.html [cover_src.html]]
  缺省在脚本所在目录读写；跨项目跑时把两个路径都传进来
  （原版把路径写死在 __file__ 旁，examples/ 项目目录里根本用不上）。
"""
import pathlib, re
import sys

SRC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parent / "poster_src.html"
OUT = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else SRC.parent / "cover_src.html"

s = SRC.read_text()

overrides = """
/* ---------- fullscreen cover variants (make_covers.py) ---------- */
.poster.lc { width: 1920px; height: 1080px; padding: 44px 64px 36px; }
.poster.lc .grid { grid-template-columns: repeat(4, 1fr); grid-template-rows: repeat(3, 1fr); margin-top: 22px; min-height: 0; }
.poster.lc .title-zh { font-size: 96px; }
.poster.lc .title-sub { font-size: 21px; margin-top: 12px; }
.poster.lc .legend { gap: 10px; padding-bottom: 8px; }
.poster.lc .legend .li { font-size: 17px; }
.poster.lc .legend .li b { font-size: 18px; }
.poster.lc .lang { font-size: 20px; }
.poster.lc .lang small { font-size: 15px; }
.poster.lc .natv { font-size: 19px; }
.poster.lc .translit { font-size: 30px; }
.poster.lc .annot { font-size: 38px; }
.poster.lc .jpat { font-size: 24px; }
.poster.pt { width: 1080px; height: 1920px; padding: 60px 52px 48px; }
.poster.pt .grid { grid-template-columns: repeat(3, 1fr); grid-template-rows: repeat(4, 1fr); margin-top: 28px; min-height: 0; }
.poster.pt .title-zh { font-size: 92px; }
.poster.pt .title-sub { font-size: 19px; }
.poster.pt .translit { font-size: 28px; }
.poster.pt .annot { font-size: 38px; }
.poster.pt .jpat { font-size: 24px; }
"""

# insert the overrides right before the closing </style>
s = s.replace("ruby rt { font-weight: 500; }\n</style>",
              "ruby rt { font-weight: 500; }\n" + overrides + "</style>")

# fmt switching + cover title id: add a tiny boot script before the fit script
boot = """
<script>
// cover variant: ?fmt=P portrait (3x4, default geometry), else landscape (4x3)
const FMT = new URLSearchParams(location.search).get("fmt");
document.querySelector(".poster").classList.add(FMT === "P" ? "pt" : "lc");
</script>
"""
s = s.replace("<script>\n// per-cell auto-fit", boot + "\n<script>\n// per-cell auto-fit")

OUT.write_text(s)
print(f"wrote {OUT} ({OUT.stat().st_size//1024} KB)")
