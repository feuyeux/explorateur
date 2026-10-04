#!/usr/bin/env pwsh
<#
run.ps1 — 管线统一入口（uv 管理单一 .venv：edge-tts / Pillow / numpy 全在一个环境，见 pyproject.toml）
  tts     edge-tts 7.2.8：逐行合成 + 词级时间戳
  assets  Edge headless 渲染文字层 PNG（双色 matte 抠像）
  render  Pillow+numpy 帧渲染 + ffmpeg
  qa / qa-motion / all          亮相卡验收与全流程
  qa-shape                      人物层形状/连接/图层几何探针（28 人 × 6）
  chars                         人物形象体检台：28 人立绘 + 剪影 + 总览 + 索引页 -> build/chars/
  scene / scene-list / qa-scene 教学场景 A/B 对话线（M2，-Scene <id> 选场景）
  lesson / dump-lesson          教学文档（lessons/<id>/scene.json + analysis -> build/lesson/<id>）
用法：.\run.ps1 all | .\run.ps1 render -Only xiaoman,layla -Workers 7
      .\run.ps1 qa-shape       # 改完 draw_character/face_geo 必跑
      .\run.ps1 chars          # 生成/复看 28 人形象图（--Openness 0.9 可验图层序）
      .\run.ps1 scene            # 14 语种场景：parse → tts → assets → render
      .\run.ps1 scene -Only zh-CN
首次使用：uv sync（建 .venv 并装锁定的依赖；抖音工具另需 uv sync --group douyin + playwright install chromium）
#>
param(
  # ValidateSet 必须与下面 switch 的 case 标签逐项一致：漏一项 = 该分支永远进不去
  # （2026-10-04 实测：qa-annotate / qa-shape-verify 曾漏列，run.ps1 直接 REJECTED，
  #  而 render-handbook §0 正把这两条当标准命令教人用 —— 死代码）。
  [Parameter(Position = 0)][ValidateSet("tts", "assets", "render", "qa", "qa-motion", "qa-shape", "qa-annotate", "qa-shape-verify", "verify", "chars", "all", "scene", "scene-tts", "scene-assets", "scene-render", "scene-list", "qa-scene", "lesson", "dump-lesson")][string]$Phase = "all",
  [string]$Only = "",
  [string]$Scene = "colors",
  [int]$Workers = 7,
  [double]$Openness = 0.0,
  [string]$Pose = ""
)
# PowerShell 5.1：原生命令只要往 stderr 写一行（uv 的 "Building usine" 进度、ffmpeg 的告警…），
# $ErrorActionPreference="Stop" 就会抛 NativeCommandError 直接中断——哪怕退出码是 0。
# 2026-10-04 实测：这条让 run.ps1 的每一条子命令（连 scene-list 这种纯读命令）都跑不起来。
# 判据统一交给 $LASTEXITCODE（Invoke-Step 已经在做），所以这里必须让 stderr 闭嘴。
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) { Write-Host "==> uv sync（.venv 不存在，先建环境）" -ForegroundColor Cyan; uv sync }

$onlyArg = if ($Only) { @("--only", $Only) } else { @() }

function Invoke-Step([string]$Name, [scriptblock]$Step) {
  Write-Host "`n==> $Name" -ForegroundColor Cyan
  $global:LASTEXITCODE = 0
  & $Step
  if ($LASTEXITCODE -ne 0) {
    Write-Host "$Name 失败 (rc=$LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
  }
}

# 亮相卡管线（管线一）：-Only 用人物 id
function Invoke-Cards([string[]]$Steps) {
  foreach ($s in $Steps) {
    switch ($s) {
      "tts"    { Invoke-Step "tts（edge-tts）" { uv run usine-cards tts @onlyArg } }
      "assets" { Invoke-Step "assets（Edge headless）" { uv run usine-cards assets @onlyArg } }
      "render" { Invoke-Step "render（$Workers workers）" { uv run usine-cards render @onlyArg --workers $Workers } }
      "qa"     { Invoke-Step "qa_all（32 单元全量验收）" { uv run python -m usine.qa_all } }
      "motion" { Invoke-Step "qa_motion（动态验收）" { uv run python -m usine.qa_motion } }
      "shape"  { Invoke-Step "qa_shape（人物层形状/连接/图层探针）" { uv run python -m usine.qa_shape @onlyArg } }
      "annot"  { Invoke-Step "qa_shape --annotate（缺陷框标注图）" { uv run python -m usine.qa_shape @onlyArg --annotate } }
      "fixverify" { Invoke-Step "verify_shape_fixes（探针反向验证）" { uv run python scripts/verify_shape_fixes.py } }
      "verify"     { Invoke-Step "verify_probes（探针反向验证统一入口：形状 + 文本契约）" { uv run python scripts/verify_probes.py } }
      "charsimg" {
        $poseArg = if ($Pose) { @("--pose", $Pose) } else { @() }
        Invoke-Step "usine-chars（人物形象体检台 -> build/chars/）" { uv run usine-chars all @onlyArg @poseArg --openness $Openness }
      }
    }
  }
}

