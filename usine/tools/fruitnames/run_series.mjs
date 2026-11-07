// run_series.mjs — 批量跑若干期（并发可调；任一期红即非零退出）
//
// 跑法（usine/ 下）：
//   pnpm exec tsx tools/fruitnames/run_series.mjs --eps 2,3,4 --jobs 2
//
// 并发别开太大：每期都要起 headless Chrome 截帧，抢得厉害会出白帧/错图
// （scan-blank 与 verify-sync 会响亮地红，不会静默过）。22 核机器 --jobs 2 稳。
import { spawn } from 'node:child_process'
import { join, resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const USINE = resolve(here, '..', '..')

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}
const EPS = String(arg('eps', '1')).split(',').map((s) => Number(s.trim())).filter(Boolean)
const JOBS = Number(arg('jobs', '1'))
const BGM = arg('bgm') ? resolve(arg('bgm')) : null
const BGM_JSON = arg('bgm-json') ? resolve(arg('bgm-json')) : null
if (!EPS.length) { console.error('usage: run_series.mjs --eps 2,3,... [--jobs 2] [--bgm bed.wav --bgm-json bed.wav.json]'); process.exit(2) }

console.log(`跑 ${EPS.length} 期（ep${EPS.join(', ep')}），并发 ${JOBS}${BGM ? `，床 ${BGM.split(/[\\/]/).pop()}` : '，无床'}`)
const queue = [...EPS]
const failed = []
const running = new Map()

function startNext() {
  const ep = queue.shift()
  if (ep === undefined) return
  const extra = BGM ? ['--bgm', BGM, '--bgm-json', BGM_JSON] : []
  const p = spawn(process.execPath, [
    '--import', 'tsx', join(here, 'run_episode.mjs'),
    '--episode', String(ep), '--out', `examples/fruitnames-ep${String(ep).padStart(2, '0')}`,
    ...extra,
  ], { cwd: USINE, stdio: ['ignore', 'pipe', 'pipe'] })
  running.set(ep, p)
  let out = ''
  p.stdout.on('data', (d) => { out += d })
  p.stderr.on('data', (d) => { out += d })
  p.on('exit', (code) => {
    running.delete(ep)
    if (code !== 0) {
      failed.push(ep)
      console.error(`\n✖✖ ep${ep} 失败（退出码 ${code}）\n${out.slice(-2500)}`)
    } else {
      console.log(`\n✅✅ ep${String(ep).padStart(2, '0')} 完成`)
    }
    drain()
  })
  console.log(`▶▶ ep${String(ep).padStart(2, '0')} 启动`)
}
function drain() {
  while (running.size < JOBS && queue.length) startNext()
  if (!running.size && !queue.length) {
    const ok = EPS.length - failed.length
    console.log(`\n═══ 批量结束：${ok}/${EPS.length} 成功${failed.length ? `；失败：ep${failed.join(', ep')}` : ''}`)
    process.exit(failed.length ? 1 : 0)
  }
}
drain()
