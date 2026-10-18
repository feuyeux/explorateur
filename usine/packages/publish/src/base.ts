// base.ts — 发布器共享骨架（⑨）：三份发布器的公共结构拆成可测小函数
// （publish/base.py 的 TS 移植）。
//
// 平台特有逻辑在 douyin.ts / xhs.ts / bilibili.ts。两条硬约定：
// - `runTasks` 的防风控节流写在**循环内**（每条之间都睡；实测连发 2 条就撞风控）。
// - `resolveChrome()` 经 `platform.browser(only="chrome")` 解析（全仓唯一事实源），
//   找不到显式报缺（FeuilleError），绝不编路径、绝不退化成「系统默认」；
//   `FEUILLE_BROWSER` 环境变量可临时覆盖。
//
// 移植约定：
// - playwright **只在函数内 lazy import**（`await import('playwright')`）：主环境
//   不装 playwright 也必须能 import 本包；真跑发布先装 playwright（可选依赖组）。
//   Playwright TS 只有 async API → 全部页面驱动函数 async；page/ctx 一律 any
//   （playwright 不进静态依赖，类型见 playwright.d.ts 的 ambient 声明）。
// - Python SystemExit → FeuilleError（消息到 stderr、退出码 1，CLI 可见口径不变）。
// - time.sleep → clock.sleep（独立小模块：门禁要 vi.mock 整模块记录「发布→歇→
//   发布」事件序列，不动业务签名）。
// - Python 字符串切片按码点（str[:n]），JS slice 按 UTF-16 单元——统一走 clip()。
// - Python `is_visible(timeout=ms)` 会等；JS Locator.isVisible() 是即时判定——
//   差异用 visibleWithin()（waitFor）补齐，调用处的 try/catch 结构按原样镜像。
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'

import { FeuilleError, platform as pt } from '@feuille/core'

import * as clock from './clock.js'

export type AnyPage = any
export type AnyCtx = any
export type Task = Record<string, any>
export type PubResult = Record<string, any>

// ---------------------------------------------------------------- Python 口径小件
/** Python repr 常见形态：str 单引号、None 无引号（报错文案与 Python 侧逐字一致用）。 */
export function pyRepr(v: unknown): string {
  if (v === null || v === undefined) return 'None'
  if (typeof v === 'string') return `'${v}'`
  return String(v)
}

/** Python str(sorted(dict)) 的排版：`['a', 'b']`（键升序）。 */
export function pyList(items: readonly string[]): string {
  return `[${[...items].sort().map((s) => `'${s}'`).join(', ')}]`
}

/** Python list 直接进 f-string 的排版：`['x', 'y']`。 */
export function pyReprList(items: readonly unknown[]): string {
  return `[${items.map((x) => pyRepr(x)).join(', ')}]`
}

/** Python type(x).__name__ 的最小口径（manifest 顶层键报错用）。 */
export function pyTypeName(v: unknown): string {
  if (v === null) return 'NoneType'
  if (Array.isArray(v)) return 'list'
  switch (typeof v) {
    case 'object': return 'dict'
    case 'string': return 'str'
    case 'boolean': return 'bool'
    case 'number': return Number.isInteger(v) ? 'int' : 'float'
    default: return typeof v
  }
}

/** Python str 切片语义：按码点取前 n 个（JS slice 按 UTF-16 单元，会截散 emoji）。 */
export function clip(s: string, n: number): string {
  return Array.from(s).slice(0, n).join('')
}

/** Python type(e).__name__ 口径（门禁里 err.name='RuntimeError' 模拟原生异常名）。 */
export function errName(e: unknown): string {
  return e instanceof Error ? e.name : String(e)
}

/** Python str(e) 口径：Error 取 message（String(err) 会带 "Error:" 前缀）。 */
export function errStr(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}

/** `:02d`。 */
export function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

/** Python is_visible(timeout=ms)：等到可见或超时（JS API 里 isVisible() 即时，这里补齐）。 */
export async function visibleWithin(loc: any, timeoutMs: number): Promise<boolean> {
  try {
    await loc.waitFor({ state: 'visible', timeout: timeoutMs })
    return true
  } catch {
    return false
  }
}