switch ($Phase) {
  "tts"     { Invoke-Cards @("tts") }
  "assets"  { Invoke-Cards @("assets") }
  "render"  { Invoke-Cards @("render") }
  "qa"      { Invoke-Cards @("qa") }
  "qa-motion" { Invoke-Cards @("motion") }
  "qa-shape" { Invoke-Cards @("shape") }
  "qa-annotate" { Invoke-Cards @("annot") }
  "qa-shape-verify" { Invoke-Cards @("fixverify") }
  "verify"     { Invoke-Cards @("verify") }
  "chars"   { Invoke-Cards @("charsimg") }
  "all" {
    Invoke-Cards @("tts", "assets", "render", "qa", "motion", "shape")
    Write-Host "`n全部通过：32 单元就绪（28 卡 + 4 个 RTL 女性观众版）-> build/intro/" -ForegroundColor Green
  }
  # ---- 教学场景 A/B 对话线（M2）：-Scene <id>，-Only 用 locale 码 ----
  "scene-list"    { Invoke-Step "scene list" { uv run usine-scene list --scene $Scene } }
  "scene-tts"     { Invoke-Step "scene tts（edge-tts）" { uv run usine-scene tts @onlyArg --scene $Scene } }
  "scene-assets"  { Invoke-Step "scene assets（Edge headless）" { uv run usine-scene assets @onlyArg --scene $Scene } }
  "scene-render"  { Invoke-Step "scene render（$Workers workers）" { uv run usine-scene render @onlyArg --scene $Scene --workers $Workers } }
  "qa-scene"      { Invoke-Step "qa_scene（场景线验收）" { uv run python -m usine.qa_scene @onlyArg --scene $Scene } }
  "scene" {
    Invoke-Step "parse（lessons/$Scene/scene.md -> scene.json）" { uv run usine-parse --scene $Scene }
    Invoke-Step "scene tts（edge-tts）" { uv run usine-scene tts @onlyArg --scene $Scene }
    Invoke-Step "scene assets（Edge headless）" { uv run usine-scene assets @onlyArg --scene $Scene }
    Invoke-Step "scene render（$Workers workers）" { uv run usine-scene render @onlyArg --scene $Scene --workers $Workers }
    Write-Host "`n场景就绪：build/scene/scene-$Scene`_<locale>.mp4" -ForegroundColor Green
  }
  # ---- 教学文档线：lessons/<id>/scene.json + analysis -> build/lesson/<id>/index.html ----
  "dump-lesson" { Invoke-Step "dump-lesson（lessons/<id>/scene.json -> lessons/<id>/analysis/_source）" { uv run usine-dump-lesson @onlyArg --scene $Scene } }
  "lesson"      { Invoke-Step "lesson（scene.json + analysis -> build/lesson/<id>/index.html）" { uv run usine-lesson --scene $Scene } }
}

# ---- 自检：Phase 枚举与顶层 switch 的 case 标签必须逐项一致 ----
# 2026-10-04 在同一个坑上栽了两次，两次症状不同、都很坏：
#   ① 枚举漏列 → case 永不可达（死代码），手册教的命令直接报错；
#   ② 枚举列了、case 漏写 → switch 无匹配分支，**静默无输出**：
#      命令「跑完了」却什么也没干，比报错更危险（会让人以为验过了）。
# 所以不再靠人眼对齐：每次运行都机检一次，不一致直接 exit 2。
# 正则只认 2 空格缩进的 case（内层 Invoke-Cards 的 case 是 6 空格，不在其列）。
$topCases = [regex]::Matches((Get-Content $PSCommandPath -Raw), '(?m)^  "([a-z0-9-]+)"\s*\{') |
            ForEach-Object { $_.Groups[1].Value }
$declared = @((Get-Command $PSCommandPath).Parameters['Phase'].Attributes |
              Where-Object { $_ -is [System.Management.Automation.ValidateSetAttribute] } |
              ForEach-Object { $_.ValidValues })
$missingCase = @($declared | Where-Object { $_ -notin $topCases })   # 会静默无输出
$missingEnum = @($topCases  | Where-Object { $_ -notin $declared })   # 命令进不来
if ($missingCase.Count -or $missingEnum.Count) {
  Write-Host "run.ps1 自检失败：Phase 枚举与顶层 switch 不一致" -ForegroundColor Red
  if ($missingCase.Count) { Write-Host ("  枚举有、case 缺（跑起来静默无输出）: " + ($missingCase -join ", ")) -ForegroundColor Red }
  if ($missingEnum.Count) { Write-Host ("  case 有、枚举缺（命令进不来）:       " + ($missingEnum -join ", ")) -ForegroundColor Red }
  exit 2
}
