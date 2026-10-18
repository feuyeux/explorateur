// audio_profile.ts — 音频拆轨对比：定位「人声消失 / BGM 忽隐忽现 / 提前静音」
// 类问题（multilingual-video-poetry/scripts/audio_profile.py 的 TS 归流）。
//
// 只听最终混音定位不了问题——把滤镜图拆成独立分轨逐段对齐才有诊断力：
// 人声干轨 vs 被压 BGM 轨 vs 最终混音，同源同长横向对比。
// 归流决定：ffmpeg 解析走 @feuille/core platform 唯一实现（Python _bin 的
// 平行拷贝不迁移即消除）；解码失败必须响亮失败（纪律 19：禁止静默兜底）。
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'

import { FeuilleError, platform } from '@feuille/core'

/** Python __doc__ 整段是 usage 输出的一部分（缺参时 print(__doc__)）——原样保留。 */
export const DOC = `音频拆轨对比：定位「人声消失 / BGM 忽隐忽现 / 提前静音」类问题。

只听最终混音定位不了问题——把滤镜图拆成独立分轨逐段对齐才有诊断力：

    人声干轨  vs  被压 BGM 轨  vs  最终混音

三者同源同长，同一时间点横向对比，一眼看出是哪一环丢的。
本文两个真实 bug 都是这么定位的（人声被压掉 25–30 dB、BGM 提前 2.6 秒静音）。

## 用法

    feuille poetry audio-profile <音频文件> [窗口定义...]

窗口从 stdin 的 JSON 读，形如（**终端下不传窗口 = 直接出全曲曲线**——
只有管道 / 重定向才读 stdin，交互终端不会等输入）：

    {"voice": [[0.55, 2.88], [5.75, 8.22]], "gaps": [[3.13, 5.50]]}

不传窗口时只打印全曲逐 0.1s 电平曲线。

    # 全曲曲线
    feuille poetry audio-profile mix.m4a

    # 带人声段/空档段对比（推荐）
    echo '{"voice":[[0.55,2.88]],"gaps":[[3.13,5.50]]}' | \\
        feuille poetry audio-profile mix.m4a

    # 同上，外加每段 RMS 交叉核对（判据仍用 LUFS，RMS 只作旁证）
    echo '{"voice":[[0.55,2.88]],"gaps":[[3.13,5.50]]}' | \\
        feuille poetry audio-profile mix.m4a --rms

## 输出

- 无窗口：逐 0.1s 的 RMS 电平条 + 峰值/静音段提示
- 有窗口：人声段 vs 空档段的平均电平，以及差值（差值 < 8 dB 说明人声被盖住了）
`

/** 外部可执行文件经 @feuille/core platform 解析（AGENTS.md 跨平台硬约定 1）。
 * 模块级 throw 会破坏 barrel 导入——函数内懒解析，代价是 import 永不炸。 */
function ffmpegBin(): string {
  const got = platform.ffmpeg()
  if (!got) {
    throw new FeuilleError(
      '找不到 ffmpeg：请安装后重跑（@feuille/core platform 解析，'
      + '外部可执行文件不许写死路径名）')
  }
  return got
}

/** 解码器统一入口：超时与退出码都要响亮失败。
 *
 * 解码失败时测量行不会出现，正则失配会让上层拿到 None——再把 None
 * 印成「静音」，就把真错误伪装成了「测不出来」（纪律 19：禁止静默
 * 兜底）。所以退出码非 0 必须在这里就失败，带上 stderr 尾巴。 */
function runFfmpeg(args: string[], timeout = 300): string {
  const r = spawnSync(ffmpegBin(), args, { encoding: 'utf8', timeout: timeout * 1000 })
  if (r.error) {
    if ((r.error as NodeJS.ErrnoException).code === 'ETIMEDOUT') {
      throw new FeuilleError(`ffmpeg 超时（${timeout}s）：${args.slice(0, 6).join(' ')} …`)
    }
    throw new FeuilleError(`ffmpeg 启动失败：${r.error.message}`)
  }
  if (r.status !== 0) {
    throw new FeuilleError(`ffmpeg 退出 ${r.status}：${(r.stderr ?? '').slice(-300)}`)
  }
  return r.stderr ?? ''
}