// ---------------------------------------------------------------- 平台 profile 表
// 各平台持久 user-data 目录（登录态存盘勿删）。作为数据放在表里，不散落在代码里。
export const PROFILES: Record<string, string> = {
  douyin: '~/.douyin_creator_profile',
  xiaohongshu: '~/.xhs_creator_profile',
  bilibili: '~/.bili_creator_profile',
  zhihu: '~/.zhihu_creator_profile',
}

/** os.path.expanduser 的最小版（platform.ts 未导出，这里复制同一实现）。 */
function expanduser(p: string): string {
  if (p === '~') return homedir()
  if (p.startsWith('~/') || p.startsWith('~\\')) return join(homedir(), p.slice(2))
  return p
}

/** 平台持久 profile 目录（展开后的绝对路径）。 */
export function profileDir(platformKey: string): string {
  if (!(platformKey in PROFILES)) {
    throw new FeuilleError(`未知平台 ${pyRepr(platformKey)}（合法：${pyList(Object.keys(PROFILES))}）`)
  }
  return resolve(expanduser(PROFILES[platformKey]!))
}

/**
 * Chrome 可执行文件绝对路径——**唯一入口**，发布器一律从这里拿（缺陷③修复）。
 *
 * 经 `platform.browser(only='chrome')` 解析（发布 profile 与 Chrome 绑定，所以
 * 只认 Chrome，不吃 Edge 候选；`FEUILLE_BROWSER` 环境变量可临时覆盖做 A/B）。
 * 找不到 = 显式报缺并中止，绝不编造路径、绝不退化成 Playwright 自带浏览器。
 */
export function resolveChrome(): string {
  const b = pt.browser('chrome')
  if (b === null) {
    throw new FeuilleError(
      '找不到 Chrome：发布器用系统 Chrome + 持久 profile（自带 Chromium 没有登录态）。'
      + '装 Google Chrome，或设 FEUILLE_BROWSER 指向可执行文件。')
  }
  return b[1]
}

export interface LaunchOpts {
  headless?: boolean
  viewport?: { width: number; height: number } | null
  args?: string[] | null
}

/**
 * Chrome 持久 profile 启动（Python with base.launch(...) 的回调形态移植）。
 *
 * 回调返回或抛异常都保证 close context——关闭才把 cookie 写进 profile
 * （登录态落盘）；跳过 close = 下次发布全部掉登录。
 */
export async function launch<T>(
  profileDir_: string,
  opts: LaunchOpts,
  fn: (ctx: AnyCtx, page: AnyPage) => Promise<T>,
): Promise<T> {
  const exe = resolveChrome()
  const userDataDir = resolve(expanduser(profileDir_))
  mkdirSync(userDataDir, { recursive: true })
  let pw: any
  try {
    pw = await import('playwright')
  } catch (e) {
    // 镜像 cli.py 的契约：缺 playwright 报「缺 playwright」，不是「未知命令」
    throw new FeuilleError(
      `缺 playwright（可选依赖未装）：发布前先安装 playwright。原始报错：${errName(e)}`)
  }
  const ctx = await pw.chromium.launchPersistentContext({
    user_data_dir: userDataDir,
    executable_path: exe,
    headless: opts.headless ?? false,
    viewport: opts.viewport ?? { width: 1440, height: 900 },
    args: opts.args ?? ['--start-maximized', '--disable-blink-features=AutomationControlled'],
  })
  const page = ctx.pages && ctx.pages.length ? ctx.pages[0] : await ctx.newPage()
  try {
    return await fn(ctx, page)
  } finally {
    // 任何路径都要关 context——关闭才把 cookie 写进 profile
    await ctx.close()
  }
}

// ---------------------------------------------------------------- 登录墙
// 登录墙关键词（各平台后台实测过的面板文案，按平台传自己的子集）
export const WALL_DEFAULT: readonly string[] = [
  '扫码登录', '验证码登录', '密码登录', '手机号登录', '立即登录', '登录后',
]

/**
 * 登录墙判定：只信**可见**文本。
 *
 * 踩过的坑（login._visibleTexts 同源教训）：登录弹窗是浮层，底层页面的「作品管理」
 * 等文案仍躺在 body 文本里，按 inner_text('body') 判会把「未登录」误判成
 * 「已登录」——必须逐关键词 get_by_text + is_visible。
 */
export async function loginWall(page: AnyPage, kws: readonly string[] = WALL_DEFAULT): Promise<boolean> {
  for (const kw of kws) {
    try {
      const loc = page.getByText(kw, { exact: false })
      if ((await loc.count()) && (await loc.first().isVisible())) return true
    } catch {
      continue
    }
  }
  return false
}

