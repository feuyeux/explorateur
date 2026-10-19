# 实测记录（2026-10）

> 静态规则见 [reference.md](reference.md)；交互见 [guide.md](guide.md)。
> 只留可复算的数字与已修缺陷；过程流水账看 git 历史。

## 1 一次真跑：一座城 · 12 语种

环境：Windows + Node 22.23.0（仓库要求 ≥24，实测可跑完整条线；升 24 是系统级变更，
未替你动）、pnpm、Edge/Chrome headless、ffmpeg/ffprobe、magick。

```powershell
$ErrorActionPreference = "Stop"
$env:FEUILLE_BROWSER = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$P   = "examples\one-city-12lang"
$ABS = "D:\coding\personal\explorateur\usine\examples\one-city-12lang"
$LOC = "zh-CN,en-US,de-DE,fr-FR,es-ES,ru-RU,el-GR,hi-IN,ar-SA,he-IL,ja-JP,ko-KR"

# 1 字体 + 字符门
pnpm exec feuille poster fetch-fonts $P\fonts.json
pnpm exec feuille poster audit-charset $P\poster_src.html $P\fonts.json
pnpm exec feuille poster audit-charset $P\video_src.html  $P\fonts.json
# 2 注入 + 海报 + 封面
pnpm exec feuille poster assemble $P\poster_src.html $P\index.html
pnpm exec feuille poster render $P\index.html "$ABS\poster.png"
pnpm exec feuille poster make-covers $P\index.html $P\cover_src.html
pnpm exec feuille poster render "$P\cover_src.html?fmt=P" "$ABS\cover_pt.png" 1080 1920 1
pnpm exec feuille poster render $P\cover_src.html "$ABS\cover_lc.png" 1920 1080 1
# 3 配音 + 合成
pnpm exec feuille karaoke tts $P\voices.json $P\tts
pnpm exec feuille karaoke build $P\video.json --only landscape
pnpm exec feuille karaoke build $P\video.json --only portrait
# 4 闸门
pnpm exec feuille karaoke scan-blank $P\out\one_city_landscape.mp4 $P\out\one_city_portrait.mp4
pnpm exec feuille karaoke verify-sync --video $P/out/one_city_landscape.mp4 --frames $P/frames --tts $P/tts --locales "$LOC" --preroll 0.8 --done 0.5 --intro 2.2
# 5 发布侧（零平台流量）
pnpm exec feuille copy check $P\publish --facts $P\publish\facts.json
pnpm exec feuille publish check-plan $P\publish\manifest.json --root $P
```

| 项 | 实测 |
|---|---|
| 语种 | 12（zh/en/de/fr/es/ru/el/hi/ar/he/ja/ko） |
| 成片 | 1920×1080 与 1080×1920，30fps，66.20s，1986 帧 |
| 同步门 | 横竖各 36/36 OK，最大 diff 608 / 40000 |
| 字体 | 7 字族子集，`fonts.css` 181,576 B（base64 woff2） |
| 复现 | 四步重跑 SHA256 一致：`poster.png` BD600809…、`cover_pt` 603670BE…、`cover_lc` D785B7F1… |
| BGM | Lyria 床 76.13s / 48 kHz / 16-bit / 立体声 / RMS −14.0 dBFS；`gain` 0.0871，fade 1.5→3.0 |

未跑（要人或要外部副作用）：`publish login`（扫码）、三平台真实发布（不可撤回）。
`publish check-plan` 可跑——零平台流量。

