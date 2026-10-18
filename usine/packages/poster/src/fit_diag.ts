// fit_diag.ts — 解析模板 ?verify=1 模式倒出的逐格自适应诊断（DIAG {...} 块）。
// （promoted from skills/one-page-poster/scripts/fit_diag.py，P5-7e 归流）
//
// 一步式用法：`feuille poster page-dump "index.html?verify=1" diag.txt` 后
// `feuille poster fit-diag diag.txt`（也支持 stdin 管道）。逐格打印字号、词框
// （CSS px）、溢出旗标；任一溢出或字体未加载 → 退出码 1。词框直接喂
// check-overlay。
import { readFileSync } from 'node:fs'

export function main(argv: string[]): number {
  const raw = argv[0] !== undefined ? readFileSync(argv[0], 'utf-8') : readFileSync(0, 'utf-8')
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
