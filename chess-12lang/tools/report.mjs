// tools/report.mjs —— 生成 §8 的实测结果表（数据来自成片本身与批产日志，不手抄）
//
// 用法：node tools/report.mjs
// 输出：12 支 × 横竖两版的实测时长 / 画幅 / 文件大小 + 各道门的退出码
import { readFileSync, existsSync, statSync, readdirSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const DATA = JSON.parse(readFileSync(join(ROOT, 'data', 'series.json'), 'utf8'))

function probe(p) {
  if (!existsSync(p)) return null
  const r = spawnSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0',
    '-show_entries', 'stream=width,height:format=duration', '-of', 'json', p],
    { encoding: 'utf8' })
  try {
    const j = JSON.parse(r.stdout)
    const s = j.streams?.[0] ?? {}
    return { w: s.width, h: s.height, dur: Number(j.format?.duration) }
  } catch { return null }
}

// 验收结果来自 verify-all.mjs 的当场复验（verify-report.json），不从流式日志反查
const gates = new Map()
const vrPath = join(ROOT, 'verify-report.json')
if (existsSync(vrPath)) {
  for (const r of JSON.parse(readFileSync(vrPath, 'utf8'))) gates.set(r.id, r)
}

const rows = []
for (const ep of DATA.episodes) {
  const dir = join(ROOT, 'episodes', ep.id)
  const p = probe(join(dir, 'out', `${ep.id}_portrait.mp4`))
  const l = probe(join(dir, 'out', `${ep.id}_landscape.mp4`))
  const g = gates.get(ep.id) ?? {}
  const size = (f) => {
    const q = join(dir, 'out', f)
    return existsSync(q) ? `${(statSync(q).size / 1024 / 1024).toFixed(1)}MB` : '—'
  }
  const qa = join(dir, 'qa')
  const qaN = existsSync(qa) ? readdirSync(qa).filter((f) => f.endsWith('.png')).length : 0
  rows.push({
    no: ep.no, id: ep.id, title: ep.title_zh,
    pdur: p ? p.dur.toFixed(1) : '—', pspec: p ? `${p.w}×${p.h}` : '—', psize: size(`${ep.id}_portrait.mp4`),
    ldur: l ? l.dur.toFixed(1) : '—', lspec: l ? `${l.w}×${l.h}` : '—', lsize: size(`${ep.id}_landscape.mp4`),
    g, qaN,
  })
}

console.log('| 话 | 标题 | 竖版时长 | 竖版画幅 | 竖版体积 | 横版时长 | 横版画幅 | 横版体积 | scan-blank | verify-sync×2 | 抽帧 |')
console.log('|---|---|---|---|---|---|---|---|---|---|---|')
for (const r of rows) {
  const g = r.g
  const sb = g.scanBlank === undefined ? '—' : g.scanBlank === 0 ? 'PASS' : `FAIL(${g.scanBlank})`
  const vs = (g.syncs ?? []).map((s) => s.code)
  const vsStr = vs.length === 0 ? '—' : (vs.every((x) => x === 0) ? `PASS×${vs.length}` : `FAIL(${vs.join(',')})`)
  console.log(`| ${String(r.no).padStart(2, '0')} | ${r.title} | ${r.pdur}s | ${r.pspec} | ${r.psize} | ${r.ldur}s | ${r.lspec} | ${r.lsize} | ${sb} | ${vsStr} | ${r.qaN} 帧 |`)
}
