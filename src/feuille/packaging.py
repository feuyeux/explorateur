# -*- coding: utf-8 -*-
"""packaging.py — 交付打包（zipfile，非 ASCII 文件名必须置 UTF-8 flag）

搬运自 yiyezhiqiu/package.py 的核心教训：macOS 自带 Info-ZIP 对非 ASCII
文件名**不置 UTF-8 flag（bit 0x800）**，解包到别的机器上中文/阿拉伯语
文件名全变乱码。Python 的 zipfile 默认置位，所以打包一律走 zipfile，
不走命令行 zip。
"""
from __future__ import annotations

import zipfile
from pathlib import Path

UTF8_FLAG = 0x800


def zip_tree(src_dir, out_zip, *, include=lambda p: True) -> Path:
    """把 src_dir 打成 zip（相对路径保留；UTF-8 flag 由 zipfile 默认置位）。

    include(path)：以 src_dir 为根的相对路径过滤（跳过 build 产物/临时件用）。
    """
    src_dir, out_zip = Path(src_dir), Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src_dir.rglob("*")):
            if not p.is_file() or not include(p.relative_to(src_dir)):
                continue
            zf.write(p, p.relative_to(src_dir).as_posix())
            n += 1
    return out_zip


def has_utf8_flag(out_zip, name: str) -> bool:
    """验证某个条目带了 UTF-8 flag（反向验证用：这是判据不是摆设）。"""
    with zipfile.ZipFile(out_zip) as zf:
        info = zf.getinfo(name)
        return bool(info.flag_bits & UTF8_FLAG)
