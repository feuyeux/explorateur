#!/usr/bin/env pwsh
<#
run.ps1 — 亮相卡管线统一入口（两解释器分工见 render-handbook.md §1）
  tts     系统 Python（edge-tts 7.2.8）：逐行合成 + 词级时间戳
  assets  任意 Python：Edge headless 渲染文字层 PNG（双色 matte 抠像）
  render  捆绑 DSH Python（Pillow+numpy）：帧渲染 + ffmpeg
  qa / qa-motion / all：验收与全流程
用法：.\run.ps1 all | .\run.ps1 render -Only xiaoman,layla -Workers 7
#>
param(
  [Parameter(Position = 0)][ValidateSet("tts", "assets", "render", "qa", "qa-motion", "all")][string]$Phase = "all",
  [string]$Only = "",
  [int]$Workers = 7
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$SysPy = "python"   # edge-tts 装在系统 Python
$DshPy = "C:\Users\feuye\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $DshPy)) { Write-Error "捆绑 Python 不存在：$DshPy（见 render-handbook.md §1）" }

$onlyArg = if ($Only) { @("--only", $Only) } else { @() }

function Invoke-Step([string]$Name, [scriptblock]$Step) {
  Write-Host "`n==> $Name" -ForegroundColor Cyan
  & $Step
  if ($LASTEXITCODE -ne 0) { Write-Error "$Name 失败 (rc=$LASTEXITCODE)"; exit $LASTEXITCODE }
}

switch ($Phase) {
  "tts" { Invoke-Step "tts（系统 Python）" { & $SysPy intro_cards.py tts @onlyArg } }
  "assets" { Invoke-Step "assets（Edge headless）" { & $DshPy intro_cards.py assets @onlyArg } }
  "render" { Invoke-Step "render（捆绑 Python，$Workers workers）" { & $DshPy intro_cards.py render @onlyArg --workers $Workers } }
  "qa" { Invoke-Step "qa_all（28 卡全量验收）" { & $DshPy qa_all.py } }
  "qa-motion" { Invoke-Step "qa_motion（动态验收）" { & $DshPy qa_motion.py } }
  "all" {
    Invoke-Step "tts（系统 Python）" { & $SysPy intro_cards.py tts @onlyArg }
    Invoke-Step "assets（Edge headless）" { & $DshPy intro_cards.py assets @onlyArg }
    Invoke-Step "render（捆绑 Python，$Workers workers）" { & $DshPy intro_cards.py render @onlyArg --workers $Workers }
    Invoke-Step "qa_all（28 卡全量验收）" { & $DshPy qa_all.py }
    Invoke-Step "qa_motion（动态验收）" { & $DshPy qa_motion.py }
    Write-Host "`n全部通过：28 × 10s 亮相卡就绪 -> build/intro/" -ForegroundColor Green
  }
}
