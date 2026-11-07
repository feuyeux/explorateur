# 插画风格判据（冻结）

参考图（三栏水果中英图鉴海报）的视觉语言，2026-11-07 用 VLM 对参考海报实测定音：

- **卡通贴纸**：粗深色描边（近黑偏棕）+ **体积感的简单明暗与高光**（弧面渐变、
  白高光都允许——2026-11-06 的「纯色块、几乎无渐变」是初读，实测修正）
- **无投影**：参考海报明确没有 drop shadow / ground shadow——这是要压死的轴
- **绿叶/短柄/叶冠**：每个水果带绿色叶部（具体形态按主体描述：菠萝是叶冠、
  石榴是萼冠，不写死「一片叶」）
- **主体居中**，四周留白均匀；没有第二个物体（没有刀、碗、花）
- **奶油纸底**（`#fffcf5`，实测参考海报画布底色），不是纯白
- 无文字、无水印

## 验收判据（人眼逐条核，缺一即重生；VLM 门按同口径预检）

1. 卡通贴纸质感 + 简单明暗表现体积——不是水彩、不是 3D、不是写实
2. 明显粗描边
3. 暖奶油底，**无投影、无贴纸白边**，主体居中，四周留白均匀
4. 绿色叶部在位（叶/柄/冠按主体描述）
5. 无文字、无水印
6. 与上一张并排时，描边粗细与饱和度**明显属于同一套**

## 风格后缀（逐字不变；事实源在 `tools/fruitnames/gen_art.mjs`）

**matrix 引擎**（`STYLE`，mcode 运行时的 Matrix connector；启动器只在 mcode
运行时进程的 PATH 上）：

```
flat vector illustration, thick dark outline, solid flat colors, one green leaf, centered on plain cream background, no text
```

**mmx 引擎**（`MMX_STYLE`，image-01，API-key 登录态；2026-11-07 按参考海报
实测重写——投影是唯一必须压死的轴，体积明暗允许）：

```
bold cartoon sticker illustration, thick dark brown outline around every shape, simple flat shading for volume, no drop shadow, no ground shadow, no shadow of any kind, the background is one flat plain warm cream color filling the entire canvas, no scene, no ground line, one small green leaf and short brown stem on top, children's educational flashcard style, no text, no watermark
```

## 引擎差异（2026-11-07 实测，改引擎前先读）

- image-01 的家法是光泽卡通 + **产品照式软影**：投影轴用提示词压不住
  （10+ 轮措辞探针、两批实测 16+ 张全卡投影），所以 mmx 引擎走
  **程序去影 + 双层门**：
  1. `strip_shadow.mjs`——从画布四边泛洪（入口查近底色 T_NEAR=110，续行
     只查局部步进 T_STEP=12 + 距纸色深度上限 D_CAP=200），把「底色 +
     软影坡」整体替换成纸色；主体靠粗描边陡沿挡住泛洪。幂等。
  2. **像素残影判据**（`stripShadow` 返回的 `shadowResidue`）：剥完后统计
     「未泛洪、距纸色 14~130、与泛洪区连通、连通域紧凑（填充率 ≥0.45、
     面积 ≥300）」的像素量——干净图实测 0，真投影几千，上限 400。
     连通域几何专门排掉三类干扰：轮廓抗锯齿沿（细长）、果内奶油高光
     （被描边包住不贴背景）、果内彩色体色（同前）。
  3. VLM 六问（`GATE_PROMPT`，最多重试 2 次；落选稿留 `_rejected_<key>.png`）。
     **第 3 问（影子）只记录不判门**——它把果内高光误读成贴地影（olive/
     date 实测冤案）、残影 0 仍报有影（blueberry/avocado 实测），与确定性
     判据矛盾时以像素为准；判门的是其余五问。第 1 问允许扁平或简单明暗
     （参考海报自己有体积渐变）；第 4 问收「叶/柄/冠」不写死一片叶。
- 主体描述里的 `glossy` / `shiny`（高光邀请词）与 `blush patch` 在 mmx 分支
  的引擎边界上统一替换/剥掉（不改 `SUBJECTS` 本体——那是 matrix 线调好的）。
- 门禁口径不许比权威更严：第一版把「扁平」问成零明暗、把「无影」问成
  连果内高光都算影，20/35 落选里大半是冤案（2026-11-07 实测）。
- **同一集的图必须同一引擎出的**；跨引擎出图风格不成套。换引擎 = 全部重出，
  先拿 1 张探针并排对比已验收样图再动批。
- VLM 门是预检机器，第 6 条「成套与否」只有人眼能判：批完出联络表
  （`tools/fruitnames/contact_sheet.mjs`）交用户终审。
