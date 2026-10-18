# -*- coding: utf-8 -*-
"""spike2_scenes_ref.py — spike 2 参照渲染器：按 op-spec 用 Pillow 渲染 PNG。

与 TS 侧（@feuille/core imaging/draw.ts 的 spec 渲染器）共享同一份
`golden/assets/scenes_ref.spec.json`；产物 scenes_ref.png 是机桶参照
（Pillow 桶），TS 侧按「结构与几何」比对（降采样灰度均值/分位差，
不比像素——栅格化器不同，边缘 AA 必然不同）。

跑法：uv run python migration/spike2_scenes_ref.py
"""
from __future__ import annotations

import json
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden"


def run(spec_path: Path, out_png: Path) -> None:
    from PIL import Image, ImageDraw

    spec = json.loads(spec_path.read_text("utf-8"))
    W, H, SS = spec["w"], spec["h"], spec["ss"]

    img = Image.new("RGB", (W * SS, H * SS), (246, 243, 238))
    d = ImageDraw.Draw(img)
    k = SS

    def rgb(c):
        return tuple(c)

    for op in spec["ops"]:
        kind = op["op"]
        box = [v * k for v in op["box"]] if "box" in op else None
        pts = [(x * k, y * k) for x, y in op["pts"]] if "pts" in op else None
        if kind == "gradient":
            x0, y0, x1, y1 = op["box"]
            top, bottom = op["top"], op["bottom"]
            for y in range(y0, y1):
                t = (y - y0) / max(1, (y1 - y0 - 1))
                c = [round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)]
                d.rectangle([x0 * k, y * k, x1 * k, (y + 1) * k], fill=rgb(c))
        elif kind == "rectangle":
            d.rectangle(box, fill=rgb(op["fill"]) if "fill" in op else None,
                        outline=rgb(op["outline"]) if "outline" in op else None,
                        width=op.get("width", 1) * k)
        elif kind == "rounded_rectangle":
            d.rounded_rectangle(box, op["radius"] * k,
                                fill=rgb(op["fill"]) if "fill" in op else None,
                                outline=rgb(op["outline"]) if "outline" in op else None,
                                width=(op.get("width", 1)) * k)
        elif kind == "ellipse":
            d.ellipse(box, fill=rgb(op["fill"]) if "fill" in op else None,
                      outline=rgb(op["outline"]) if "outline" in op else None,
                      width=op.get("width", 1) * k)
        elif kind == "line":
            d.line(pts, fill=rgb(op["fill"]), width=max(1, op.get("width", 1) * k),
                   joint=op.get("joint"))
        elif kind == "arc":
            d.arc(box, op["start"], op["end"], fill=rgb(op["fill"]),
                  width=max(1, op.get("width", 1) * k))
        elif kind == "pieslice":
            d.pieslice(box, op["start"], op["end"], fill=rgb(op["fill"]))
        elif kind == "chord":
            d.chord(box, op["start"], op["end"], fill=rgb(op["fill"]))
        elif kind == "polygon":
            d.polygon(pts, fill=rgb(op["fill"]))
        else:
            raise ValueError(f"unknown op: {kind}")

    out = img.resize((W, H), Image.LANCZOS)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_png)
    print(f"ref written: {out_png} ({W}x{H})")


if __name__ == "__main__":
    run(GOLDEN / "assets" / "scenes_ref.spec.json",
        GOLDEN / "assets" / "scenes_ref.png")
