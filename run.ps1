#!/usr/bin/env pwsh
<#
run.ps1 — 管线统一入口（uv 管理单一 .venv：edge-tts / Pillow / numpy 全在一个环境，见 pyproject.toml）
  tts     edge-tts 7.2.8：逐行合成 + 词级时间戳
  assets  Edge headless 渲染文字层 PNG（双色 matte 抠像）
  render  Pillow+numpy 帧渲染 + ffmpeg
  qa / qa-motion / all          亮相卡验收与全流程
  scene / scene-list / qa-scene 教学场景 A/B 对话线（M2，-Scene <id> 选场景）
  lesson / dump-lesson          教学文档（scene_<id>.json + lesson_analysis -> build/lesson）
用法：.\run.ps1 all | .\run.ps1 render -Only xiaoman,layla -Workers 7
      .\run.ps1 scene            # 14 语种场景：parse → tts → assets → render
      .\run.ps1 scene -Only zh-CN
首次使用：uv sync（建 .venv 并装锁定的依赖；抖音工具另需 uv sync --group douyin + playwright install chromium）
#>
param(
  [Parameter(Position = 0)][ValidateSet("tts", "assets", "render", "qa", "qa-motion", "all", "scene", "scene-tts", "scene-assets", "scene-render", "scene-list", "qa-scene", "lesson", "dump-lesson")][string]$Phase = "all",
  [string]$Only = "",
  [string]$Scene = "colors",
  [int]$Workers = 7
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) { Write-Host "==> uv sync（.venv 不存在，先建环境）" -ForegroundColor Cyan; uv sync }

$onlyArg = if ($Only) { @("--only", $Only) } else { @() }

function Invoke-Step([string]$Name, [scriptblock]$Step) {
  Write-Host "`n==> $Name" -ForegroundColor Cyan
  & $Step
  if ($LASTEXITCODE -ne 0) { Write-Error "$Name 失败 (rc=$LASTEXITCODE)"; exit $LASTEXITCODE }
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
    }
  }
}

switch ($Phase) {
  "tts"     { Invoke-Cards @("tts") }
  "assets"  { Invoke-Cards @("assets") }
  "render"  { Invoke-Cards @("render") }
  "qa"      { Invoke-Cards @("qa") }
  "qa-motion" { Invoke-Cards @("motion") }
  "all" {
    Invoke-Cards @("tts", "assets", "render", "qa", "motion")
    Write-Host "`n全部通过：32 单元就绪（28 卡 + 4 个 RTL 女性观众版）-> build/intro/" -ForegroundColor Green
  }
  # ---- 教学场景 A/B 对话线（M2）：-Scene <id>，-Only 用 locale 码 ----
  "scene-list"    { Invoke-Step "scene list" { uv run usine-scene list --scene $Scene } }
  "scene-tts"     { Invoke-Step "scene tts（edge-tts）" { uv run usine-scene tts @onlyArg --scene $Scene } }
  "scene-assets"  { Invoke-Step "scene assets（Edge headless）" { uv run usine-scene assets @onlyArg --scene $Scene } }
  "scene-render"  { Invoke-Step "scene render（$Workers workers）" { uv run usine-scene render @onlyArg --scene $Scene --workers $Workers } }
  "qa-scene"      { Invoke-Step "qa_scene（场景线验收）" { uv run python -m usine.qa_scene @onlyArg --scene $Scene } }
  "scene" {
    Invoke-Step "parse（scene-$Scene.md -> scene_$Scene.json）" { uv run usine-parse --scene $Scene }
    Invoke-Step "scene tts（edge-tts）" { uv run usine-scene tts @onlyArg --scene $Scene }
    Invoke-Step "scene assets（Edge headless）" { uv run usine-scene assets @onlyArg --scene $Scene }
    Invoke-Step "scene render（$Workers workers）" { uv run usine-scene render @onlyArg --scene $Scene --workers $Workers }
    Write-Host "`n场景就绪：build/scene/scene-$Scene`_<locale>.mp4" -ForegroundColor Green
  }
  # ---- 教学文档线：scene_<id>.json + lesson_analysis -> build/lesson/index.html ----
  "dump-lesson" { Invoke-Step "dump-lesson（scene json -> lesson_analysis/_source）" { uv run usine-dump-lesson @onlyArg } }
  "lesson"      { Invoke-Step "lesson（scene json + lesson_analysis -> build/lesson/index.html）" { uv run usine-lesson } }
}
