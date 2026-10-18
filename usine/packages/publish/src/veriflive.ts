// veriflive.ts — 发布后核对（⑪）：管理页 → 按标题搜索 → 逐条截图 → 拼对照图
// （publish/veriflive.py 的 TS 移植）。
//
// 全部只读，不做任何修改。最终判定 = 人眼看缩略图里有文字（纪律 5：
// 发布成功的唯一权威判据 = 回列表核验到这条作品）。本模块只产证据
// （逐条截图 + full-page 截图 + 对照图），不判 ok/fail——程序打 ✓ 不算数。
//
// 对照图用 `@feuille/core` 的 covers.sheet 拼，不用 magick montage，少一个外部件。
//
// 合集核对是双通道互证：① 合集卡片的「N 个作品」计数；② 进编辑页滚遍
// 列表抓到的逐条唯一标题清单。两通道都等于 want 才算齐——只看计数会被
// 「计数对但挂错条」骗，只看清单会被「重复挂同一条」骗。可再加交叉验证：
// 「只看可添加的作品」计数应为 0（否则还有漏挂）。
//
// 使用契约：page 由 base.launch 给出（resolver Chrome + 平台 profile）；
// 截图全部落 outDir；返回 dict 只是证据索引，结论由人眼下。
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { covers, FeuilleError } from '@feuille/core'

import * as base from './base.js'
import * as clock from './clock.js'

// 各平台核对入口（管理页 URL / 搜索框 / 行定位模板 / 视口）。
// rowText 的 {kw} 会被 keyword 替换：抖音行文本是「…」的前缀、B 站是【…】标题、
// 小红书没有搜索框（走滚动采集，正则按 keyword 匹配）。
export interface PlatformCfg {
  manage: string
  searchSel: string | null
  rowText: string | null
  viewport: { width: number; height: number }
}

export const PLATFORMS: Record<string, PlatformCfg> = {
  douyin: {
    manage: 'https://creator.douyin.com/creator-micro/content/manage',
    searchSel: "input[placeholder*='搜索']",
    rowText: '「{kw}」的',
    viewport: { width: 1700, height: 1100 },
  },
  bilibili: {
    manage: 'https://member.bilibili.com/platform/upload-manager/article',
    searchSel: "input[placeholder*='搜索'], input[placeholder*='标题']",
    rowText: '【{kw}',
    viewport: { width: 1600, height: 1000 },
  },
  xiaohongshu: {
    manage: 'https://creator.xiaohongshu.com/new/note-manager',
    searchSel: null, // 无搜索框：滚动采集（verify_xhs_all 实测）
    rowText: null,
    viewport: { width: 1600, height: 1000 },
  },
}

// 滚动采集（小红书）：抓含系列关键词的短文本行
// （Python 源里 `\\s` = 求值字符串中的 `\s`，TS 模板串同样要双写反斜杠。）
const JS_COLLECT = `(kw) => {
  const out=[];
  document.querySelectorAll('a,div[class*=note],div[class*=card],div[class*=item]')
    .forEach(e => {
      const t=(e.innerText||'').replace(/\\s+/g,' ').trim();
      if (t && t.includes(kw) && t.length < 80 && !out.includes(t)) out.push(t);
    });
  return out;
}`

// 找真正的滚动容器（小红书列表不在 window 上滚）
// （Python 源里同款：模块级常量，_scroll_rows 实测链路留档备用。）
export const JS_SCROLLER = `() => {
  const cands = [document.scrollingElement, document.body,
                 ...document.querySelectorAll('div[class*=scroll],div[class*=list],main')];
  let best = null, bestArea = 0;
  for (const c of cands) {
    if (!c) continue;
    const area = c.scrollHeight;
    if (area > bestArea) { bestArea = area; best = c; }
  }
  if (!best) return {moved:0, sh:0};
  const before = best.scrollTop;
  best.scrollTop = before + best.clientHeight * 0.85;
  return {moved: best.scrollTop - before, sh: best.scrollHeight, ch: best.clientHeight};
}`