## 2 坑位表（一次真跑暴露）

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | `poster render` 报浏览器被抢占 | 输出是相对路径，Chrome 不按 cwd 解析 | 输出一律绝对路径 |
| 2 | 海报末行空白 / 转写丢失 | Edge 视口比 `--window-size` 小 24×93 | `FEUILLE_BROWSER` 指 Chrome |
| 3 | `fit-diag` OK 但图缺块 | 只看格内溢出，不看视口 | `getBoundingClientRect` 探 `innerHeight` |
| 4 | `make-covers` 退出 0 但没改文件 | 源文件 CRLF，字面 `\n` 锚点不匹配 | 源文件转 LF 重跑 |
| 5 | `audit-charset` 把拉丁大写算缺字 | `<small>` 落在 `class="f-sc"` 子树 | 字族类挪到内层 span |
| 6 | `pnpm --dir ..` 后路径全错 | `--dir` 只换包目录，cwd 仍是仓库根 | 从仓库根写相对路径 |
| 7 | `verify-sync` 找不到 seg.wav | PowerShell 把逗号当数组分隔符 | `--locales "a,b,c"` 加引号 |
| 8 | 同一封面小红书过、抖音不过 | 平台底色不同（白 vs 黑） | 按平台各出一张 |
| 9 | 视频字体没生效 | `build` 用原始 src 截图 | 先 `poster assemble` 注入 |
| 10 | `cover make` 传 `?fmt=P` 无效 | 只接受文件路径 | 竖版走 `poster render "…?fmt=P"` |
| 11 | `--locales` 顺序错，diff 全红 | 场景起点按该顺序累加 | 与 `video.json` 严格一致 |
| 12 | Node 22 上 `pnpm install` 也过 | 无 `.npmrc`，engine-strict 未开 | 升 ≥24 或显式关检查 |
| 13 | 加 BGM 后旁白小 3 dB | `aformat` mono→stereo 走 swr，每声道 −3.01 dB | 显式 `pan=stereo\|c0=c0\|c1=c0` |
| 14 | 装 playwright 后发布测试红 | `launchPersistentContext` 目录是第一个位置参数 | `(userDataDir, options)` |
| 15 | `bgm gen` 请求 76s 只得 36s | 收流按 1× 实时睡，实际 0.5–0.6× | 按音频字节数收流，wall 上限 2.5×+30s |

## 3 装库 / 真 key 之后才暴露的三个缺陷

1. **`launchPersistentContext` 签名**：没装 playwright 时测试 `skipIf` 跳过；装上立刻
   `TypeError: "path" argument must be of type string`。修后 `packages/publish` 22/22 通过。
2. **有床分支压旁白 3 dB**：静音床对照 −23.5 vs −26.5 dB，差恰 3.01；`aformat` 的
   mono→stereo 矩阵每声道 ×1/√2。改显式 `pan` 复制后回到 −23.5 dB。
3. **Lyria 收流提前收工**：请求 76.13s 实得 36.0s（47%），69s→42s（61%），23s→20s（87%）；
   探针显示到账约 0.59× 实时且中间成段停 5–10s。根因是 `session.play()` 后
   `sleep(seconds)`。改为凑够 `seconds×48000×2×2` 字节、250ms 轮询、20s 无新数据判流断；
   同一命令 76.13s / exit 0。原先记的「实时后端短约 10%」是假象。

## 4 发布：证据与判据（2026-10-06 批）

- **证据优先级**：截图/像素 > 脚本自报。反复出现「脚本说找不到、截图里明明有」和
  「脚本说成功、截图里没生效」。
- **未知状态一律当失败**；不许静默 fallback（已删三处「封面上传失败 → 用默认首帧 → 继续」）。
- **每条前强制回干净投稿页**：小红书 03 撞风控后残留遮罩，04–12 全部把上一条封面盖上去。
- **草稿箱计数不是判据**：小红书发布成功也不清草稿，计数从 (1) 涨到 (4) 时四条其实全成功。
- **成功判据**：回列表核验到作品（抖音计数递增并刷新一次；小红书按标题搜到）。
- **标题按平台倒推**：抖音 `系列名｜第NN话 语种：场景`（≤30）；小红书砍成
  `系列名｜NN语种`（≤20）；29 字抖音标题搬过去直接红字。
- **自检清单**：封面是预制带字图 → 文字在真实裁切框内 → 分区/声明由用户拍板 →
  发布后重开管理页截图核对 → 数量对不上拒绝提交 → 撞风控停下等人。

**2026-10-06 基线**（发布后 8.5h）：小红书 +35 粉 / 3,965 观看 / 曝光环比 +4249%；
抖音 +3 粉 / 平均播放 4.72s / 完播 0.8%。归因两次被推翻：不是「批量发布」，也不是
「45–56s 太长」；区分变量是语种与包装。
