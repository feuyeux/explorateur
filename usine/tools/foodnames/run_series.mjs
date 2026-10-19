// run_series.mjs — 批量跑「各国美食名称」系列的若干期（并发上限可调）
//
// 一期一条命令跑完整条产线（生成→字体→韩语补丁→海报→三封面→门禁→配音→
// 旁白实测→床位反推→双画幅成片→同步/白帧验收→发布侧清单与门禁）。
// 本脚本只做**调度**：把若干期分批投到子进程里跑，任一期红即非零退出。
//
// 跑法（仓库根目录）：
//   node --import tsx tools/foodnames/run_series.mjs --eps 03 04 05 06 --jobs 2
//
// ⚠️ 只做本地渲染与门禁，零平台流量。
import { spawn } from 'node:child_process'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const USINE = resolve(here, '..', '..')
const DATA_DIR = join(here, 'data')
const EX_DIR = join(USINE, 'examples')

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}

/** 多值参数：收集 `--eps` 后面连续的裸值，直到下一个 `--` 开关。
 *
 * ⚠️ 只取 `argv[i+1]` 会**静默丢掉后面的期号**——`--eps 03 04` 会只跑 03，
 * 04 不报错也不跑，看起来像「排队没轮到」。多值参数必须吃到下一个开关。 */
function argList(name) {
  const i = process.argv.indexOf('--' + name)
  if (i < 0) return []
  const out = []
  for (let j = i + 1; j < process.argv.length; j++) {
    const v = process.argv[j]
    if (v.startsWith('--')) break
    out.push(v)
  }
  return out
}
const eps = argList('eps').flatMap((s) => s.split(/[\s,]+/)).filter(Boolean).map((s) => s.padStart(2, '0'))
const jobs = Number(arg('jobs', '2'))
const BED = resolve(arg('bed', join(EX_DIR, '_beds', 'bed-b.wav')))
const BED_JSON = BED + '.json'

if (eps.length === 0) {
  console.error('usage: run_series.mjs --eps 03 04 [--jobs 2] [--bed <wav>]')
  process.exit(2)
}
if (!existsSync(BED) || !existsSync(BED_JSON)) {
  console.error(`✖ 床不存在：${BED}（或边车 ${BED_JSON}）`)
  process.exit(1)
}

/** 期号 → 数据文件（按 epNN-*.json 匹配）。 */
function dataOf(ep) {
  const f = readdirSync(DATA_DIR).find((n) => n.startsWith(`ep${ep}-`) && n.endsWith('.json'))
  return f ? join(DATA_DIR, f) : null
}

const queue = []
for (const ep of eps) {
  const data = dataOf(ep)
  if (!data) { console.error(`✖ 找不到第 ${ep} 期的数据文件（data/ep${ep}-*.json）`); process.exit(1) }
  const meta = JSON.parse(readFileSync(data, 'utf8'))
  const out = join(EX_DIR, `foodnames-ep${ep}-${meta.slug}`)
  queue.push({ ep, data, out, title: meta.title_zh, slug: meta.slug })
}

console.log(`\n═══ 批量产线：${queue.length} 期 / 并发 ${jobs} ═══`)
for (const q of queue) console.log(`  第 ${q.ep} 期 ${q.title} (${q.slug}) → ${q.out}`)

let failed = null
let next = 0
let running = 0

function launch(q) {
  running += 1
  console.log(`\n▶▶▶ 启动 第 ${q.ep} 期 ${q.title}`)
  const p = spawn(process.execPath, [
    '--import', 'tsx', join(here, 'run_episode.mjs'),
    '--data', q.data, '--out', q.out,
    '--bgm', BED, '--bgm-json', BED_JSON,
  ], { cwd: USINE, stdio: ['ignore', 'pipe', 'pipe'] })
  let tail = ''
  p.stdout.on('data', (d) => {
    const s = d.toString()
    tail = (tail + s).slice(-4000)
    process.stdout.write(s.replace(/^/gm, `  [${q.ep}] `))
  })
  p.stderr.on('data', (d) => process.stderr.write(d.toString().replace(/^/gm, `  [${q.ep}!] `)))
  p.on('close', (code) => {
    running -= 1
    if (code !== 0 && !failed) {
      failed = { ep: q.ep, title: q.title, code, tail }
      console.error(`\n✖ 第 ${q.ep} 期 ${q.title} 失败（退出码 ${code}）——剩余的批次继续跑完再报。`)
    } else if (code === 0) {
      console.log(`\n✔✔ 第 ${q.ep} 期 ${q.title} 完成`)
    }
    pump()
  })
}

function pump() {
  while (!failed && running < jobs && next < queue.length) {
    launch(queue[next++])
  }
  if (!failed && running === 0 && next >= queue.length) {
    if (failed) process.exit(failed.code === 0 ? 1 : failed.code)
    console.log(`\n✅ ${queue.length} 期全部跑完（发布侧门禁在各自 runner 内已跑）`)
    process.exit(0)
  }
}
pump()