/** 人工扫码等待（纪律 21：认证一律人工，agent 不代填）。墙消失即返回 True。 */
export async function waitLogin(
  page: AnyPage,
  timeoutS = 600,
  opts: { pollS?: number; kws?: readonly string[] } = {},
): Promise<boolean> {
  const pollS = opts.pollS ?? 3
  const kws = opts.kws ?? WALL_DEFAULT
  const deadline = clock.now() + timeoutS
  let tick = 0
  while (clock.now() < deadline) {
    if (!(await loginWall(page, kws))) {
      console.log('   ✅ 已检测到登录完成')
      return true
    }
    if (tick % 10 === 0) {
      console.log(`   ⏳ 仍在等待扫码…（余 ${Math.floor((deadline - clock.now()) / 60) + 1} 分钟）`)
    }
    tick++
    await clock.sleep(pollS)
  }
  console.log('   ❌ 超时未登录，中止。')
  return false
}

// ---------------------------------------------------------------- 发布按钮
// 真正的「发布」按钮：角色=button 且文本**精确**等于「发布」。
// 踩过的坑：原来用 `button:has-text('发布')` 做子串匹配，而左上角导航有个
// 「作品发布」按钮也含「发布」二字，于是 .first 一直点中它——点完只跳草稿页，
// 脚本却自报「已发布」。文本必须 exact，且 class 要含 primary。
export const PUB_BTN_EXACT = 'button:text-is("发布")'

/** 返回真正的发布按钮 locator；找不到返回 null。绝不退回子串匹配。 */
export async function findPublishButton(page: AnyPage, texts: readonly string[] = ['发布']): Promise<AnyPage> {
  for (const txt of texts) {
    try {
      const loc = page.locator(`button:text-is("${txt}")`)
      const n = await loc.count()
      for (let i = 0; i < n; i++) {
        const b = loc.nth(i)
        if (!(await visibleWithin(b, 500))) continue
        const cls = (await b.getAttribute('class')) ?? ''
        const t = ((await b.innerText()) ?? '').trim()
        if (t !== txt) continue
        // 主按钮的 class 里带 primary
        if (!cls.toLowerCase().includes('primary')) continue
        return b
      }
    } catch {
      // 按原样镜像：单文本失败继续下一个
    }
  }
  return null
}

// ---------------------------------------------------------------- 填词（三家共用）
/** 全选清空。必须用 ControlOrMeta+A（Playwright 可移植组合键）。 */
export async function selectAllClear(page: AnyPage): Promise<void> {
  await page.keyboard.press('ControlOrMeta+A')
  await page.keyboard.press('Backspace')
}

/** 标题录入。失败返回 False——调用方按纪律 19 中止本条，不带着空标题发布。 */
export async function fillTitle(
  page: AnyPage,
  box: any,
  title: string,
  opts: { limit: number },
): Promise<boolean> {
  const snippet = clip(title, opts.limit)
  try {
    await box.click()
    await box.fill(snippet)
    console.log(`   ✓ 标题已录入（${Array.from(snippet).length}/${opts.limit} 字）`)
    return true
  } catch (e) {
    console.log(`   ❌ 标题录入失败：${errStr(e)}`)
    return false
  }
}

/**
 * 正文录入（可选逐个补 #话题）。
 *
 * contenteditable 编辑器必须走键盘输入（fill() 不触发 contenteditable 的
 * 输入事件，栽过）。失败返回 False——正文是发布内容的一部分，录不进去
 * = 「做了一半」，按纪律 19 中止而不是照发。
 */
export async function fillBody(
  page: AnyPage,
  box: any,
  body: string,
  opts: { tags?: readonly string[]; pause?: number } = {},
): Promise<boolean> {
  const tags = opts.tags ?? []
  const pause = opts.pause ?? 0.3
  try {
    await box.click()
    await selectAllClear(page)
    await page.keyboard.type(body)
    if (tags.length) {
      await page.keyboard.type('\n\n')
      for (const topic of tags) {
        await page.keyboard.type(topic.startsWith('#') ? topic : `#${topic}`)
        await page.keyboard.type(' ')
        await clock.sleep(pause)
      }
    }
    console.log(tags.length ? `   ✓ 正文已录入（${tags.length} 个话题）` : '   ✓ 正文已录入')
    return true
  } catch (e) {
    console.log(`   ❌ 正文录入失败：${errStr(e)}`)
    return false
  }
}

