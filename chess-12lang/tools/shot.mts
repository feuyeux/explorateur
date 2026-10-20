// tools/shot.mts —— 截某个场景的图（人眼看帧用；门禁全绿 ≠ 画面正确）
//
// 用法：tsx tools/shot.mts <video_src.html> <lang> <out.png> [fmt] [state]
//   fmt   v = 竖版 1080×1920（默认），不传 = 横版 1920×1080
//   state 数字 = 第几个 token 高亮（99 = 全部唱完，字最实）
//
// 两条环境铁律（README「环境坑」）：Chrome 走绝对路径输出；Edge 从 Node 子进程
// 启动不落盘截图，所以这里固定用 Chrome。
import { spawnSync } from 'node:child_process'
import { existsSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const html = process.argv[2]!
const lang = process.argv[3] ?? 'nar'
const out = resolve(process.argv[4] ?? 'shot.png')
const fmt = process.argv[5] === 'v' ? 'v' : ''
const state = process.argv[6] ?? '99'

// 窗口必须等于画幅：场景是 1920×1080 / 1080×1920 的定尺页面，窗口不匹配
// 只会截到一角（之前横版帧只截到左上 1080×1080，误判成版式塌了）。
const [W, H] = fmt === 'v' ? [1080, 1920] : [1920, 1080]

rmSync(out, { force: true })
const url = `${pathToFileURL(html).href}?lang=${encodeURIComponent(lang)}&state=${state}&fmt=${fmt}`
const args = [
  '--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1',
  `--window-size=${W},${H}`, `--screenshot=${out}`, '--virtual-time-budget=4000', url,
]
const r = spawnSync(CHROME, args, { encoding: 'utf8', timeout: 120000 })
if (!existsSync(out)) {
  console.error(`FAIL: 没出图 status=${r.status} ${(r.stderr ?? '').slice(0, 300)}`)
  process.exit(1)
}
console.log(`${out} ok`)
