// video_style_pins.test.ts — D1–D5 的**构造期证据**（不需要浏览器、不需要成片）
//
// 为什么要有这条测试：D2–D5 是**版式判据**（主角墨迹 ≥12% 帧高 / 空白带 ≤15% /
// 暗词不透明度 ≥0.45 / 高亮属品牌三色）。成片门 check_video_layout.mjs 要 frames
// 与浏览器，本机两样都没有。能在这里钉住的是**产物与样式的构造事实**：
//   ① D1 —— 真实构建器产出的每个语种，.sentence 里的 top-level .tok 序列必须与
//      数据里的 tokens **同数、同序、同字**（独立解析产物，不信构建器的自检）。
//   ② D2 —— 词形是**自己一个元素**（.hero），且拟合框按最保守墨迹系数换算后
//      仍 ≥ 12% 帧高（或 ≥30% 帧宽）。
//   ③ D3 —— 竖屏整栏 justify-content: space-between，所有竖屏声明的单段间距
//      ≤ 15% 帧高；最保守内容高代入后算出的最大间隙也 ≤ 288px。
//   ④ D4 —— .tok.dim 的 opacity ≥ 0.45。
//   ⑤ D5 —— .cur 的底色落在品牌三色（c9403a / 2f5d9e / b8860b）里，中性灰不许回来。
import { describe, expect, test } from 'vitest'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const FN = resolve(HERE, '..')
const USINE = resolve(FN, '..', '..')
const TMPL = join(FN, 'templates')
const CSS = readFileSync(join(TMPL, 'video_style.css'), 'utf8')
const SCRIPT = readFileSync(join(TMPL, 'video_script.js'), 'utf8')

const PORTRAIT = { w: 1080, h: 1920 } // ?fmt=v，发布平台吃的那一版
const BRAND = ['c9403a', '2f5d9e', 'b8860b'] // 页脚图例承诺的三色（= layout_rules.BRAND）

/** 取一条 CSS 规则的声明块（选择器按字面匹配；只转义点号，够用）。 */
function decl(css: string, selector: string): string {
  const esc = selector.split('.').join('\\.')
  const re = new RegExp('(?:^|[}\n])\\s*' + esc + '\\s*\\{([^}]*)\\}')
  const m = re.exec(css)
  if (!m) throw new Error('CSS 里找不到规则：' + selector)
  return m[1] ?? ''
}

/** 像素值（'52px' → 52；没有 px 单位 → null）。 */
function px(v: string | undefined): number | null {
  const m = /(-?[\d.]+)px/.exec(v ?? '')
  return m ? Number(m[1]) : null
}

/** rgba()/rgb() 的十六进制（与 check_video_layout.mjs 的 isBrand() 同口径）。 */
function hexOf(css: string): string | null {
  const m = /rgba?\(([^)]*)\)/.exec(css)
  if (!m) return null
  const nums = (m[1] ?? '').split(',').map((s) => Number(s.trim()))
  if (nums.length < 3 || nums.some((n) => !Number.isFinite(n))) return null
  return nums
    .slice(0, 3)
    .map((n) => Math.round(n).toString(16).padStart(2, '0'))
    .join('')
}

const ENT: [RegExp, string][] = [
  [/&amp;/g, '&'],
  [/&quot;/g, '"'],
  [/&lt;/g, '<'],
  [/&gt;/g, '>'],
]
const unent = (s: string): string => ENT.reduce((acc, [re, r]) => acc.replace(re, r), s)

/** 与两道视频门同口径的可见文字；同时把 top-level .tok 切成数组（顺序 = 出现顺序）。
 *  跳过 .annot 与 .stack > .top（叠印上层不是词形本身）。 */