/** dry-run 停手：截图留证 + 报残留弹窗，绝不点发布。三家共用同一口径。 */
export async function dryRunStop(
  page: AnyPage,
  res: PubResult,
  opts: { logDir: string; shotName: string; blocking: () => Promise<readonly string[]> },
): Promise<PubResult> {
  try {
    await page.screenshot({ path: join(opts.logDir, opts.shotName) })
  } catch {
    // 截图只是留证，不让它中断收尾
  }
  const left = await opts.blocking()
  res['ok'] = left.length === 0
  res['stage'] = !left.length ? '已填词(dry-run，未发布)' : `残留弹窗 ${pyReprList(left)}`
  console.log(`   🧪 dry-run：未发布。截图 ${opts.shotName}`)
  if (left.length) console.log(`   ❌ 仍有弹窗挡着：${pyReprList(left)}`)
  return res
}

// ---------------------------------------------------------------- 成功判定
/**
 * 可见文本全词命中——与 login_wall 同口径（只信可见文本），判成功的公共判据。
 *
 * 踩过的坑：inner_text('body') 会把 display:none 的底层文案也算进来
 * （login.probe 在这里翻过车）。判**成功**必须从严：隐藏层的「成功」文案
 * 命中 = 谎报成功，比报「未确认」糟糕得多。
 */
export async function visibleTextHit(page: AnyPage, words: readonly string[]): Promise<boolean> {
  for (const k of words) {
    try {
      const loc = page.getByText(k, { exact: false })
      if ((await loc.count()) && (await loc.first().isVisible())) return true
    } catch {
      continue
    }
  }
  return false
}

/**
 * 成功判定（带阶段名）。命中全词 → [true, "已发布"]；
 * URL 离开投稿页（url_gone 里的子串全都不在了）→ [true, "已跳转"]；
 * 超时 → [false, "已提交未确认"]。
 *
 * B 站成功页文案是「稿件投递成功」全词——v1 词表缺「投递」二字，11 条实际
 * 已进后台的稿件全被判成「已提交未确认」（见 bilibili.BILI_SUCCESS_WORDS 的
 * 坑注）。词表由平台模块以数据传入，本函数不做任何默认兜底：词表缺词 =
 * 判不出成功，这正是如实报「未确认」而不是谎报成功的底线。
 */
export async function waitSuccessStage(
  page: AnyPage,
  words: readonly string[],
  timeoutS = 120,
  pollS = 2,
  opts: { urlGone?: readonly string[] } = {},
): Promise<[boolean, string]> {
  const urlGone = opts.urlGone ?? []
  const deadline = clock.now() + timeoutS
  while (clock.now() < deadline) {
    if (await visibleTextHit(page, words)) return [true, '已发布']
    if (urlGone.length) {
      try {
        if (!urlGone.some((u) => page.url.includes(u))) return [true, '已跳转']
      } catch {
        // URL 读不到就继续轮询文案
      }
    }
    await clock.sleep(pollS)
  }
  return [false, '已提交未确认']
}

/** 成功词表判定（布尔版；阶段名版见 waitSuccessStage）。只读，不点任何东西。 */
export async function waitSuccess(
  page: AnyPage,
  words: readonly string[],
  timeoutS = 120,
  pollS = 2,
): Promise<boolean> {
  return (await waitSuccessStage(page, words, timeoutS, pollS))[0]
}

// ---------------------------------------------------------------- 风控
// 风控词表（小红书实测撞过；其他平台复用时按平台传入自己的词表）
export const RISK_WORDS: readonly string[] = [
  'Scan to verify', '发布失败，请稍后重试', '操作过于频繁', '请稍后再试',
]

/**
 * 检测平台风控弹窗/提示（可见文本口径，同 login_wall）。
 *
 * 撞上风控时**不能**自动重试——只会越撞越死。必须停下来让用户本人扫码。
 */
export async function riskHit(page: AnyPage, kws: readonly string[] = RISK_WORDS): Promise<boolean> {
  return visibleTextHit(page, kws)
}

