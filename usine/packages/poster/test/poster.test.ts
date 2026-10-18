// poster.test.ts — @feuille/poster 反向验证门禁（one-page-poster 十脚本归流）。
//
//   fetch_fonts   uniq/pyQuote 纯函数 + 真 Google Fonts css2 子集端点 e2e
//                （免费端点，不在额度红线内——edge-tts 同款口径）
//   assemble     标记全出现处替换 / 无标记原样 / --theme / 共享样式表注入（子进程）
//   make_covers  变体 CSS + boot 脚本注入 / 标记不在原样
//   fit_diag     OK / 溢出 / 字体未载 / 无 DIAG 块
//   audit_charset 字符子集门三判据（verify_skill_scripts.py §4 随归流移植）
//                + 垫片规则绑定门（A-03 机器形态）+ unescapeHtml 口径
//   verify_colors 合成网格放行 / 缺色拦截 / 网格缺失响亮失败
//   check_overlay 对齐 PASS / 错位 FAIL（np.roll 环绕语义按原样镜像）
//   render e2e    render_poster（query 后缀透传）+ render_page dump/render
import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import sharp from 'sharp'
import { afterAll, afterEach, describe, expect, it, vi } from 'vitest'

import { FeuilleError, platform } from '@feuille/core'

import * as poster from '../src/index.js'
import { check, checkPatchBindings, unescapeHtml } from '../src/audit_charset.js'
import { pyQuote, uniq } from '../src/fetch_fonts.js'

const HAS_BROWSER = platform.browserPath() !== null
const USINE = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const TSX_LOADER = `file://${join(USINE, 'node_modules/tsx/dist/loader.mjs')}`

function makeTmp(): string {
  return mkdtempSync(join(tmpdir(), 'poster-test-'))
}

async function svgPng(path: string, svg: string): Promise<void> {
  await sharp(Buffer.from(svg)).png().toFile(path)
}

function captureLog(): { log: string[] } {
  const log: string[] = []
  vi.spyOn(console, 'log').mockImplementation((...a: unknown[]) => {
    log.push(a.map(String).join(''))
  })
  vi.spyOn(console, 'error').mockImplementation((...a: unknown[]) => {
    log.push(a.map(String).join(''))
  })
  return { log }
}

afterEach(() => {
  vi.restoreAllMocks()
})

// ============ fetch_fonts ============

describe('fetch_fonts 纯函数（Python 口径）', () => {
  it('uniq：去空格/换行、去重、按码点排序 + 尾随空格', () => {
    expect(uniq('ba ab\nba')).toBe('ab ')
    expect(uniq('가나다')).toBe('가나다 ')
    expect(uniq(' \n ')).toBe(' ')
  })

  it('pyQuote：urllib.parse.quote（safe=/）——大写十六进制、多字节逐字节转义', () => {
    expect(pyQuote('Noto Sans+KR:wght@500')).toBe('Noto%20Sans%2BKR%3Awght%40500')
    expect(pyQuote('a/b_c.d-e~')).toBe('a/b_c.d-e~')
    expect(pyQuote('ब')).toBe('%E0%A4%AC') // 天城文 BA：UTF-8 三字节
    expect(pyQuote('차')).toBe('%EC%B0%A8')
  })
})