/** 单段 RMS（dB）。volumedetect 的输出在 info 级，**不要加 -v error**。 */
export function meanVolume(path: string, start: number, dur: number): number | null {
  const stderr = runFfmpeg([
    '-ss', start.toFixed(3), '-t', Math.max(0.05, dur).toFixed(3),
    '-i', path, '-af', 'volumedetect', '-f', 'null', '-',
  ])
  const m = /mean_volume: (-?[\d.]+) dB/.exec(stderr)
  return m ? Number(m[1]) : null
}

/** 单段 K 加权积分响度（LUFS）。
 *
 * **配比判据必须用 LUFS，不能用 RMS。** 同样 −20 dB RMS，密集音乐和语音的
 * 听感响度完全不同：实测同一段混音，RMS 口径差 6.3 dB，LUFS 口径差 8.2 dB。
 * 阈值是按 LUFS 定标的，拿 RMS 去比会得出「不达标」的假结论。要看 RMS
 * 作交叉核对，用 `--rms`（不是拿来比阈值的）。 */
export function lufs(path: string, start: number, dur: number): number | null {
  const stderr = runFfmpeg([
    '-ss', start.toFixed(3), '-t', Math.max(0.1, dur).toFixed(3),
    '-i', path, '-af', 'loudnorm=I=-16:print_format=json', '-f', 'null', '-',
  ])
  const m = /"input_i"\s*:\s*"?(-?[\d.]+)/.exec(stderr)
  return m ? Number(m[1]) : null
}

/** 全曲逐 N 帧电平曲线。
 *
 * 注意：astats 的逐点数值与 volumedetect 不完全一致，适合看**趋势**，
 * 下结论前请用 `--rms` 让窗口模式顺带打出每段 RMS 交叉核对。 */
export function curve(path: string, reset = 5): Record<number, number> {
  const stderr = runFfmpeg([
    '-i', path, '-af',
    `astats=metadata=1:reset=${reset},`
      + 'ametadata=print:key=lavfi.astats.Overall.RMS_level',
    '-f', 'null', '-',
  ])
  let cur: number | null = null
  const out: Record<number, number> = {}
  for (const line of stderr.split('\n')) {
    const m = /pts_time:([\d.]+)/.exec(line)
    if (m) cur = Number(m[1])
    const m2 = /lavfi\.astats\.Overall\.RMS_level=(-?[\d.]+|-\w+)/.exec(line)
    if (m2 && cur !== null) {
      // astats 对静音输出 `-inf`；Number 能解析它但不抛异常，
      // 会一路带到取整才变成 Infinity——必须在这里就归一。
      const v = Number(m2[1])
      out[Math.round(cur * 10) / 10] = Number.isFinite(v) ? v : -99.0
    }
  }
  return out
}

/** 原样保留：Python 原版就定义了它而 main 未引用——镜像，不擅自删。 */
export function inWindows(t: number, wins: ReadonlyArray<readonly [number, number]>): boolean {
  return wins.some(([a, b]) => a <= t && t <= b)
}

/** 读 stdin（管道/重定向时）；TTY 下返回空串不挂起（Python isatty 同款）。
 * 非管道场景的读失败（EAGAIN 等）按空串处理，与 Python stdin.read() 等 EOF 同效。 */
function readStdin(): string {
  if (process.stdin.isTTY) return ''
  try {
    return readFileSync(0, 'utf8')
  } catch {
    return ''
  }
}

export type WinSpec = { voice?: Array<[number, number]>; gaps?: Array<[number, number]> }

