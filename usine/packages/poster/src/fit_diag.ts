// fit_diag.ts — 解析模板 ?verify=1 模式倒出的逐格自适应诊断（DIAG {...} 块）。
// （promoted from skills/one-page-poster/scripts/fit_diag.py，P5-7e 归流）
//
// 一步式用法：`feuille poster page-dump "index.html?verify=1" diag.txt` 后
// `feuille poster fit-diag diag.txt`。逐格打印字号、词框
// （CSS px）、溢出旗标；任一溢出或字体未加载 → 退出码 1。词框直接喂
// check-overlay。
//
// **stdin 要分清两种情形**：CLI 里管道用法照旧（`| feuille poster fit-diag`）；
// 但**工具面里没有可用的 stdin**（FEUILLE_STDIN=off，见 dsh-plugin 的 install()）——
// 那时缺参数必须**立刻报错退出**，不许去读一块可能永远不会来的数据。
// 2026-10-22 实测：原来「不给参数就读 stdin」，工具面（dsh 的 `usine_poster`）调它时
// 既没有文件、stdin 又是宿主那根**永远不关**的管道，于是 `readFileSync(0)` **永久阻塞**：
// B 线 4 条 rollout 把整个时间预算烧在这个挂起的工具调用上，最后被时间上限掐死——
// 量到的全是「工具面挂死」，不是「智能体搭得好不好」。
import { existsSync, readFileSync } from 'node:fs'

/** 工具面里没有可用的 stdin（宿主那根管道永远不关）。 */
export function stdinUnavailable(): boolean {
  return process.env['FEUILLE_STDIN'] === 'off'
}

export function main(argv: string[]): number {
  const arg = argv[0]
  let raw: string
  if (arg === undefined) {
    if (stdinUnavailable() || process.stdin.isTTY) {
      console.error('usage: feuille poster fit-diag <dump.txt>   （`-` 表示从 stdin 读）')
      return 2
    }
    raw = readFileSync(0, 'utf-8')
  } else if (arg === '-') {
    raw = readFileSync(0, 'utf-8')
  } else {
    if (!existsSync(arg)) {
      console.error(`fit-diag：文件不存在：${arg}`)
      return 2
    }
    raw = readFileSync(arg, 'utf-8')
  }
  const m = raw.match(/DIAG (\{[\s\S]*?\})\s*</)
  if (!m) {
    console.log('no DIAG block found — render with ?verify=1 and --dump-dom')
    return 1
  }
  const d = JSON.parse(m[1]!) as {
    fonts: string
    cells: Array<{ lang: string; fs: number; word: string; overflowX: boolean; overflowY: boolean }>
  }

  const bad = d['fonts'].split(',').filter((s) => s && !s.endsWith('loaded'))
  for (const f of bad) console.log(`UNLOADED FONT: ${f}`)

  let fail = bad.length > 0
  for (const c of d['cells']) {
    let flag = ''
    if (c['overflowX']) {
      flag += ' <-- OVERFLOW-X'
      fail = true
    }
    if (c['overflowY']) {
      flag += ' <-- OVERFLOW-Y'
      fail = true
    }
    console.log(`${c['lang'].padEnd(10)} fs=${c['fs'].toFixed(1).padStart(6)} word=${c['word']}${flag}`)
  }
  console.log(fail ? 'fit diag: PROBLEMS' : 'fit diag: OK')
  return fail ? 1 : 0
}