/** 读遮罩浮层的几何与样式（display/opacity/宽高）——「遮罩还在不在」的判据。 */
export async function modalMask(
  page: AnyPage,
  sel = '.d-modal-mask, .d-modal-wrapper',
): Promise<Record<string, any> | null> {
  try {
    return await page.evaluate(`(sel) => {
            const m = document.querySelector(sel);
            if (!m) return null;
            const r = m.getBoundingClientRect();
            const cs = getComputedStyle(m);
            return {w: Math.round(r.width), h: Math.round(r.height),
                    disp: cs.display, opa: cs.opacity};
        }`, sel)
  } catch {
    return null
  }
}

export interface WaitRiskClearOpts {
  no?: number
  logDir: string
  limitMin?: number
  kws?: readonly string[]
  maskSel?: string
  hint?: string
  reset?: ((page: AnyPage) => Promise<boolean>) | null
}

/**
 * 等用户扫码。浏览器窗口保持打开，等风控解除再返回 True。
 *
 * 解除后**必须**确认遮罩真的没了——扫码后那层遮罩常常还在，文本没了但遮罩
 * 留着，不重置的话下一条必挂。
 * reset：平台自己的「回干净页」函数（如 xhs.resetPage），null 则只按 Esc。
 */
export async function waitRiskClear(page: AnyPage, opts: WaitRiskClearOpts): Promise<boolean> {
  const no = opts.no ?? 0
  const limitMin = opts.limitMin ?? 10
  const kws = opts.kws ?? RISK_WORDS
  const maskSel = opts.maskSel ?? '.d-modal-mask, .d-modal-wrapper'
  const hint = opts.hint ?? '完成扫码验证'
  const shot = join(opts.logDir, `risk-${pad2(no)}.png`)
  try {
    await page.screenshot({ path: shot })
  } catch {
    // 截图只是留证
  }
  console.log('\n🛑 撞上平台风控，需要你本人扫码验证')
  console.log(`   📸 ${shot}`)
  console.log(`   请在弹出的 Chrome 窗口里${hint}（最多等 ${limitMin} 分钟）…`)
  const deadline = clock.now() + limitMin * 60
  let cleared = false
  while (clock.now() < deadline) {
    await clock.sleep(6)
    if (!(await riskHit(page, kws))) {
      cleared = true
      break
    }
  }
  if (!cleared) {
    console.log('   ❌ 超时未解除')
    return false
  }
  console.log('   ✓ 风控文案已消失，检查遮罩…')
  const m = await modalMask(page, maskSel)
  if (m && m['disp'] !== 'none' && (m['w'] ?? 0) >= 50) {
    console.log(`   ⚠️ 遮罩仍在 ${JSON.stringify(m)}，强制重置`)
    await page.keyboard.press('Escape')
    await clock.sleep(1.5)
    if (opts.reset && !(await opts.reset(page))) {
      console.log('   ❌ 重置失败')
      return false
    }
  }
  console.log('   ✓ 风控已彻底解除')
  return true
}

// ---------------------------------------------------------------- 批量骨架
export type PublishOneFn = (
  page: AnyPage,
  t: Task,
  auto: boolean,
  opts: { logDir: string },
) => Promise<PubResult>

export interface RunTasksOpts {
  uploadUrl: string
  logDir: string
  betweenS?: number
  dryRun?: number
  resultJson?: string
}

/**
 * 批量循环骨架：单条异常不拖垮整批 + 防风控节流（**写在循环内**）。
 *
 * - 每条 try/catch：一条挂掉只记「异常」，异常后强制回干净投稿页
 *   （脏状态会跨条污染——第 5 条编辑器里躺着第 3 条内容的教训）；
 * - 关键节点前后截图：pre/post 各一张 + 异常现场 crash-*，全留证；
 * - result 记录逐条落 JSON，可回读复核；
 * - **节流在循环内**（已核实缺陷①修复）：原 xhs 版「每条之间歇 35s」写在
 *   循环外，整批只睡最后一次。这里每条之间都睡 between_s（最后一条后不睡）。
 */
