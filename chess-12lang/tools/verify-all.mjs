// tools/verify-all.mjs —— 12 支的渲染后验收全跑一遍（白页扫描 + 双版 AV 同步）
//
// 为什么单独一遍：批产脚本自己会跑这两道门，但它的日志是流式缓冲的，
// 事后从日志里反查退出码容易漏。这里**当场重跑、当场记**，结果落
// verify-report.json，§8 的表由它生成（不手抄）。
//
// 用法：node tools/verify-all.mjs
import { spawnSync } from 'node:child_process'
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const USINE = join(ROOT, '..', 'usine')
const TSX_CLI = join(USINE, 'node_modules', 'tsx', 'dist', 'cli.mjs')
const CLI = join(USINE, 'packages', 'cli', 'src', 'main.ts')
const DATA = JSON.parse(readFileSync(join(ROOT, 'data', 'series.json'), 'utf8'))

process.env['FEUILLE_BROWSER'] = process.env['FEUILLE_BROWSER']
  ?? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'

function run(args, cwd) {
  const r = spawnSync(process.execPath, [TSX_CLI, CLI, ...args],
    { cwd, encoding: 'utf8', timeout: 600_000, env: process.env, maxBuffer: 32 * 1024 * 1024 })
  return { code: r.status ?? -1, out: `${r.stdout ?? ''}${r.stderr ?? ''}` }
}

const out = []
for (const ep of DATA.episodes) {
  const dir = join(ROOT, 'episodes', ep.id)
  const vids = ['portrait', 'landscape']
    .map((f) => join(dir, 'out', `${ep.id}_${f}.mp4`))
    .filter((p) => existsSync(p))
  if (vids.length === 0) { console.log(`!! 缺成片：${ep.id}`); continue }

  const blank = run(['karaoke', 'scan-blank', ...vids], dir)
  const locales = ['nar', ...DATA.locales.map((l) => l.locale)].join(',')
  const syncs = []
  for (const f of ['portrait', 'landscape']) {
    const mp4 = join(dir, 'out', `${ep.id}_${f}.mp4`)
    if (!existsSync(mp4)) continue
    const framesDir = join(dir, f === 'portrait' ? 'frames_v' : 'frames')
    const r = run(['karaoke', 'verify-sync', '--video', mp4, '--frames', framesDir,
      '--tts', join(dir, 'tts'), '--locales', locales], dir)
    syncs.push({ f, code: r.code })
  }
  const rec = {
    id: ep.id,
    scanBlank: blank.code,
    syncs,
    ok: blank.code === 0 && syncs.every((s) => s.code === 0),
  }
  out.push(rec)
  console.log(`${rec.ok ? 'PASS' : 'FAIL'}  ${ep.id}  scan-blank=${blank.code}  ` +
    `sync=${syncs.map((s) => `${s.f}:${s.code}`).join(' ')}`)
  if (!rec.ok) console.log(blank.out.split('\n').slice(-8).join('\n'))
}

writeFileSync(join(ROOT, 'verify-report.json'), JSON.stringify(out, null, 1), 'utf8')
const bad = out.filter((r) => !r.ok)
console.log(`\n${out.length - bad.length}/${out.length} 支通过`)
process.exit(bad.length ? 1 : 0)