/** CLI 入口：`feuille poetry audio-profile <音频文件> [窗口 JSON...] [--rms]`。
 * 缺文件 → print(__doc__) + 2；文件不在盘 → 「找不到」+ 2（Python 同款）。 */
export function main(argv: string[]): number {
  if (argv.length < 1) {
    console.log(DOC)
    return 2
  }
  const path = argv[0]!
  if (!existsSync(path)) {
    console.log(`找不到 ${path}`)
    return 2
  }

  // 终端下不传窗口 = 直接出全曲曲线；只有管道/重定向才读 stdin（否则挂起）。
  // argv 项之间要加空格拼回 JSON（"".join 会把被 shell 拆开的 JSON 拼坏）；
  // --rms 是开关，不是窗口 JSON 的一部分。
  const rest = argv.slice(1)
  const wantRms = rest.includes('--rms')
  const raw = rest.filter((x) => x !== '--rms').join(' ') || readStdin()
  let spec: WinSpec = { voice: [], gaps: [] }
  if (raw.trim()) spec = JSON.parse(raw) as WinSpec

  const voice = spec.voice ?? []
  const gaps = spec.gaps ?? []

  if (voice.length || gaps.length) {
    console.log(`${baseName(path)}  （窗口测量用 LUFS，感知口径）\n`)

    const measureWins = (wins: ReadonlyArray<readonly [number, number]>) =>
      wins.map(([a, b]) => {
        const lv = lufs(path, a, b - a)
        const rv = wantRms ? meanVolume(path, a, b - a) : null
        return { a, b, lv, rv }
      })
    const vs = measureWins(voice)
    const gs = measureWins(gaps)
    for (const [label, ws] of [['【人声段】', vs], ['【空档段（底床）】', gs]] as const) {
      console.log(label)
      for (const { a, b, lv, rv } of ws) {
        let s = `  ${a.toFixed(2).padStart(6)}–${b.toFixed(2).padStart(6)}s   `
          + (lv !== null ? `${lv.toFixed(1).padStart(7)} LUFS` : '      静音')
        if (wantRms) {
          s += rv !== null ? `   （RMS ${rv.toFixed(1).padStart(6)} dB）` : '   （RMS 静音）'
        }
        console.log(s)
      }
    }
    const vv = vs.map((w) => w.lv).filter((x): x is number => x !== null)
    const gg = gs.map((w) => w.lv).filter((x): x is number => x !== null)
    if (vv.length && gg.length) {
      const mv = vv.reduce((s, x) => s + x, 0) / vv.length
      const mg = gg.reduce((s, x) => s + x, 0) / gg.length
      const d = mv - mg
      const ok = d >= 8 ? '✓ 人声盖过底床' : '✗ 人声未高出底床 8 dB'
      console.log(`\n人声均值 ${mv.toFixed(1)} LUFS · 底床均值 ${mg.toFixed(1)} LUFS`
        + ` · 差 ${d >= 0 ? '+' : ''}${d.toFixed(1)} dB  ${ok}`)
    }
    return 0
  }

  const c = curve(path)
  console.log(`${baseName(path)} 逐 0.1s 电平\n`)
  let prev: number | null = null
  for (const t of Object.keys(c).map(Number).sort((x, y) => x - y)) {
    const db = c[t]!
    const bar = '#'.repeat(Math.max(0, Math.min(50, Math.trunc((db + 60) * 0.9))))
    let mark = ''
    if (db <= -70) {
      mark = '  ← 静音'
      if (prev !== null && prev > -60) mark += '（此处起断流）'
    }
    console.log(`${t.toFixed(1).padStart(6)}s  ${bar.padEnd(50)} ${db.toFixed(1).padStart(6)}${mark}`)
    if (db > -60) prev = db
  }
  return 0
}

function baseName(p: string): string {
  const i = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'))
  return i < 0 ? p : p.slice(i + 1)
}
