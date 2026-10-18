# migration/ — TS 迁移工作目录（P7 清场时整体退役）

本目录是 usine → dsh（DeepSeek Harness）原生 TS 工程全量迁移的工作区：
金样本判据、基线记录、迁移专用脚本。**门禁不扫描本目录**；迁移期 usine 的
权威门禁仍是 21 套 Python 反向验证（`uv run feuille verify`）。迁移完成后
（P7）本目录随 Python 侧一并清场，金样本迁入 TS 门禁包后删除。

## 目录

| 路径 | 内容 |
|---|---|
| `baseline/verify-baseline.txt` | 迁移起点基线：21 套全 PASS（1 SKIP 诚实列出），本机全量 ≈19.5s（2026-10-18，macOS arm64；ADAPTATION 记录的 46s 为当时 Windows 宿主口径） |
| `golden/*.json` | 金样本判据（capture_golden.py 产出）：纯函数**逐字节对齐**，环境相关项带机桶元数据、断**结构与几何** |
| `golden/assets/` | 金样本实物：tts-cache（3 语料 mp3+词表）、textlayer 渲染 PNG（不透明整图 + 双 matte 抠像） |
| `capture_golden.py` | 采集脚本：`uv run python migration/capture_golden.py [tts\|audio\|timeline\|textlayer\|all]` |

## 金样本口径

- **纯函数**（缓存键 / 滤镜图 / 时间轴 / HTML 模板 / 转义）：TS 侧逐字节复现
  同一输出（含 sha256 缓存键口径——口径不许变，变了等于换缓存空间）。
- **机桶项**（视口亏空 / 像素哈希 / 时长）：随 `_meta`（机器 / 浏览器 / ffmpeg /
  edge_tts 版本）落盘；跨实现断结构与几何（alpha 覆盖率 / 包围盒 / 时长容差），
  像素逐字节只在同桶内作参照。

## 迁移期事实记录

- **2026-10-18：Edge TTS 服务端协议已变更（v2）**。微软于 2026-10-16 前后弃用
  `speech.platform.bing.com` 旧握手：钉版 edge-tts 7.2.8 在线合成稳定 403
  （离线门禁不受影响）。上游 rany2/edge-tts #491/#492：改走
  `api.msedgeservices.com` + Sec-MS-GEC **v2** 令牌，7.3.1 适配。本项目已将
  基线从 7.2.8 升至 7.3.1（pyproject 同步注明；21 套门禁复验全绿）。
  **TS 移植必须实现 v2 协议**；金样本 `tts.json` 的 `synth` 段即 v2 协议的
  实测输出（词级时间戳语义不变：offset/duration 单位 100ns）。
- 金样本批次 1（tts / audio / timeline / textlayer）已采集；后续批次随
  P2–P4 各阶段在 Python 侧退役前补齐。