export async function runTasks(
  page: AnyPage,
  tasks: readonly Task[],
  publishOne: PublishOneFn,
  opts: RunTasksOpts,
): Promise<PubResult[]> {
  const betweenS = opts.betweenS ?? 35
  const dryRun = opts.dryRun ?? 0
  const resultJson = opts.resultJson ?? 'publish-result.json'
  const logDir = opts.logDir
  mkdirSync(logDir, { recursive: true })
  const results: PubResult[] = []
  const n = tasks.length
  for (let idx = 0; idx < n; idx++) {
    const t = tasks[idx]!
    // --dry-run N：前 N 条干跑（与 manifestArgs 的帮助文本一致）。
    // 栽过的坑：v1 写成 t["no"] == dry_run——只有第 N 号干跑、其余照常真发，
    // 操作者以为在演练，实际剩下全部发到真实账号。
    const auto = !(dryRun && t['no'] <= dryRun)
    try {
      try {
        await page.screenshot({ path: join(logDir, `pre-${pad2(t['no'])}.png`) })
      } catch {
        // 截图失败不拦发布
      }
      results.push(await publishOne(page, t, auto, { logDir }))
    } catch (e) {
      // 一条挂掉不能带走整批
      console.log(`\n💥 [${pad2(t['no'])}] ${t['lang']} 异常 ${errName(e)}: ${clip(errStr(e), 120)}`)
      try {
        await page.screenshot({ path: join(logDir, `crash-${pad2(t['no'])}.png`) })
      } catch {
        // 截图失败不拦收尾
      }
      results.push({ no: t['no'], lang: t['lang'], ok: false, stage: `异常 ${errName(e)}` })
      // 回投稿页，避免脏状态污染下一条
      try {
        await page.goto(opts.uploadUrl, { waitUntil: 'domcontentloaded', timeout: 60000 })
        await clock.sleep(5)
      } catch {
        // 回不去也只能如实继续
      }
    }
    try {
      await page.screenshot({ path: join(logDir, `post-${pad2(t['no'])}.png`) })
    } catch {
      // 截图失败不拦收尾
    }
    // 防风控节流：每条之间都歇（原版写在循环外只睡一次，缺陷①）
    if (idx < n - 1) {
      console.log(`\n⏸ 歇 ${betweenS}s 再发下一条（防风控）…`)
      await clock.sleep(betweenS)
    }
  }
  const out = join(logDir, resultJson)
  writeFileSync(out, `${JSON.stringify(results, null, 1)}\n`, 'utf-8')
  console.log(`\n明细写入 ${out}`)
  return results
}

/** 汇总打印 + 退出码（全成才算成，失败判定一律看退出码）。 */
export function summarize(results: readonly PubResult[], label = ''): number {
  console.log(label ? `\n===== ${label}发布汇总 =====` : '\n===== 发布汇总 =====')
  const done = results.filter((r) => r['ok'])
  console.log(`  成功 ${done.length} / ${results.length}`)
  for (const r of results) {
    const extra = r['cover'] ? ` · 封面${r['cover']}` : ''
    console.log(`  ${r['ok'] ? '✅' : '❌'} [${pad2(r['no'])}] ${String(r['lang']).padEnd(8)} ${r['stage']}${extra}`)
  }
  return done.length === results.length ? 0 : 1
}

// ---------------------------------------------------------------- 任务过滤
/**
 * `--only 1,7` / `--from 3` 过滤（纪律 12：筛空当场报错，不许静默跑 0 条）。
 */
export function filterTasks(tasks: readonly Task[], only: string | null = null, frm: number | null = null): Task[] {
  let out = [...tasks]
  if (only) {
    const keep = new Set(only.split(',').filter((x) => x.trim()).map((x) => Number(x)))
    out = out.filter((t) => keep.has(t['no']))
  } else if (frm) {
    out = out.filter((t) => t['no'] >= frm)
  }
  if (!out.length) {
    throw new FeuilleError(
      `筛选后任务为空（only=${pyRepr(only)}, from=${pyRepr(frm)}）——`
      + `按纪律 12 当场报错，不静默跑 0 条。原始任务数 ${tasks.length}。`)
  }
  return out
}

// ---------------------------------------------------------------- CLI 适配层
export interface ManifestArgs {
  manifest: string
  logDir: string
  only: string | null
  frm: number | null
  dryRun: number
  headless: boolean
  /** bilibili 叶子加 --subs-dir（参数表公共部分 + 平台差异项，约定见 manifestArgs）。 */
  subsDir: string | null
}

export type ParsedManifestArgs = ManifestArgs | { rc: number }

