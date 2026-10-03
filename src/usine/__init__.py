"""usine — 多语种教学视频渲染管线（人物亮相卡 + A/B 对话教学场景）。

数据在仓库根（personas/ · docs/ · scenes/scene-<id>.md · lesson_analysis/），代码在本包（src/usine/），
产物在 build/。ROOT 由本文件位置向上定位仓库根（pyproject.toml 所在层）——
包内模块统一 `from usine import ROOT` 取数据/产物锚点，不依赖 cwd。
"""
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
