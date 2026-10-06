# -*- coding: utf-8 -*-
"""section_patch.py — 按 `### NN · 语种` 边界整节替换发布文案（幂等）

搬运自 yiyezhiqiu/section_patcher.py（终态视角重构：路径参数化、
节头时长字段可选——与 manifest._SEC 同口径，两版文案体例都吃）。

为什么不再用行号区间（三个真实事故换来的）：
  · RTL 文本（阿拉伯语/希伯来语）从终端/编辑器复制会被双向算法重排，
    字符串匹配必然失配；
  · 前面多轮编辑会让行号漂移；
  · 「从 .bak2 恢复」曾把上一轮对 08/09 的改动整个冲掉。
按节标题定位与行号无关，整节写死，重复执行结果一致（幂等）。
"""
from __future__ import annotations

import re
from pathlib import Path

SEC = re.compile(r"^### (\d+) · (\S+) `([^`]+)`(?: · (\d\d):(\d\d))?\s*$")


def split_sections(text: str) -> dict[str, str]:
    """返回 {order: 该节完整文本（不含下一节的标题行）}。"""
    lines = text.split("\n")
    starts = [(i, *m.groups()) for i, m in
              ((i, SEC.match(l)) for i, l in enumerate(lines)) if m]
    out: dict[str, str] = {}
    for n, (i, *_) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        out[starts[n][1]] = "\n".join(lines[i:end]).rstrip("\n")
    return out


def replace(path, new_sections: dict[str, str]) -> None:
    """整节替换（幂等：重复执行结果一致）。找不到节 = 当场报错。"""
    p = Path(path)
    text = p.read_text("utf-8")
    secs = split_sections(text)
    for order, body in new_sections.items():
        if order not in secs:
            raise SystemExit(f"{p.name} 找不到第 {order} 节")
        secs[order] = body.rstrip("\n")
    orders = sorted(secs, key=int)
    lines = text.split("\n")
    head_end = next((m.start() for l in lines if (m := SEC.match(l))), None)
    if head_end is None:
        raise SystemExit(f"{p.name} 里没有任何节头（体例被改了？）")
    header = text[:head_end].rstrip("\n")
    body = "\n\n".join(secs[o] for o in orders) + "\n"
    p.write_text(header + "\n\n" + body, "utf-8")
