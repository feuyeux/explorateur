// collections.ts — 抖音合集收录（⑩）：编辑补挂 / 新建两条流程
// （publish/collections.py 的 TS 移植）。
//
// 平台差异（实测）：
// - 抖音：合集在内容管理 `?tab=collections`，两条流程都实测过——
//   这是唯一在本模块实现全流程的平台。
// - B 站：合集需**创作中心 Lv2**，等级不够时 UI 上是灰字、无可点控件，
//   无法绕过（先攒等级，别硬闯）。
// - 小红书：网页创作平台**没有合集管理页**——加入合集走「编辑单条笔记 →
//   选择合集」的逐条链路，不存在批量补挂入口。
//
// 使用契约：
// - 只对**自己的账号内容**操作；page 由 base.launch 给出（resolver Chrome）。
// - 保存是修改类操作：计数不符就不点保存、保留现场（每步截图落 outDir）。
// - title / want / searchKw / desc / cover 全部由调用方传入——本模块不写死
//   任何项目内容。
import { writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'

import * as base from './base.js'
import * as clock from './clock.js'

export const MANAGE = 'https://creator.douyin.com/creator-micro/content/manage?tab=collections'

// 找「+」按钮：24x24 svg，在右侧抽屉面板内，行内不含「已添加」。
// 选择器长在按钮自己的几何特征上，不靠「文本行去重取序号」（曾每轮都点
// 同一行）。几何判定禁绝对坐标——那等于把 viewport 宽度写死，inPanel 一律
// 相对视口；行文本也不按 search_kw 过滤（曾静默漏挂），未添加的一律返回，
// 数量核对交给调用方。几何判据只允许一份实现：JS_PLUS 与 scroller 共用
// JS_GEOM，各写一份必然漂移。
// （Python 源里 `\\s` = 求值字符串中的 `\s`，TS 模板串同样要双写反斜杠。）
const JS_GEOM = `
  const vw = window.innerWidth || 1600;
  const inPanel = (r) => r.x + 24 >= vw * 0.62     // 在右侧抽屉面板内
                       && r.x <= vw - 26 + 12      // 且贴近面板右缘（内约 26px）
                       && r.y >= 140;             // 排除右上角关闭/清空图标
`
const JS_PLUS = `() => {${JS_GEOM}  const cands = [];
  document.querySelectorAll('svg').forEach(e => {
    const r = e.getBoundingClientRect();
    if (Math.abs(r.width - 24) > 3 || Math.abs(r.height - 24) > 3) return;
    if (!inPanel(r)) return;
    let p = e, row = null;
    for (let i = 0; i < 9 && p; i++) {
      p = p.parentElement;
      if (p && /发布于/.test(p.innerText || '')) { row = p; break; }
    }
    if (!row) return;
    const rt = (row.innerText || '').replace(/\\s+/g, ' ').trim();
    if (rt.length > 220) return;                 // 行容器识别失败
    // ⚠️ 原来要求行文本包含 search_kw。实测标题未必含该词（12 条里只 3 条含），
    // 其余永远匹配不上 → 静默漏挂。
    // 改为：**未添加的一律返回**，数量核对交给调用方。
    if (rt.includes('已添加')) return;
    cands.push({t: rt.slice(0, 46), x: Math.round(r.x), y: Math.round(r.y)});
  });
  cands.sort((a, b) => a.y - b.y);
  return cands;
}`

const JS_COUNT = `() => {
  const b = document.body.innerText || '';
  // ⚠️ 空合集时页面**根本没有**「合集内作品 N」这段文本
  //（截图实证：只有标题 +「点击添加作品」）。旧正则匹配不到返回 -1，
  // 与「面板被服务端清空」混为一谈。
  // 现在区分三种状态：正数 = 计数 / 0 = 确认空 / -1 = 未知。
  const m = b.match(/合集内作品\\s*(\\d+)/);
  if (m) return parseInt(m[1], 10);
  if (/点击添加作品/.test(b)) return 0;
  return -1;
}`

// 面板是否被服务端错误清空
const JS_PANEL_EMPTY = `() => {
  const b = document.body.innerText || '';
  // ⚠️ 原来把「没有更多视频」当成面板被清空。实测那是
  // **分页到底**的正常文案，不是故障。判据应是「共 0 个作品」或服务端错误。
  if (/共\\s*0\\s*个作品/.test(b)) return true;
  if (/服务器\\/网络开小差了/.test(b)) return true;
  return false;
}`

// 关掉飘在页面上的错误 toast，避免遮挡底部按钮
const JS_CLEAR_TOAST = `() => {
  let n = 0;
  document.querySelectorAll('svg,button,div,span').forEach(e => {
    const r = e.getBoundingClientRect();
    if (r.width > 26 || r.height > 26) return;
    if (r.x < 600 || r.x > 990) return;         // toast 关闭钮在中间偏上
    if (r.y < 10 || r.y > 360) return;
    let p = e;
    for (let i = 0; i < 5 && p; i++) {
      if (/开小差了|稍后再试/.test(p.innerText || '')) {
        try { e.click(); n++; } catch (err) {}
        break;
      }
      p = p.parentElement;
    }
  });
  return n;
}`

async function shot(page: base.AnyPage, outDir: string, n: string): Promise<void> {
  try {
    await page.screenshot({ path: join(outDir, n) })
    console.log(`  📸 ${n}`)
  } catch {
    // 截图只是留证
  }
}

export async function dismiss(page: base.AnyPage): Promise<void> {
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
}

/** 面板被服务端错误清空时，重新搜索把列表拉回来。 */
export async function research(
  page: base.AnyPage,
  opts: { searchKw: string; outDir: string; tries?: number },
): Promise<boolean> {
  const tries = opts.tries ?? 4
  for (let k = 0; k < tries; k++) {
    await page.evaluate(JS_CLEAR_TOAST)
    await clock.sleep(1.2)
    try {
      const box = page.locator(
        "input[placeholder*='查找作品'], input[placeholder*='作品描述']",
      ).first()
      await box.click()
      await box.fill('')
      await box.fill(opts.searchKw)
      await page.keyboard.press('Enter')
    } catch (e) {
      console.log(`    重搜 ${k + 1} 异常 ${base.errName(e)}`)
    }
    await clock.sleep(4.5)
    await page.evaluate(JS_CLEAR_TOAST)
    const empty = await page.evaluate(JS_PANEL_EMPTY)
    const n = await page.evaluate(JS_PLUS)
    console.log(`    重搜 ${k + 1}: 空=${empty} 待加=${n.length}`)
    if (!empty && n.length) return true
  }
  return false
}

/** 打开作品选择面板并搜索本系列（fix/make 两流程共用）。 */
async function openPickerAndSearch(
  page: base.AnyPage,
  opts: { searchKw: string; outDir: string },
): Promise<void> {
  console.log('▶ 打开作品面板')
  outer:
  for (const kw of ['点击添加作品', '添加上传的视频作品到你的合集里', '添加作品']) {
    const loc = page.getByText(kw, { exact: false })
    const n = Math.min(await loc.count(), 6)
    for (let i = 0; i < n; i++) {
      try {
        if (await base.visibleWithin(loc.nth(i), 800)) {
          await loc.nth(i).click()
          break outer
        }
      } catch {
        continue
      }
    }
  }
  await clock.sleep(5)

  const box = page.locator(
    "input[placeholder*='查找作品'], input[placeholder*='作品描述']",
  ).first()
  await box.click()
  await box.fill(opts.searchKw)
  await page.keyboard.press('Enter')
  console.log(`  ✓ 搜索「${opts.searchKw}」`)
  await clock.sleep(5)
}

/**
 * 逐个补挂（基准循环，douyin_fix_collection 已验证）。
 *
 * ⛔ 不要改成「扫文本行 → 去重 → 按序号取第 i 个」（douyin_make_collection
 * 的 JS_ROWS）：去重每轮都返回 target[0]，12 次点击全落在同一行（缺陷②）。
 * JS_PLUS 每轮现取**最上面那支未添加的**（svg 24x24 + 在右侧面板内 + 不含「已添加」），
 * 已添加的行天然被过滤，不存在「同一行点 12 次」。
 */
async function addLoop(
  page: base.AnyPage,
  opts: { want: number; searchKw: string; before: number; outDir: string },
): Promise<[string[], string[]]> {
  const { want, before } = opts
  const added: string[] = []
  const fails: string[] = []
  let researches = 0
  const seen = new Set<string>() // 已点过的行首文字，防重复点击
  let stale = 0 // 连续取到同一支的次数
  for (let rnd = 0; rnd < want + 14; rnd++) {
    const cands = await page.evaluate(JS_PLUS)
    if (!cands.length) {
      // 面板被服务端错误清空了 → 重搜自愈，而不是放弃
      if (researches >= 5) {
        console.log(`  轮${rnd + 1}: 面板仍空，重搜次数用尽`)
        break
      }
      researches++
      console.log(`  轮${rnd + 1}: 面板无未添加行（第 ${researches} 次重搜）`)
      if (await research(page, opts)) continue
      console.log('    重搜失败，停止')
      break
    }
    // 滚动进视口中心再取新鲜坐标。几何判据**不再另写一份**——直接拼
    // JS_GEOM（这里曾另有 `r.x > 1500` 硬编码，两份
    // 漂移后 viewport=1700 找不到元素 → 滚动没发生 → 拿旧坐标点击 →
    // 轮10/11/12 三次都点在同一条希伯来语行上（12 次点击只加进 9 支））。
    await page.evaluate(`(y) => {${JS_GEOM}
            const el = [...document.querySelectorAll('svg')].find(e => {
                const r = e.getBoundingClientRect();
                return Math.abs(r.width-24)<3 && Math.abs(r.height-24)<3
                       && inPanel(r) && Math.abs(Math.round(r.y)-y) < 30; });
            if (el) el.scrollIntoView({block: 'center'});
        }`, cands[0]['y'])
    await clock.sleep(1.0)
    let c2 = await page.evaluate(JS_PLUS)
    if (!c2.length) {
      await clock.sleep(1.2)
      c2 = await page.evaluate(JS_PLUS)
    }
    if (!c2.length) {
      researches++
      await research(page, opts)
      continue
    }
    const c = c2[0]
    // ⚠️ 护栏：坐标失效时 JS_PLUS 会反复返回同一支
    // （上一版实测轮10/11/12 连点同一条希伯来语，12 次点击只加进 9 支）。
    // 这里按**行首文字**去重，已点过的直接跳过——
    // 宁可少点，也不要把同一条点 12 次然后拿一个假计数当成功。
    // 去重键 = 行文本前 46 字符（JS_PLUS 里 slice(0,46) 截的）。
    // 假设：各行行首 46 字符互不相同（本系列标题含语种名，天然错开）；
    // 若未来行间共享更长前缀，这里会误跳——那不是本护栏的适用场景。
    const key = (c['t'] as string).trim()
    if (seen.has(key)) {
      console.log(`  轮${rnd + 1}: ⏭ 跳过重复「${base.clip(key, 24)}」（坐标可能已失效）`)
      stale++
      if (stale >= 6) {
        console.log('  ⚠️ 连续多次取到同一支，判定位失效，停止本轮')
        break
      }
      // 面板没刷新：滚一下再取，避免死循环
      await page.mouse.wheel(0, 420)
      await clock.sleep(1.0)
      continue
    }
    stale = 0
    seen.add(key)
    const px = c['x'] + 12
    const py = c['y'] + 12
    try {
      await page.mouse.click(px, py)
      await clock.sleep(2.2)
      await page.evaluate(JS_CLEAR_TOAST)
      added.push(c['t'])
      console.log(`  轮${rnd + 1}: ✓ 加「${base.clip(c['t'], 30)}」  累计 ${added.length}`)
    } catch (e) {
      fails.push(c['t'])
      console.log(`  轮${rnd + 1}: ✗ ${base.clip(c['t'], 30)} → ${base.errName(e)}`)
      await clock.sleep(1.5)
    }
    if (added.length + before >= want) break
  }
  return [added, fails]
}

export interface FixCollectionResult {
  ok: boolean
  count?: number
  log: Record<string, unknown>[]
}

/**
 * 编辑已有合集，补挂缺失作品 → 计数核对 → 达标才保存。
 *
 * 返回 log（原版落盘 fix-collection.json 的内容 + 退出状态在 ok）。
 * 计数不符就不点「保存」、保留现场——修改类操作的默认保守（纪律 15/19）。
 */
export async function fixCollection(
  page: base.AnyPage,
  opts: { title: string; want: number; searchKw: string; outDir: string },
): Promise<FixCollectionResult> {
  const outDir = opts.outDir
  mkdirSync(outDir, { recursive: true })
  const log: Record<string, unknown>[] = []

  await page.goto(MANAGE, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await clock.sleep(10)
  await dismiss(page)

  // ---- 定位合集卡片 ----
  console.log('▶ 打开合集编辑页')
  const cards = page.locator("[class*='collection-card-']")
  let card: any = null
  const cnt = await cards.count()
  for (let i = 0; i < cnt; i++) {
    const c = cards.nth(i)
    try {
      const txt = (await c.innerText({ timeout: 3000 })) ?? ''
      if (txt.includes(base.clip(opts.title, 6))) {
        card = c
        break
      }
    } catch {
      continue
    }
  }
  if (card === null) {
    console.log('  ✗ 找不到合集卡片，中止')
    log.push({ stage: 'abort', reason: 'card-not-found' })
    writeFileSync(join(outDir, 'fix-collection.json'), JSON.stringify(log, null, 2))
    return { ok: false, log }
  }
  await card.scrollIntoViewIfNeeded()
  await clock.sleep(0.8)
  await card.locator("[class*='new-layout-action-']").first().click()
  await clock.sleep(6)
  await shot(page, outDir, 'fix-01-edit-open.png')

  const before = await page.evaluate(JS_COUNT)
  console.log(`  编辑页「合集内作品」= ${before}`)
  log.push({ stage: 'open', before })
  if (before > opts.want) {
    console.log(`  ⚠ 已有 ${before} > 预期 ${opts.want} —— 仍按补挂逻辑继续`)
  }

  await openPickerAndSearch(page, { searchKw: opts.searchKw, outDir })
  await shot(page, outDir, 'fix-02-searched.png')

  // ---- 逐个补挂（基准：JS_PLUS svg 选择器，缺陷②修复） ----
  const [added, fails] = await addLoop(page, {
    want: opts.want,
    searchKw: opts.searchKw,
    before,
    outDir,
  })
  await shot(page, outDir, 'fix-03-all-added.png')

  // ---- 关闭面板 ----
  console.log('▶ 关闭作品面板')
  // 绝不盲点绝对坐标（换视口/缩放/改版后点中的目标不可预测——栽过）。
  // 一律元素定位：关闭钮 → ESC → 还在就如实报出来人工看。
  let closed = false
  for (const sel of ["[class*='semi-modal-close']", "[class*='icon-close']"]) {
    try {
      const loc = page.locator(sel).first()
      if (await base.visibleWithin(loc, 800)) {
        await loc.click({ timeout: 3000 })
        closed = true
        break
      }
    } catch {
      continue
    }
  }
  await clock.sleep(1)
  if (!closed) {
    try {
      await page.keyboard.press('Escape')
    } catch {
      // 键盘不可用就靠关闭钮
    }
  }
  await clock.sleep(2)
  // 若面板还在，按 ESC
  if ((await page.evaluate(JS_PLUS)).length) {
    await page.keyboard.press('Escape')
    await clock.sleep(2)
  }
  await shot(page, outDir, 'fix-04-panel-closed.png')

  const after = await page.evaluate(JS_COUNT)
  console.log(`\n  「合集内作品」= ${after}（预期 ${opts.want}）`)
  log.push({ stage: 'added', count: after, added, fails })

  if (after !== opts.want) {
    console.log(`  ✗ 数量不符（${after} != ${opts.want}），不点保存，保留现场`)
    writeFileSync(join(outDir, 'fix-collection.json'), JSON.stringify(log, null, 2))
    return { ok: false, count: after, log }
  }
  console.log('▶ 点「保存」')
  await page.getByText('保存', { exact: true }).first().scrollIntoViewIfNeeded()
  await clock.sleep(0.8)
  await page.getByText('保存', { exact: true }).first().click()
  await clock.sleep(7)
  await shot(page, outDir, 'fix-05-saved.png')
  console.log(`  URL ${page.url}`)
  // 判据只信可见文本（inner_text('body') 会被隐藏层文案骗，login.probe 同源教训）
  const back = await base.visibleTextHit(page, [opts.title])
  console.log(`  返回列表页: ${back}`)
  log.push({ stage: 'saved', url: page.url, back_to_list: back })
  try {
    const b2 = await page.innerText('body', { timeout: 10000 })
    for (const kw of ['保存成功', '操作成功', '创建成功']) {
      if (b2.includes(kw)) console.log(`  成功提示: ${kw}`)
    }
  } catch {
    // 提示读不到不 Blocking
  }

  writeFileSync(join(outDir, 'fix-collection.json'), JSON.stringify(log, null, 2))
  return { ok: back, count: after, log }
}

/**
 * 创建合集：填表 + 上传封面 + 打开作品选择面板 + JS_PLUS 挂 want 支 → 创建。
 *
 * 表单/封面/面板步骤为实测有效的做法；挂作品环节**不用** make 版的 JS_ROWS 循环（缺陷②），
 * 走 fix 版的 addLoop（JS_PLUS）。
 */
export async function createCollection(
  page: base.AnyPage,
  opts: { title: string; desc: string; cover: string; want: number; searchKw: string; outDir: string },
): Promise<boolean> {
  const outDir = opts.outDir
  mkdirSync(outDir, { recursive: true })

  await page.goto(MANAGE, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await clock.sleep(9)
  await dismiss(page)

  console.log('▶ 打开创建合集')
  await page.getByText('创建合集', { exact: true }).first().click()
  await clock.sleep(3)

  const ti = page.locator("input[placeholder*='合集的标题']").first()
  await ti.click()
  await ti.fill(opts.title)
  const de = page.locator("textarea[placeholder*='合集的简介']").first()
  await de.click()
  await de.fill(opts.desc)
  console.log(
    `  ✓ 标题「${opts.title}」(${Array.from(opts.title).length}/20)  简介(${Array.from(opts.desc).length}/200)`,
  )

  await page.locator('input[type=file]').first().setInputFiles(opts.cover)
  await clock.sleep(4)
  // 封面上传后会弹裁剪框 → 点「保存」确认（方图无裁切）
  outer:
  for (const kw of ['保存', '确定', '完成']) {
    const loc = page.getByText(kw, { exact: true })
    const n = Math.min(await loc.count(), 4)
    for (let i = 0; i < n; i++) {
      try {
        if (await base.visibleWithin(loc.nth(i), 900)) {
          await loc.nth(i).click()
          console.log(`  ✓ 封面裁剪「${kw}」`)
          await clock.sleep(2)
          break outer
        }
      } catch {
        continue
      }
    }
  }
  await shot(page, outDir, 'create-01-cover-ok.png')

  await openPickerAndSearch(page, { searchKw: opts.searchKw, outDir })
  await shot(page, outDir, 'create-02-searched.png')

  const [added, fails] = await addLoop(page, {
    want: opts.want,
    searchKw: opts.searchKw,
    before: 0,
    outDir,
  })
  await shot(page, outDir, 'create-03-added.png')
  console.log(`\n  共加入 ${added.length} 支（失败 ${fails.length}）`)

  // 关闭抽屉：ESC → 关闭钮 → 还开着就如实报出来（不盲点空白坐标）
  try {
    await page.keyboard.press('Escape')
    await clock.sleep(1.5)
  } catch {
    // 键盘不可用就靠关闭钮
  }
  for (const sel of [
    "[class*='semi-modal-close']",
    "[class*='icon-close']",
    "div[role='dialog'] [class*='close']",
  ]) {
    try {
      const loc = page.locator(sel).first()
      if (await base.visibleWithin(loc, 600)) {
        await loc.click({ timeout: 2000 })
        break
      }
    } catch {
      continue
    }
  }
  if ((await page.evaluate(JS_PLUS)).length) {
    console.log('  ⚠ 作品面板还开着（关闭钮与 ESC 都没关上），继续前请人工看一眼')
  }
  await clock.sleep(2)
  await shot(page, outDir, 'create-04-before-create.png')

  const body = await page.innerText('body', { timeout: 8000 })
  console.log('\n=== 合集内作品区 ===')
  const i = body.indexOf('合集内作品')
  console.log(`  ${i >= 0 ? body.slice(i, i + 200).replace(/\n/g, ' | ') : '（未找到）'}`)

  // 创建
  const btn = page.getByText('创建', { exact: true }).first()
  await btn.scrollIntoViewIfNeeded()
  await clock.sleep(0.8)
  await btn.click()
  console.log('\n  ✓ 点「创建」')
  await clock.sleep(6)
  await shot(page, outDir, 'create-05-created.png')
  console.log(`  URL ${page.url}`)
  // 判据只信可见文本（同 fixCollection 的 back 判据口径）
  const ok = await base.visibleTextHit(page, [opts.title])
  console.log(`  页面含新合集名（可见）：${ok}`)
  return ok
}