describe('fetch_fonts e2e：Google Fonts css2 子集端点（免费，不在额度红线内）', () => {
  it('fonts.json → fonts.css：@font-face 内嵌 base64 woff2 + family 改名', { timeout: 120_000 }, async () => {
    const d = makeTmp()
    try {
      const spec = join(d, 'fonts.json')
      writeFileSync(spec, JSON.stringify([
        { family: 'OBS KR', google: 'Noto+Sans+KR:wght@400', text: '차' },
      ]), 'utf-8')
      const { log } = captureLog()
      const rc = await poster.fetch_fonts.main([spec])
      expect(rc).toBe(0)
      const css = readFileSync(join(d, 'fonts.css'), 'utf-8')
      expect(css).toContain('@font-face')
      expect(css).toContain("font-family: 'OBS KR'")
      expect(css).toContain('data:font/woff2;base64,')
      expect(log.join('\n')).toContain('wrote')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })
})

// ============ assemble ============

describe('assemble：标记注入', () => {
  it('/*__FONTS__*/ 全出现处替换（Python str.replace 镜像）+ fonts.css 内嵌', () => {
    const d = makeTmp()
    try {
      const src = join(d, 'poster_src.html')
      const out = join(d, 'index.html')
      writeFileSync(src, '<style>a/*__FONTS__*/b/*__FONTS__*/c</style>', 'utf-8')
      writeFileSync(join(d, 'fonts.css'), 'FONTCSS', 'utf-8')
      const rc = poster.assemble.main([src, out])
      expect(rc).toBe(0)
      const got = readFileSync(out, 'utf-8')
      expect(got).toBe('<style>aFONTCSSbFONTCSSc</style>')
      expect(got).not.toContain('/*__FONTS__*/')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('标记不在 → 原样写回，不报错', () => {
    const d = makeTmp()
    try {
      const src = join(d, 'poster_src.html')
      const out = join(d, 'index.html')
      writeFileSync(src, '<html><body>plain</body></html>', 'utf-8')
      expect(poster.assemble.main([src, out])).toBe(0)
      expect(readFileSync(out, 'utf-8')).toBe('<html><body>plain</body></html>')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('--theme：首处 <body 注入 data-theme（已有 data-theme 不重复注入）', () => {
    const d = makeTmp()
    try {
      const src = join(d, 'poster_src.html')
      const out = join(d, 'index.html')
      writeFileSync(src, '<html><body class="x"><p>hi</p></body></html>', 'utf-8')
      expect(poster.assemble.main([src, out, '--theme', 'autumn'])).toBe(0)
      expect(readFileSync(out, 'utf-8')).toContain('<body data-theme="autumn" class="x">')

      const out2 = join(d, 'index2.html')
      writeFileSync(src, '<html><body data-theme="old"><p>hi</p></body></html>', 'utf-8')
      expect(poster.assemble.main([src, out2, '--theme', 'autumn'])).toBe(0)
      expect(readFileSync(out2, 'utf-8')).not.toContain('data-theme="autumn"')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('共享样式表注入：cwd 旁的 theme-tokens.css / typography-base.css 进标记位（子进程真跑）', () => {
    const d = makeTmp()
    try {
      // assemble.main 以 process.cwd() 定位共享样式表——进程内 chdir 会波及同
      // 进程的其它并行测试文件，改用子进程 + cwd 控制
      writeFileSync(join(d, 'theme-tokens.css'), '/*TOKENS*/', 'utf-8')
      writeFileSync(join(d, 'typography-base.css'), '/*TYPO*/', 'utf-8')
      writeFileSync(join(d, 'poster_src.html'), '<style>/*__FONTS__*/</style>', 'utf-8')
      const leaf = `file://${join(USINE, 'packages/cli/src/leaves/poster-assemble.ts')}`
      const r = spawnSync(process.execPath, [
        '--import', TSX_LOADER, '--input-type=module', '-e',
        `import { main } from ${JSON.stringify(leaf)};`
        + ` process.exit(await main([${JSON.stringify('poster_src.html')}, ${JSON.stringify('out.html')}]))`,
      ], { cwd: d, encoding: 'utf8' })
      expect(r.status).toBe(0)
      const got = readFileSync(join(d, 'out.html'), 'utf-8')
      expect(got).toContain('/* Extracted Theme Tokens */\n/*TOKENS*/')
      expect(got).toContain('/* Extracted Typography & Component Base */\n/*TYPO*/')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })
})

// ============ make_covers ============

describe('make_covers：全屏封面变体派生', () => {
  it('ruby rt 标记位前插变体 CSS、自适应脚本前插 boot；缺省输出到 src 同目录', () => {
    const d = makeTmp()
    try {
      const src = join(d, 'poster_src.html')
      writeFileSync(src,
        '<style>ruby rt { font-weight: 500; }\n</style>\n<script>\n// per-cell auto-fit\nfoo();</script>',
        'utf-8')
      expect(poster.make_covers.main([src])).toBe(0)
      const got = readFileSync(join(d, 'cover_src.html'), 'utf-8')
      expect(got).toContain('fullscreen cover variants (make_covers.py)')
      expect(got).toContain('const FMT = new URLSearchParams(location.search).get("fmt");')
      // boot 必须在自适应脚本之前（fmt class 决定后续排版）
      expect(got.indexOf('const FMT')).toBeLessThan(got.indexOf('<script>\n// per-cell auto-fit'))
      // 原子性检查：poster_src.html 未被改写
      expect(readFileSync(src, 'utf-8')).not.toContain('fullscreen cover variants')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('标记不在 → 原样写回（按原样镜像，不报错）', () => {
    const d = makeTmp()
    try {
      const src = join(d, 'poster_src.html')
      const out = join(d, 'cover_src.html')
      const body = '<html><body>nothing to inject</body></html>'
      writeFileSync(src, body, 'utf-8')
      expect(poster.make_covers.main([src, out])).toBe(0)
      expect(readFileSync(out, 'utf-8')).toBe(body)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })
})

// ============ fit_diag ============

describe('fit_diag：?verify=1 诊断解析', () => {
  const wrap = (json: string): string => `<pre id="d">DIAG ${json}</pre>`

  it('全绿：无溢出、字体全载 → 退出码 0 + OK', () => {
    const d = makeTmp()
    try {
      const f = join(d, 'diag.txt')
      writeFileSync(f, wrap('{"fonts":"A loaded,B loaded","cells":[{"lang":"ko","fs":12.3,"word":"차","overflowX":false,"overflowY":false}]}'), 'utf-8')
      const { log } = captureLog()
      expect(poster.fit_diag.main([f])).toBe(0)
      const out = log.join('\n')
      expect(out).toContain('fs=  12.3')
      expect(out).toContain('fit diag: OK')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('溢出 → OVERFLOW 旗标 + 退出码 1；字体未载 → UNLOADED FONT + 退出码 1', () => {
    const d = makeTmp()
    try {
      const f = join(d, 'diag.txt')
      writeFileSync(f, wrap('{"fonts":"A queued,B loaded","cells":[{"lang":"ko","fs":12.3,"word":"차","overflowX":true,"overflowY":false}]}'), 'utf-8')
      const { log } = captureLog()
      expect(poster.fit_diag.main([f])).toBe(1)
      const out = log.join('\n')
      expect(out).toContain('<-- OVERFLOW-X')
      expect(out).not.toContain('<-- OVERFLOW-Y')
      expect(out).toContain('UNLOADED FONT: A queued')
      expect(out).toContain('PROBLEMS')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('无 DIAG 块 → 提示 + 退出码 1', () => {
    const d = makeTmp()
    try {
      const f = join(d, 'diag.txt')
      writeFileSync(f, '<html>no diag here</html>', 'utf-8')
      const { log } = captureLog()
      expect(poster.fit_diag.main([f])).toBe(1)
      expect(log.join('\n')).toContain('no DIAG block found')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })
})

// ============ audit_charset：字符子集门（verify_skill_scripts.py §4 移植） ============

// 合成叠印源：.lay/.top/.c/.sp 全是「带 class 但无映射族」的标签，
// 逐字母大词文本只活在这里——扁平重置的盲区本体（a01/a02 实锤）
const OVERLAY_SRC = '<html><body>\n'
  + '<div class="cell f-deva"><span class="stack f-deva">'
  + '<span class="lay v" aria-hidden="true">बात</span>'
  + '<span class="top"><span class="c">ब</span><span class="sp"></span>'
  + '<span class="c">त</span></span></span></div>\n'
  + '<div class="cell">Ω</div>\n'
  + '</body></html>\n'

describe('audit_charset 字符子集门（verify_skill_scripts.py §4 移植）', () => {
  function writeFixture(d: string, subset: string): [string, string] {
    const src = join(d, 'poster_src.html')
    const spec = join(d, 'fonts.json')
    writeFileSync(src, OVERLAY_SRC, 'utf-8')
    writeFileSync(spec, JSON.stringify([
      { family: 'OBS Deva', google: 'Noto+Sans+Devanagari:wght@500', text: subset, classes: ['f-deva'] },
    ]), 'utf-8')
    return [src, spec]
  }

  it('好数据放行：叠印层逐字母文本进扫描面且全覆盖', () => {
    const d = makeTmp()
    try {
      const [src, spec] = writeFixture(d, 'बात')
      const [missing, counts] = check(src, spec)
      expect(missing).toEqual([])
      // ब/ा/त 三个去重字符都检过（叠印 .lay 全词 + .top 逐字母同一批）
      expect(counts['OBS Deva']).toBe(3)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('凿洞：只出现在叠印层的码位（ा）删出子集 → 必须当场 MISSING', () => {
    const d = makeTmp()
    try {
      const [src, spec] = writeFixture(d, 'बत')
      const [missing] = check(src, spec)
      const hit = missing.find((m) => m.ch === 'ा')
      expect(hit).toBeDefined()
      expect(hit!.fam).toBe('OBS Deva')
      expect(hit!.code).toBe('0x93e')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('弹栈纪律：族外文本（Ω）不进任何族', () => {
    const d = makeTmp()
    try {
      const [src, spec] = writeFixture(d, 'बत')
      const [missing] = check(src, spec)
      expect(missing.some((m) => m.ch === 'Ω')).toBe(false)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('main：MISSING 全报后退出码 1', () => {
    const d = makeTmp()
    try {
      const [src, spec] = writeFixture(d, 'बत')
      const { log } = captureLog()
      expect(poster.audit_charset.main([src, spec])).toBe(1)
      expect(log.join('\n')).toContain('MISSING from subsets:')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })
})

describe('audit_charset 垫片规则绑定门（A-03 机器形态）', () => {
  function run(body: string, style = ''): string[] {
    const d = makeTmp()
    try {
      const f = join(d, 'poster_src.html')
      writeFileSync(f, `<html><head>${style ? `<style>${style}</style>` : ''}</head><body>${body}</body></html>`, 'utf-8')
      return checkPatchBindings(f)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  }

  it('好数据放行：class 码位 == 字形码位 + 规则存在', () => {
    expect(run('<span class="ksyl kCC28">차</span>', '.kCC28 { background: none; }')).toEqual([])
  })

  it('凿洞：穿错码位（.kB9CC = 만 的几何贴在 많 字形上）必须被抓', () => {
    const got = run('<span class="ksyl kB9CC">차</span>', '.kB9CC { background: none; }')
    expect(got).toHaveLength(1)
    expect(got[0]).toContain("wearing another glyph's patches")
    expect(got[0]).toContain('U+CC28')
    expect(got[0]).toContain('not U+B9CC')
  })

  it('凿洞：规则缺失（贴了 class 但 CSS 里没有这条规则）', () => {
    const got = run('<span class="ksyl kCC28">차</span>')
    expect(got).toHaveLength(1)
    expect(got[0]).toBe('kCC28: no CSS rule .kCC28 defined in the poster')
  })

  it('凿洞：孤儿规则（规则定义了但没有字形穿它）', () => {
    const got = run('<span>차</span>', '.kCC28, .other { background: none; }')
    expect(got).toEqual(['orphan rule .kCC28 is defined but worn by no glyph'])
  })

  it('凿洞：多字形 span（expected ONE glyph）', () => {
    const got = run('<span class="ksyl kCC28">차바</span>', '.kCC28 { background: none; }')
    expect(got).toHaveLength(1)
    expect(got[0]).toContain('expected ONE glyph, found 2')
  })

  it('void / 自闭合标签永不压栈（否则后续文本会被误归/漏归）', () => {
    // img（void）与 br/（自闭合）都不得 push——push 了的话 '차' 后面的
    // openCls 栈顶会是空列表，字形漏检 → 孤儿规则误报
    const got = run(
      '<span class="ksyl kCC28"><img src="x"><br/>차</span>',
      '.kCC28 { background: none; }',
    )
    expect(got).toEqual([])
  })
})

describe('audit_charset unescapeHtml（html.unescape 口径）', () => {
  it('数字引用（十进制/十六进制、可无分号）+ 常用具名实体；未知具名原样保留', () => {
    expect(unescapeHtml('&#48;&#x41;A')).toBe('0AA')
    expect(unescapeHtml('&#48')).toBe('0') // 无分号数字引用同样解（Python 口径）
    expect(unescapeHtml('&nbsp;&amp;&copy;')).toBe('\u00a0&\u00a9')
    expect(unescapeHtml('&zzz;')).toBe('&zzz;') // 名录外原样（Python 同）
  })
})

// ============ verify_colors ============

/** 合成 3×4 网格海报（300×400）：d9cdb7 网格线 + 每格红/蓝/灰/墨四色块。
 * missingBlueCell：指定格（如 'c0r0'）挖掉蓝块 → 触发 NO blue pixels。 */
function gridSvg(missingBlueCell?: string): string {
  const LINE = '#d9cdb7'
  const p: string[] = [`<rect width="300" height="400" fill="#ffffff"/>`]
  for (const x of [0, 100, 200, 299]) p.push(`<rect x="${x}" y="0" width="1" height="400" fill="${LINE}"/>`)
  for (const y of [0, 100, 200, 300, 399]) p.push(`<rect x="0" y="${y}" width="300" height="1" fill="${LINE}"/>`)
  const x0s = [3, 103, 203]
  const y0s = [3, 103, 203, 303]
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < 3; c++) {
      let dx = 10
      for (const fill of ['#c9403a', '#2f5d9e', '#a2967f', '#2c2620']) {
        if (missingBlueCell === `c${c}r${r}` && fill === '#2f5d9e') {
          dx += 14
          continue
        }
        p.push(`<rect x="${x0s[c]! + dx}" y="${y0s[r]! + 10}" width="10" height="10" fill="${fill}"/>`)
        dx += 14
      }
    }
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400">${p.join('')}</svg>`
}

describe('verify_colors：网格探测 + 逐格四色统计', () => {
  it('合成网格全绿：all cells OK', async () => {
    const d = makeTmp()
    try {
      const png = join(d, 'poster.png')
      await svgPng(png, gridSvg())
      const { log } = captureLog()
      expect(await poster.verify_colors.main([png])).toBe(0)
      const out = log.join('\n')
      expect(out).toContain('vertical lines: [0.0, 100.0, 200.0, 299.0]')
      expect(out).toContain('all cells OK')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('凿洞：某格没有蓝 → PROBLEMS + 退出码 1；--allow-missing blue 放行', async () => {
    const d = makeTmp()
    try {
      const png = join(d, 'poster.png')
      await svgPng(png, gridSvg('c0r0'))
      const { log } = captureLog()
      expect(await poster.verify_colors.main([png])).toBe(1)
      expect(log.join('\n')).toContain('cell1: NO blue pixels')

      const { log: log2 } = captureLog()
      expect(await poster.verify_colors.main([png, '--allow-missing', 'blue'])).toBe(0)
      expect(log2.join('\n')).toContain('all cells OK')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('网格缺失 → 响亮失败（Python assert 镜像）', async () => {
    const d = makeTmp()
    try {
      const png = join(d, 'blank.png')
      await svgPng(png, '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400"><rect width="300" height="400" fill="#ffffff"/></svg>')
      await expect(poster.verify_colors.main([png])).rejects.toThrow(FeuilleError)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })
})

// ============ check_overlay ============

describe('check_overlay：层间配准', () => {
  it('对齐（同位置红/蓝墨）→ best shift (0,0) + PASS', async () => {
    const d = makeTmp()
    try {
      const lay = join(d, 'lay.png')
      const top = join(d, 'top.png')
      // 墨块必须紧凑（不能是整列）：np.roll 环绕移位 + 平手取更小 dx/dy 的
      // 决胜规则下，整列墨块的竖直位移是简并的——dy 会平手落到 -radius。
      // 紧凑 6×6 块让 (0,0) 成为唯一零未匹配位移。
      await svgPng(lay, '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        + '<rect width="20" height="20" fill="#ffffff"/><rect x="7" y="7" width="6" height="6" fill="#c9403a"/></svg>')
      await svgPng(top, '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        + '<rect width="20" height="20" fill="#ffffff"/><rect x="7" y="7" width="6" height="6" fill="#2f5d9e"/></svg>')
      const { log } = captureLog()
      const rc = await poster.check_overlay.main([lay, top, '0', '0', '20', '20', '--scale', '1'])
      expect(rc).toBe(0)
      const out = log.join('\n')
      expect(out).toContain('best shift dx=0 dy=0')
      expect(out).toContain('PASS')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('凿洞：top 层右移 2px → 最优位移非零 → FAIL', async () => {
    const d = makeTmp()
    try {
      const lay = join(d, 'lay.png')
      const top = join(d, 'top.png')
      await svgPng(lay, '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        + '<rect width="20" height="20" fill="#ffffff"/><rect x="7" y="7" width="6" height="6" fill="#c9403a"/></svg>')
      await svgPng(top, '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        + '<rect width="20" height="20" fill="#ffffff"/><rect x="9" y="7" width="6" height="6" fill="#2f5d9e"/></svg>')
      const { log } = captureLog()
      const rc = await poster.check_overlay.main([lay, top, '0', '0', '20', '20', '--scale', '1'])
      expect(rc).toBe(1)
      const out = log.join('\n')
      expect(out).toContain('best shift dx=-2 dy=0')
      expect(out).toContain('FAIL — layers misregistered')
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('缺位置参数 → usage + 退出码 2', async () => {
    const { log } = captureLog()
    expect(await poster.check_overlay.main(['a.png', 'b.png', '0', '0', '20'])).toBe(2)
    expect(log.join('\n')).toContain('usage: feuille poster check-overlay')
  })
})

// ============ render e2e（Edge/Chrome headless——免费本机渲字，零额度） ============

// AGENTS.md 铁律的反向验证：headless 渲染**一律不带 --user-data-dir**。
// 实测 macOS + Edge 上带它时图能出但进程永不退出，整个 build 挂死（不带它
// 1.7s 退出）。render_poster 曾是五个渲染口里唯一的例外——这里把它钉死，
// 任何一侧（判据与被测不同源：判据是 AGENTS.md 纪律，被测是源码字面量）。
describe('headless 渲染旗标纪律（反向验证）', () => {
  const RENDER_SOURCES = [
    ['poster/render_poster', 'packages/poster/src/render_poster.ts'],
    ['poster/render_page', 'packages/poster/src/render_page.ts'],
    ['poster/measure_korean', 'packages/poster/src/measure_korean.ts'],
    ['core/textlayer', 'packages/core/src/textlayer.ts'],
    ['karaoke/build_video', 'packages/karaoke/src/build_video.ts'],
    ['storyteller/render_act_frames', 'packages/storyteller/src/render_act_frames.ts'],
  ] as const

  for (const [name, rel] of RENDER_SOURCES) {
    it(`${name}：启动参数里没有 --user-data-dir`, () => {
      const src = readFileSync(join(USINE, rel), 'utf-8')
      // 只看真正 spawn 浏览器的参数构造：注释里复述这条纪律不算违规
      const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
      expect(code).not.toContain('--user-data-dir')
    })
  }

  it('render_poster：timeout 由 spawnSync 自己兜，不依赖 GNU coreutils', () => {
    const src = readFileSync(
      join(USINE, 'packages/poster/src/render_poster.ts'), 'utf-8')
    // 外部 `timeout` 命令只在装了 coreutils 的机器上有；挂死兜底不能挂在它上面
    expect(src).toContain('timeout:')
    expect(src).not.toContain("spawnSync('timeout'")
  })
})

describe('render_poster 浏览器解析契约', () => {
  it('CHROME_BIN 解析不到 → 显式报缺，不静默换浏览器', () => {
    const old = process.env['CHROME_BIN']
    // FEUILLE_BROWSER 在本用例里必须缺席（CHROME_BIN 才是被测来源），但
    // edge project 是 singleFork：所有文件共用一个 worker 进程，恢复时
    // 必须还原原值——无条件 delete 会把调用方注入的 FEUILLE_BROWSER
    // （如 RSI guest 的无浏览器哨兵）连带抹掉，毒化同 worker 里之后
    // 跑的每个浏览器门控用例。
    const oldFb = process.env['FEUILLE_BROWSER']
    delete process.env['FEUILLE_BROWSER']
    process.env['CHROME_BIN'] = '/definitely/not/a/browser'
    const errs: string[] = []
    const realErr = console.error
    console.error = (...a: unknown[]) => { errs.push(a.join(' ')) }
    try {
      expect(poster.render_poster.main(['x.html', 'out.png'])).toBe(1)
    } finally {
      console.error = realErr
      if (old === undefined) delete process.env['CHROME_BIN']
      else process.env['CHROME_BIN'] = old
      if (oldFb === undefined) delete process.env['FEUILLE_BROWSER']
      else process.env['FEUILLE_BROWSER'] = oldFb
    }
    // 错误信息必须点名那个坏值，否则用户无从判断是哪个来源配错了
    expect(errs.join('\n')).toContain('/definitely/not/a/browser')
  })
})

describe('render e2e', () => {
  const d = makeTmp()
  afterAll(() => rmSync(d, { recursive: true, force: true }))

  it(HAS_BROWSER
    ? 'render_poster：query 后缀透传到浏览器（?fmt=P 真被 JS 读到）+ 出图尺寸 = W×S'
    : '跳过：本机无 Chromium 系浏览器', { timeout: 180_000 }, async () => {
    if (!HAS_BROWSER) return
    const src = join(d, 'tiny.html')
    const out = join(d, 'tiny.png')
    writeFileSync(src,
      '<!DOCTYPE html><html><head><style>body{margin:0}</style></head><body>'
      + '<script>document.body.style.background = location.search.includes("fmt=P") ? "#00ff00" : "#ff0000"</script>'
      + '</body></html>', 'utf-8')
    expect(poster.render_poster.main([`${src}?fmt=P`, out, '100', '100', '1'])).toBe(0)
    expect(existsSync(out)).toBe(true)
    const meta = await sharp(out).metadata()
    expect(meta.width).toBe(100)
    expect(meta.height).toBe(100)
    // query 真的到了页面：?fmt=P → 绿底（少了 ?fmt=P 会静默渲成横版红底）
    const px = await sharp(out).extract({ left: 50, top: 50, width: 1, height: 1 }).raw().toBuffer()
    expect(px[0]).toBeLessThan(100) // R
    expect(px[1]).toBeGreaterThan(200) // G
  })

  it(HAS_BROWSER
    ? 'render_page dump：--dump-dom 吐渲染后 DOM'
    : '跳过：本机无 Chromium 系浏览器', { timeout: 180_000 }, async () => {
    if (!HAS_BROWSER) return
    const src = join(d, 'dom.html')
    const out = join(d, 'dom.txt')
    writeFileSync(src, '<!DOCTYPE html><html><body><div id="a">HELLO-DOM</div></body></html>', 'utf-8')
    expect(await poster.render_page.main(['dump', src, out, '200', '200'])).toBe(0)
    expect(readFileSync(out, 'utf-8')).toContain('HELLO-DOM')
  })

  it(HAS_BROWSER
    ? 'render_page render：窗框开销 (24,93) 补偿后裁回 w×h×scale 精确尺寸'
    : '跳过：本机无 Chromium 系浏览器', { timeout: 180_000 }, async () => {
    if (!HAS_BROWSER) return
    const src = join(d, 'page.html')
    const out = join(d, 'page.png')
    writeFileSync(src, '<!DOCTYPE html><html><head><style>body{margin:0;background:#ffffff}</style></head><body>x</body></html>', 'utf-8')
    expect(await poster.render_page.main(['render', src, '-', out, '100', '100', '1'])).toBe(0)
    const meta = await sharp(out).metadata()
    expect(meta.width).toBe(100)
    expect(meta.height).toBe(100)
  })

  it('render_page render：缺 query 参数 → 响亮失败（无 query 须传 "-"）', async () => {
    await expect(poster.render_page.main(['render', 'x.html'])).rejects.toThrow(FeuilleError)
  })
})

// ============ barrel ============

describe('barrel：十脚本归流一包', () => {
  it('index 导出 10 个命名空间（one-page-poster/scripts 全量）', () => {
    expect(Object.keys(poster).sort()).toEqual([
      'assemble', 'audit_charset', 'check_overlay', 'fetch_fonts', 'fit_diag',
      'make_covers', 'measure_korean', 'render_page', 'render_poster', 'verify_colors',
    ])
  })
})