/**
 * 三个发布器 CLI 叶子的公共参数表（manifest_argparser 的手写移植；
 * 平台差异项由调用方传 extra 再加）。
 *
 * 参数表长一个样是**约定**不是巧合（清单格式三平台同构），各抄一份只会漂移出
 * 三个「文档说 a、代码收 b」的版本。缺必填 / 坏 int → usage 到 stderr +
 * 返回 {rc: 2}（argparse 退出码 2 口径）；-h → usage 到 stdout + {rc: 0}。
 */
export function manifestArgs(
  argv: readonly string[],
  prog: string,
  extra: { subsDir?: boolean } = {},
): ParsedManifestArgs {
  const valueFlags = ['--log-dir', '--only', '--frm', '--dry-run']
  if (extra.subsDir) valueFlags.push('--subs-dir')
  const usage =
    `usage: ${prog} [-h] --log-dir LOG_DIR [--only ONLY] [--frm FRM]`
    + `${extra.subsDir ? ' [--subs-dir SUBS_DIR]' : ''} [--dry-run N] [--headless] manifest`
  const fail = (why: string): { rc: 2 } => {
    process.stderr.write(`${usage}\n${prog}: error: ${why}\n`)
    return { rc: 2 }
  }
  const m = new Map<string, string>()
  let headless = false
  const positional: string[] = []
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!
    if (a === '-h' || a === '--help') {
      process.stdout.write(`${usage}\n`)
      return { rc: 0 }
    }
    if (a === '--headless') {
      headless = true
      continue
    }
    let key = a
    let val: string | undefined
    const eq = a.startsWith('--') ? a.indexOf('=') : -1
    if (eq !== -1) {
      key = a.slice(0, eq)
      val = a.slice(eq + 1)
    }
    if (valueFlags.includes(key)) {
      if (val === undefined) {
        if (i + 1 >= argv.length) return fail(`${key}: expected one argument`)
        val = argv[++i]!
      }
      // argparse 后出现的同名参数生效（last-wins）
      m.set(key, val)
    } else if (key.startsWith('--')) {
      return fail(`unrecognized arguments: ${key}`)
    } else {
      positional.push(a)
    }
  }
  if (!positional.length) return fail('the following arguments are required: manifest')
  if (positional.length > 1) return fail(`unrecognized arguments: ${positional.slice(1).join(' ')}`)
  if (!m.has('--log-dir')) return fail('the following arguments are required: --log-dir')
  // argparse type=int：坏值 → usage + 退出码 2（Number('') 会给 0，必须显式挡掉）
  const parseIntStrict = (raw: string | undefined, flag: string): number | { rc: 2 } | null => {
    if (raw === undefined) return null
    const v = Number(raw)
    if (raw.trim() === '' || !Number.isInteger(v)) return fail(`argument ${flag}: invalid int value: '${raw}'`)
    return v
  }
  const frm = parseIntStrict(m.get('--frm'), '--frm')
  if (frm !== null && typeof frm === 'object') return frm
  const dryRun = parseIntStrict(m.get('--dry-run'), '--dry-run')
  if (typeof dryRun === 'object' && dryRun !== null) return dryRun
  return {
    manifest: positional[0]!,
    logDir: m.get('--log-dir')!,
    only: m.get('--only') ?? null,
    frm,
    dryRun: dryRun ?? 0,
    headless,
    subsDir: m.get('--subs-dir') ?? null,
  }
}

/**
 * 从 build_manifest 的产物里取平台段。
 *
 * 形状不对要说清缺哪段、现有哪些键，而不是抛一个裸 TypeError 让人猜
 * 清单到底是谁生成的（FAIL 要能被修，门禁哲学同 filterTasks）。
 */
export function manifestTasks(manifest: string, platformKey: string): Task[] {
  let doc: any
  try {
    doc = JSON.parse(readFileSync(manifest, 'utf-8'))
  } catch (e) {
    throw new FeuilleError(`${manifest} 解析不了：${errStr(e)}`)
  }
  const isDict = doc !== null && typeof doc === 'object' && !Array.isArray(doc)
  const tasks = isDict ? doc[platformKey] : undefined
  if (!Array.isArray(tasks)) {
    const got = isDict ? pyList(Object.keys(doc)) : pyTypeName(doc)
    throw new FeuilleError(
      `${manifest} 缺 ${pyRepr(platformKey)} 段——确认这是 `
      + `feuille.manifest.build_manifest 的产物（顶层键：${got}）`)
  }
  return tasks
}