// 合集编辑页：抓条目标题（「系列名」开头的短文本）
const JS_COLLECT_TITLES = `(kw) => [...document.querySelectorAll('*')]
  .map(e => (e.innerText||'').replace(/\\s+/g,' ').trim())
  .filter(t => t.startsWith('「'+kw+'」') && t.length < 200)`

/** Python re.escape 的 JS 对应物：把正则元字符转义，其余原样。 */
function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * douyin/bilibili 共用：搜索 → full-page 截图 → 逐条裁剪行截图（只读）。
 *
 * 返回已落盘的截图文件名列表（含整页 list-all.png 与逐条 row-XX.png）。
 */
async function searchRows(
  page: base.AnyPage,
  plat: string,
  keyword: string,
  outDir: string,
): Promise<string[]> {
  const cfg = PLATFORMS[plat]!
  await page.goto(cfg.manage, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await clock.sleep(plat === 'bilibili' ? 6 : 7)
  if (plat === 'bilibili') {
    for (const kw of ['知道了', '我知道了']) {
      try {
        const b = page.getByText(kw, { exact: true }).first()
        if (await base.visibleWithin(b, 900)) {
          await b.click()
          await clock.sleep(1)
        }
      } catch {
        // 没弹出来就跳过
      }
    }
  }

  // 搜系列关键词
  try {
    const box = page.locator(cfg.searchSel!).first()
    await box.click()
    await box.fill(keyword)
    await page.keyboard.press('Enter')
    await clock.sleep(5)
  } catch (e) {
    console.log(`搜索框不可用：${base.errName(e)}`)
  }

  // 整页一张，先看全貌
  await page.screenshot({ path: join(outDir, 'list-all.png'), fullPage: true })

  const titles = page.getByText(cfg.rowText!.replace('{kw}', keyword), { exact: false })
  const n = await titles.count()
  console.log(`命中 ${n} 条`)
  const vp = (await page.viewportSize()) ?? cfg.viewport
  const pngs = ['list-all.png']
  for (let i = 0; i < n; i++) {
    let t: string
    try {
      t = ((await titles.nth(i).innerText()) ?? '').trim()
    } catch {
      continue
    }
    await titles.nth(i).scrollIntoViewIfNeeded()
    await clock.sleep(plat === 'douyin' ? 0.8 : 0.7)
    const bb = await titles.nth(i).boundingBox()
    if (!bb) continue
    // 缩略图约 145px 高，封面文字在**底部**那 35px，
    // 所以裁剪窗必须比缩略图还高，否则正好把文字切掉（栽过）。
    const x0 = Math.max(0, bb['x'] - (plat === 'douyin' ? 130 : 150))
    const y0 = Math.max(0, Math.min(bb['y'] - 45, vp.height - (plat === 'douyin' ? 210 : 220)))
    const clipW = Math.min(plat === 'douyin' ? 760 : 800, vp.width - x0)
    const name = `row-${base.pad2(i)}.png`
    await page.screenshot({
      path: join(outDir, name),
      clip: {
        x: x0,
        y: y0,
        width: clipW,
        height: plat === 'douyin' ? 200 : 210,
      },
    })
    console.log(`  [${base.pad2(i)}] ${base.clip(t, 46)}`)
    pngs.push(name)
  }
  return pngs
}

/**
 * xiaohongshu：无搜索框，滚动穷举「已发布」列表（verify_xhs_all 实测链路）。
 * 返回 [found, pngs]。
 */
async function scrollRows(
  page: base.AnyPage,
  keyword: string,
  outDir: string,
): Promise<[string[], string[]]> {
  const cfg = PLATFORMS['xiaohongshu']!
  await page.goto(cfg.manage, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await clock.sleep(8)
  // 点「已发布」页签
  for (let i = 0; i < 4; i++) {
    try {
      const loc = page.getByText('已发布', { exact: true })
      if ((await loc.count()) && (await base.visibleWithin(loc.nth(i), 800))) {
        await loc.nth(i).click()
        console.log('  已点「已发布」')
        break
      }
    } catch {
      continue
    }
  }
  await clock.sleep(4)

  // 不做搜索过滤，直接看「已发布」页签的全量最新列表
  const found: string[] = []
  await page.mouse.move(800, 600) // 鼠标放到列表区域上，滚轮才作用在正确的容器
  let prevCount = -1
  for (let i = 0; i < 30; i++) {
    for (const t of (await page.evaluate(JS_COLLECT, keyword)) as string[]) {
      if (!found.includes(t)) found.push(t)
    }
    if (i % 3 === 0) console.log(`  轮${i + 1}: 累计 ${found.length} 条`)
    if (found.length === prevCount) break
    prevCount = found.length
    await page.mouse.wheel(0, 700)
    await clock.sleep(1.1)
  }
  console.log(`  最终采集 ${found.length} 条`)

  // 看看有没有分页
  const pag = await page.evaluate(`() => [...document.querySelectorAll('li,button,a,div')]
      .filter(e => { const t=(e.innerText||'').trim();
        return /^\\d+$/.test(t) && parseInt(t) <= 20
               && e.getBoundingClientRect().width < 80; })
      .map(e => (e.innerText||'').trim())`)
  console.log(`  疑似分页数字: ${base.pyList([...new Set(pag as string[])])}`)

  await page.mouse.move(800, 600)
  for (let _ = 0; _ < 12; _++) {
    await page.mouse.wheel(0, -900)
    await clock.sleep(0.35)
  }
  await clock.sleep(1.5)
  await page.screenshot({ path: join(outDir, 'list-all.png') })

  const titles: string[] = []
  const pat = new RegExp(`(${escapeRe(keyword)}[^0-9]{2,14}版)`)
  for (const t of found) {
    const m = pat.exec(t)
    const k = m ? m[1]! : base.clip(t, 24)
    if (!titles.includes(k)) titles.push(k)
  }
  console.log(`\n=== 共 ${titles.length} 个标题 ===`)
  titles.forEach((t, idx) => console.log(`  ${base.pad2(idx + 1)} ${t}`))
  writeFileSync(join(outDir, 'titles.json'), JSON.stringify(titles, null, 1))
  return [found, ['list-all.png']]
}

export interface VerifyResult {
  platform: string
  keyword: string
  rows: number
  shots: string[]
  sheet: string
  out_dir: string
}

/**
 * 发布后只读核对：进管理页 → 按标题搜索 → 逐条截图 → 拼对照图。
 *
 * 返回证据索引 dict（截图清单 / 对照图路径 / 命中数）。
 * **最终判定 = 人眼看对照图缩略图里有文字**——本函数不判 ok/fail。
 * keyword 默认值只是示例系列词；接入新项目必须传自己的。
 */
export async function verify(
  platform: string,
  page: base.AnyPage,
  outDir: string,
  opts: { keyword?: string } = {},
): Promise<VerifyResult> {
  const keyword = opts.keyword ?? '一叶知秋'
  if (!(platform in PLATFORMS)) {
    throw new FeuilleError(
      `未知平台 ${base.pyRepr(platform)}（合法：${base.pyList(Object.keys(PLATFORMS))}）`,
    )
  }
  mkdirSync(outDir, { recursive: true })

  let pngs: string[]
  let nRows: number
  if (platform === 'xiaohongshu') {
    const [found, p] = await scrollRows(page, keyword, outDir)
    pngs = p
    nRows = found.length
  } else {
    pngs = await searchRows(page, platform, keyword, outDir)
    nRows = pngs.length - 1 // 去掉 list-all
  }

  // 对照图（拼版，不用 magick）：人眼判定的载体
  const sheetPath = await covers.sheet(
    pngs.map((p) => join(outDir, p)),
    join(outDir, 'sheet.png'),
  )
  console.log(`\n对照图：${sheetPath}`)
  console.log('👉 最终判定：人眼看对照图——缩略图里有文字 = 预制封面生效；纯画面 = 没生效')
  return {
    platform,
    keyword,
    rows: nRows,
    shots: pngs,
    sheet: sheetPath,
    out_dir: outDir,
  }
}

// ---------------------------------------------------------------- 合集核对

export interface VerifyColResult {
  title: string
  want: number
  count: number
  items: string[]
  dup: string[]
  missing_lang: string[]
  addable_left: number | null
  both_channels_ok: boolean
}

/**
 * 合集只读核对：作品数 + 逐条清单**双通道互证**（+可选交叉验证）。
 *
 * - 通道一：合集卡片文本里的「N 个作品」计数；
 * - 通道二：进编辑页滚遍「合集内作品」列表抓到的唯一标题清单；
 * - 互证：两通道都要等于 want；expectLangs（{语种名: 标题内子串}）可再查语种覆盖；
 * - 交叉验证（crossCheck）：作品面板勾「只看可添加的作品」后本系列计数应为 0
 *   （还有漏没挂）。
 *
 * 只读，不点任何修改类按钮。返回证据 dict；结论仍以人眼看截图为准。
 */
export async function verifyCollection(
  page: base.AnyPage,
  outDir: string,
  opts: {
    title: string
    want: number
    keyword: string
    expectLangs?: Record<string, string> | null
    crossCheck?: boolean
  },
): Promise<VerifyColResult> {
  const { title, want, keyword } = opts
  const expectLangs = opts.expectLangs ?? null
  const crossCheck = opts.crossCheck ?? true
  mkdirSync(outDir, { recursive: true })
  const manage = 'https://creator.douyin.com/creator-micro/content/manage?tab=collections'

  const shot = async (n: string): Promise<void> => {
    try {
      await page.screenshot({ path: join(outDir, n) })
      console.log(`  📸 ${n}`)
    } catch {
      // 截图只是留证
    }
  }

  await page.goto(manage, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await clock.sleep(10)
  for (const kw of ['我知道了', '知道了', '以后再说']) {
    const loc = page.getByText(kw, { exact: true })
    const n = Math.min(await loc.count(), 3)
    for (let i = 0; i < n; i++) {
      try {
        if (await base.visibleWithin(loc.nth(i), 400)) {
          await loc.nth(i).click()
          await clock.sleep(0.8)
        }
      } catch {
        // 没弹出来就跳过
      }
    }
  }

  const cards = page.locator("[class*='collection-card-']")
  let card: any = null
  const cnt = await cards.count()
  for (let i = 0; i < cnt; i++) {
    const c = cards.nth(i)
    try {
      const txt = (await c.innerText({ timeout: 3000 })) ?? ''
      if (txt.includes(base.clip(title, 6))) {
        card = c
        break
      }
    } catch {
      continue
    }
  }
  if (card === null) {
    console.log('  ✗ 找不到合集卡片')
    throw new FeuilleError(`找不到合集「${title}」的卡片（只读核对中止，未点任何东西）`)
  }

  const txt = (await card.innerText()) ?? ''
  console.log('=== 卡片全文 ===')
  console.log(`  ${txt.replace(/\n/g, ' | ')}`)
  await shot('verify-col-card.png')

  const m = /(\d+)\s*个作品/.exec(txt)
  const n = m ? Number(m[1]) : -1
  console.log(`\n  作品数 = ${n}  ${n === want ? '✓' : `✗ 预期 ${want}`}`)

  // 通道二：进编辑页滚遍合集内作品列表
  console.log('\n▶ 进编辑页看逐条清单')
  await card.scrollIntoViewIfNeeded()
  await clock.sleep(0.8)
  await card.locator("[class*='new-layout-action-']").first().click()
  await clock.sleep(6)

  const seen: string[] = []
  for (let step = 0; step < 22; step++) {
    for (const t of (await page.evaluate(JS_COLLECT_TITLES, keyword)) as string[]) {
      if (!seen.includes(t)) seen.push(t)
    }
    await page.screenshot({ path: join(outDir, `scroll-list-${base.pad2(step)}.png`) })
    // 滚到底
    await page.evaluate(`() => {
      const b = [...document.querySelectorAll('div')]
        .find(e => e.scrollHeight > e.clientHeight + 40
                && e.clientHeight > 300 && /合集内作品/.test(e.innerText||''));
      if (b) b.scrollTop = b.scrollHeight;
      else window.scrollBy(0, 600);
    }`)
    await clock.sleep(1.1)
    const atEnd = await page.evaluate(`() => {
      const b = [...document.querySelectorAll('div')]
        .find(e => e.scrollHeight > e.clientHeight + 40
                && e.clientHeight > 300 && /合集内作品/.test(e.innerText||''));
      return b ? (b.scrollTop + b.clientHeight >= b.scrollHeight - 12) : true;
    }`)
    if (atEnd) {
      console.log(`  第 ${step + 1} 屏到底`)
      break
    }
  }
  for (const t of (await page.evaluate(JS_COLLECT_TITLES, keyword)) as string[]) {
    if (!seen.includes(t)) seen.push(t)
  }

  console.log(`\n=== 抓到 ${seen.length} 条唯一标题 ===`)
  seen.forEach((t, k) => console.log(`  ${String(k + 1).padStart(2)}. ${base.clip(t, 58)}`))

  // 查重（重复挂同一条会让计数对、清单错——双通道互证的意义就在这）
  const heads = seen.map((t) => t.split(' ')[0]!)
  const dup = [...new Set(heads)].filter((h) => heads.filter((x) => x === h).length > 1)
  console.log(`\n  重复标题: ${dup.length ? base.pyReprList(dup) : '无'}`)

  let missing: string[] = []
  if (expectLangs) {
    const hit: Record<string, boolean> = {}
    for (const [k, v] of Object.entries(expectLangs)) {
      hit[k] = seen.some((t) => t.includes(v))
    }
    missing = Object.entries(hit).filter(([, v]) => !v).map(([k]) => k)
    const hitCount = Object.values(hit).filter(Boolean).length
    console.log(
      `  语种覆盖: ${hitCount}/${Object.keys(expectLangs).length}  缺=${missing.length ? base.pyReprList(missing) : '无'}`,
    )
  }

  // 交叉验证：作品面板里「只看可添加的作品」→ 本系列还剩 0 支可挂 = 全挂上了
  let left: number | null = null
  if (crossCheck) {
    console.log('\n▶ 交叉验证：作品面板 → 只看可添加的作品')
    for (const kw of ['添加作品', '点击添加作品']) {
      const loc = page.getByText(kw, { exact: true })
      if ((await loc.count()) && (await base.visibleWithin(loc.first(), 2000))) {
        await loc.first().click()
        break
      }
    }
    await clock.sleep(5)
    const box = page.locator(
      "input[placeholder*='查找作品'], input[placeholder*='作品描述']",
    ).first()
    await box.click()
    await box.fill(keyword)
    await page.keyboard.press('Enter')
    await clock.sleep(4.5)
    const chk = page.getByText('只看可添加的作品', { exact: false }).first()
    if (await chk.count()) {
      await chk.click()
      await clock.sleep(4)
      console.log('  ✓ 勾上「只看可添加的作品」')
    }
    await shot('verify-only-addable.png')
    const body = await page.innerText('body', { timeout: 8000 })
    const mm = /共\s*(\d+)\s*个作品/.exec(body)
    left = mm ? Number(mm[1]) : -1
    console.log(
      `  本系列「还可添加」的作品数 = ${left}  ${left === 0 ? '✓ 全挂上了' : '✗ 还有漏'}`,
    )
  }

  const bothOk = n === want && seen.length === want
  console.log(
    `\n  双通道互证：卡片计数 ${n} / 清单 ${seen.length} / 预期 ${want} → ${bothOk ? '✓ 齐' : '✗ 不齐'}`,
  )
  const result: VerifyColResult = {
    title,
    want,
    count: n,
    items: seen,
    dup,
    missing_lang: missing,
    addable_left: left,
    both_channels_ok: bothOk,
  }
  writeFileSync(join(outDir, 'verify-col.json'), JSON.stringify(result, null, 2))
  console.log('👉 最终判定仍以人眼看 verify-col-card.png / scroll-list-*.png 为准')
  return result
}

/** 便捷入口：launch + verify（登录态在平台 profile 里，未登录则当场停下）。 */
export async function run(
  platform: string,
  opts: { profileDir?: string | null; outDir: string; keyword?: string; headless?: boolean },
): Promise<VerifyResult> {
  const profileDir = opts.profileDir || base.profileDir(platform)
  return base.launch(
    profileDir,
    {
      headless: opts.headless ?? false,
      viewport: PLATFORMS[platform]!.viewport,
    },
    async (_ctx, page) => verify(platform, page, opts.outDir, { keyword: opts.keyword }),
  )
}