function toksOf(inner: string): string[] {
  const stack: { cls: string[]; skip: boolean }[] = []
  const out: string[] = []
  let cur: string | null = null
  for (const t of inner.match(/<[^>]+>|[^<]+/g) ?? []) {
    if (t.startsWith('</')) {
      stack.pop()
      if (cur !== null && stack.length === 0) {
        out.push(unent(cur))
        cur = null
      }
      continue
    }
    if (t.startsWith('<')) {
      const cls = ((t.match(/class="([^"]*)"/) ?? [, ''])[1] ?? '').split(/\s+/).filter(Boolean)
      const skip =
        cls.includes('annot') || (stack.some((s) => s.cls.includes('stack')) && cls.includes('top'))
      if (cls.includes('tok') && stack.length === 0) cur = ''
      stack.push({ cls, skip })
      continue
    }
    if (stack.some((s) => s.skip)) continue
    if (cur !== null) cur += t
  }
  return out
}

/** 词序/词形比对口径：去空白 + 去标点（卡拉OK token 合法地丢标点，见 README）。 */
const strip = (s: string): string => s.replace(/[\s\p{P}]/gu, '')
/** 折叠：忽略大小写与变音符号（词形定位口径）。 */
const fold = (s: string): string =>
  s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().replace(/\s+/g, '')

function build(ep: string): { dir: string; html: string; data: any } {
  const dataPath = join(FN, 'data', ep + '.json')
  const dir = mkdtempSync(join(tmpdir(), 'foodnames-pin-'))
  const r = spawnSync(
    process.execPath,
    ['--import', 'tsx', join(FN, 'build_episode.mjs'), '--data', dataPath, '--out', dir],
    { cwd: USINE, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 },
  )
  expect(r.status, 'build_episode 失败：\n' + (r.stderr || r.stdout || '').slice(-1500)).toBe(0)
  const html = readFileSync(join(dir, 'video_src.html'), 'utf8')
  const data = JSON.parse(readFileSync(dataPath, 'utf8'))
  return { dir, html, data }
}

/** 切出一格 .scene 的 HTML。 */
function sceneOf(html: string, locale: string): string {
  const at = html.indexOf('data-lang="' + locale + '"')
  expect(at, '画面里没有 ' + locale + ' 这一格').toBeGreaterThanOrEqual(0)
  const open = html.lastIndexOf('<section', at)
  const end = html.indexOf('</section>', at)
  return html.slice(open, end)
}

/** 从一格 .scene 里取 .sentence 的 inner HTML。 */
function sentenceInner(sc: string): string {
  const m = /<div class="sentence"[^>]*>([\s\S]*?)<\/div><\/div>/.exec(sc)
  expect(m, '找不到 .sentence').not.toBeNull()
  return m![1] ?? ''
}

describe('D1：画面 token 序列 == 数据里的 tokens（同数、同序、同字）', () => {
  for (const ep of ['ep01-sushi', 'ep06-curry']) {
    test(
      ep,
      () => {
        const { dir, html, data } = build(ep)
        try {
          for (const w of data.words) {
            const got = toksOf(sentenceInner(sceneOf(html, w.locale)))
            const want: string[] = w.tokens
            expect(
              got.length,
              w.locale + '：token 数变了\n  画面=' + got.join(' | ') + '\n  数据=' + want.join(' | '),
            ).toBe(want.length)
            for (let i = 0; i < want.length; i++) {
              expect(
                strip(got[i] ?? ''),
                w.locale + '：第 ' + (i + 1) + ' 个 token 变了『' + (got[i] ?? '') + '』（数据：' +
                  (want[i] ?? '') + '）\n  整句=' + got.join(' '),
              ).toBe(strip(want[i] ?? ''))
            }
          }
        } finally {
          rmSync(dir, { recursive: true, force: true })
        }
      },
      120_000,
    )
  }
})

describe('D2：词形独立成元素，拟合框保证墨迹够大', () => {
  // video_script.js 的拟合框（CSS px）：竖屏 800×700
  const w = /const STAGE_W = vert \? (\d+) : (\d+)/.exec(SCRIPT)
  const h = /const STAGE_H = vert \? (\d+) : (\d+)/.exec(SCRIPT)
  const stw = Number(w?.[1] ?? NaN)
  const sth = Number(h?.[1] ?? NaN)

  test('拟合框尺寸可读出（竖屏 800×700）', () => {
    expect([stw, sth]).toEqual([800, 700])
  })

  test('墨迹高 ≥ 12% 帧高（保守墨迹系数 0.70em）', () => {
    // 拟合把 .hero 的盒子压到 box 高以内；line-height 1.08 → 字号 ≈ boxH/1.08。
    // 字形墨迹按最保守的 0.70em 估（本仓实测各语种 0.70–0.79em）。
    const fs = sth / 1.08
    const inkH = fs * 0.7
    const need = 0.12 * PORTRAIT.h
    console.log(
      'D2 竖屏：字号上限 ≈ ' + fs.toFixed(0) + 'px → 墨迹 ≈ ' + inkH.toFixed(0) +
        'px，需要 ≥ ' + need.toFixed(0) + 'px（' + PORTRAIT.h + 'px 帧高）',
    )
    expect(inkH).toBeGreaterThanOrEqual(need)
  })

  test('拟合框宽 ≥ 30% 帧宽（宽度受限的长词也过）', () => {
    const need = 0.3 * PORTRAIT.w
    console.log('D2 竖屏：拟合框宽 ' + stw + 'px，可用墨迹宽 ≈ ' + (stw * 0.9).toFixed(0) + 'px，需要 ≥ ' + need.toFixed(0) + 'px')
    expect(stw * 0.9).toBeGreaterThanOrEqual(need)
  })

  test(
    '构建产物每格都有独立的 .hero，且文字就是词形',
    () => {
      const { dir, html, data } = build('ep01-sushi')
      try {
        for (const w of data.words) {
          const sc = sceneOf(html, w.locale)
          const heroIdx = sc.search(/<div class="hero word[^"]*"[^>]*>/)
          expect(heroIdx, w.locale + '：没有独立的 .hero 元素').toBeGreaterThanOrEqual(0)
          const stageIdx = sc.search(/<div class="stage">/)
          expect(heroIdx, w.locale + '：.hero 必须在句子的 .stage 之外').toBeLessThan(stageIdx)
          const hero = /<div class="hero word[^"]*"[^>]*>([\s\S]*?)<\/div>\s*<div class="stage">/.exec(sc)
          expect(hero, w.locale + '：读不出 .hero 的内容').not.toBeNull()
          const text = toksOf('<span class="tok">' + (hero![1] ?? '') + '</span>')[0] ?? ''
          const forms = [w.word, w.inline ?? w.word].map(fold)
          expect(forms, w.locale + '：.hero 里是『' + text + '』，不是词形').toContain(fold(text))
        }
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    },
    120_000,
  )
})

describe('D3：竖屏空白带 ≤ 15% 帧高（由构造算出，不靠渲染）', () => {
  const LIMIT = 0.15 * PORTRAIT.h // 288px

  test('整栏用 space-between 均摊余量', () => {
    expect(decl(CSS, 'body.vert .scene')).toMatch(/justify-content:\s*space-between/)
  })

  test('没有任何单段间距超过 15% 帧高', () => {
    const pad = /padding:\s*([^;]+);/.exec(decl(CSS, 'body.vert .scene'))
    expect(pad, 'body.vert .scene 没有 padding 声明').not.toBeNull()
    const vals = (pad![1] ?? '').trim().split(/\s+/).map(px)
    console.log('D3 竖屏内边距：' + vals.map((v) => v + 'px').join(' / ') + '（单段上限 ' + LIMIT + 'px）')
    for (const v of vals) {
      expect(v, '内边距超出最大空白带').not.toBeNull()
      expect(v!).toBeLessThanOrEqual(LIMIT)
    }
    for (const rule of CSS.matchAll(/body\.vert[^{]*\{([^}]*)\}/g)) {
      for (const m of (rule[1] ?? '').matchAll(/margin(?:-top|-bottom)?:\s*([^;]+);/g)) {
        for (const raw of (m[1] ?? '').trim().split(/\s+/)) {
          const v = px(raw)
          if (v === null) continue
          expect(v, '竖屏边距 ' + raw + ' 超出最大空白带').toBeLessThanOrEqual(LIMIT)
        }
      }
    }
  })

  test('最保守内容高代入 space-between，最大间隙仍 ≤ 288px', () => {
    const rows: [string, string][] = [
      ['brand', 'body.vert .brand'],
      ['langlabel', 'body.vert .langlabel'],
      ['natv', 'body.vert .natv'],
      ['tag', 'body.vert .tag'],
      ['sentence', 'body.vert .sentence'],
      ['badge', 'body.vert .badge'],
      ['translit', 'body.vert .translit'],
      ['footer', 'body.vert .footer'],
    ]
    let sum = 0
    for (const [name, sel] of rows) {
      const m = /font-size:\s*([\d.]+)px/.exec(decl(CSS, sel))
      expect(m, sel + ' 没有 font-size').not.toBeNull()
      const hgt = Number(m![1]) * 1.2
      sum += hgt
      console.log('  ' + name.padEnd(10) + ' ' + m![1].padStart(4) + 'px → 行盒 ' + hgt.toFixed(0) + 'px')
    }
    const rules = 2.5 + 1.5 // headrule + footrule
    const heroMin = 120 // 宽度受限的极长词：拟合框 800px 宽时的最小高度下界
    const pad = /padding:\s*([^;]+);/.exec(decl(CSS, 'body.vert .scene'))!
    const pv = (pad[1] ?? '').trim().split(/\s+/).map(px)
    const padSum = (pv[0] ?? 0) + (pv[pv.length - 1] ?? 0)
    const content = sum + rules + heroMin
    const free = PORTRAIT.h - padSum - content
    const gaps = 8 // 9 个子块之间的间隙数
    const gap = free / gaps
    console.log(
      'D3 竖屏：内容高 ' + content.toFixed(0) + 'px + 上下内边距 ' + padSum.toFixed(0) +
        'px → 余量 ' + free.toFixed(0) + 'px 分到 ' + gaps + ' 段 = 最大间隙 ' + gap.toFixed(0) + 'px',
    )
    expect(gap).toBeLessThanOrEqual(LIMIT)
    expect(free).toBeGreaterThanOrEqual(0) // 余量非负：内容本身撑不满时才谈空带
  })
})

describe('D4：没唱到的 token 看得见（opacity ≥ 0.45）', () => {
  test('.tok.dim opacity ≥ 0.45', () => {
    const m = /opacity:\s*([\d.]+)/.exec(decl(CSS, '.tok.dim'))
    expect(m, '.tok.dim 没有 opacity').not.toBeNull()
    const v = Number(m![1])
    console.log('D4：.tok.dim opacity = ' + v + '（旧值 0.18，阈值 ≥ 0.45）')
    expect(v).toBeGreaterThanOrEqual(0.45)
  })
})

describe('D5：当前 token 的高亮落在品牌三色里', () => {
  for (const kind of ['kv', 'kc', 'kt']) {
    test('.tok.cur.' + kind + ' 用品牌色', () => {
      const bg = /background(?:-color)?:\s*([^;]+);/.exec(decl(CSS, '.tok.cur.' + kind))
      expect(bg, '.tok.cur.' + kind + ' 没有 background').not.toBeNull()
      const hex = hexOf(bg![1] ?? '')
      console.log('D5：.tok.cur.' + kind + ' → ' + (bg![1] ?? '').trim() + ' = #' + hex)
      expect(BRAND).toContain(hex)
    })
  }

  test('中性灰 rgba(44,38,32,…) 不许回来', () => {
    expect(CSS).not.toMatch(/rgba\(\s*44\s*,\s*38\s*,\s*32/)
  })

  test('品牌三色的十六进制也出现在样式表里（与页脚图例同源）', () => {
    for (const hex of BRAND) expect(CSS.toLowerCase()).toContain(hex)
  })
})
