// douyin.ts — 抖音发布器（⑨）：上传 → 标题/正文/话题 → 发布；封面**后补**
// （publish/douyin.py 的 TS 移植）。
//
// **封面为什么后补**：上传流程的封面面板喂不准——`input[0]` 挂在 `list-*`
// （生成参考图）下，正确入口是 `selectArea-*`；确认键上传层是「保存」、
// 编辑层是「完成」。曾整批封面全发成平台默认帧而脚本自报全部成功。
// 所以发布是两步：先发视频（publish），再走已验证的编辑流程补封面（fixCovers）。
//
// 使用契约：
// - tasks 是 `manifest.build_manifest` 的产物（no/lang/locale/title/body/tags/video/cover）；
//   profile 默认 `base.PROFILES['douyin']`；截图与 result JSON 全部落 logDir。
// - 修改预算（纪律 20）：抖音每个作品**最多修改 5 次，补封面算 1 次**——
//   批量补之前先单条验证落库（fixCovers 只筛要补的条目，不盲目全跑）。
// - 补完必须用 veriflive.verify 回查缩略图确认有文字。
import { existsSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'

import * as base from './base.js'
import * as clock from './clock.js'

export const UPLOAD_URL = 'https://creator.douyin.com/creator-micro/content/upload'
export const MANAGE_URL = 'https://creator.douyin.com/creator-micro/content/manage'

// 抖音登录墙面板文案（实测词表）
export const DOUYIN_WALL: readonly string[] = ['扫码登录', '验证码登录', '密码登录', '手机号登录']

// ── 登录 ──────────────────────────────────────────────────────────────

/** 确保落到上传页。若在登录墙，等用户扫码。 */
export async function ensureLogin(page: base.AnyPage, waitMin = 10): Promise<boolean> {
  await page.goto(UPLOAD_URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await clock.sleep(4)

  if (await base.loginWall(page, DOUYIN_WALL)) {
    console.log('   ⚠️ 抖音未登录。请在弹出的 Chrome 窗口扫码。')
    console.log(`      等待中（最多 ${waitMin} 分钟）…`)
    if (!(await base.waitLogin(page, waitMin * 60, { kws: DOUYIN_WALL }))) {
      console.log('      ❌ 超时未登录，中止。')
      return false
    }
    await clock.sleep(3)
  }

  // 登录后如果被踢回首页，再去一次上传页
  const suffix = UPLOAD_URL.split('/creator-micro').slice(-1)[0] ?? ''
  if (!page.url.includes(suffix) && !page.url.includes('upload')) {
    await page.goto(UPLOAD_URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await clock.sleep(3)
  }
  return !(await base.loginWall(page, DOUYIN_WALL))
}

// ── 页面杂务 ──────────────────────────────────────────────────────────

export async function cleanDraftBanner(page: base.AnyPage): Promise<void> {
  try {
    const btn = page.locator("button:has-text('放弃'), a:has-text('放弃'), span:has-text('放弃')").first()
    if (await base.visibleWithin(btn, 1500)) {
      await btn.click()
      console.log('      ✓ 已清理上次未发布的草稿')
      await clock.sleep(1.5)
      const conf = page.locator(".semi-modal button:has-text('确定'), .semi-modal button:has-text('放弃')").first()
      if (await base.visibleWithin(conf, 1500)) {
        await conf.click()
        await clock.sleep(1)
      }
    }
  } catch {
    // 草稿横幅不存在是常态
  }
}

/**
 * 清掉盖版面上的层层弹窗。返回是否点掉了什么。
 *
 * 踩过的坑：抖音上传封面后会叠一层「设置横封面获得更多流量」，
 * 按钮是「暂不设置 / 设置横封面」，既不含「完成」也不含「确定」，
 * 原来的 dismiss 完全漏掉，脚本却照样往下报成功。
 * 我们发的是 9:16 竖封面，没有横版可设 → 一律选「暂不设置」。
 */
export async function dismissCoverModal(page: base.AnyPage): Promise<boolean> {
  let clicked = false
  // 1) 横封面推荐层 —— 必须选「暂不设置」
  for (const sel of ["button:has-text('暂不设置')", ".semi-modal button:has-text('暂不设置')"]) {
    try {
      const b = page.locator(sel).first()
      if (await base.visibleWithin(b, 800)) {
        await b.click()
        console.log('      ✓ 已关闭「横封面推荐」弹窗（选暂不设置）')
        clicked = true
        await clock.sleep(1.0)
        break
      }
    } catch {
      continue
    }
  }

  // 2) 封面检测 / 截取类弹窗
  for (const sel of [
    "div[role='dialog'] button:has-text('完成')",
    ".semi-modal button:has-text('完成')",
    ".semi-modal button:has-text('确定')",
    "div[role='dialog'] button:has-text('确定')",
  ]) {
    try {
      const b = page.locator(sel).first()
      if (await base.visibleWithin(b, 800)) {
        await b.click()
        console.log('      ✓ 已关闭封面弹窗')
        clicked = true
        await clock.sleep(0.8)
        break
      }
    } catch {
      continue
    }
  }
  return clicked
}

/** 列出当前仍然可见、且会挡住发布按钮的弹窗。用于诚实报状态。 */
export async function blockingModals(page: base.AnyPage): Promise<string[]> {
  const out: string[] = []
  for (const [sel, name] of [
    ["button:has-text('暂不设置')", '横封面推荐'],
    ["div[role='dialog'] button:has-text('完成')", '封面截取弹窗'],
    [".semi-modal button:has-text('确定')", '确认弹窗'],
    ["button:has-text('确认发布')", '确认发布弹窗'],
  ] as const) {
    try {
      if (await base.visibleWithin(page.locator(sel).first(), 600)) out.push(name)
    } catch {
      continue
    }
  }
  return out
}

// ── 单条发布 ──────────────────────────────────────────────────────────

export async function publishOne(
  page: base.AnyPage,
  t: base.Task,
  auto: boolean,
  opts: { logDir: string },
): Promise<base.PubResult> {
  const vid = t['video']
  const cov = t['cover']
  const logDir = opts.logDir
  const res: base.PubResult = { no: t['no'], lang: t['lang'], ok: false, stage: '', cover: false }

  console.log(`\n🚀 [${base.pad2(t['no'])}] ${t['lang']}  ${basename(vid)}`)
  console.log(`   标题: ${t['title']}`)

  if (!existsSync(vid)) {
    console.log('   ❌ 视频文件不存在')
    res['stage'] = '素材缺失'
    return res
  }

  if (!page.url.includes('upload')) {
    await page.goto(UPLOAD_URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await clock.sleep(3)
  }
  await cleanDraftBanner(page)

  await page.locator('input[type="file"]').first().setInputFiles(vid)
  console.log('   ✓ 已送入上传通道，等待解析…')

  const titleBox = page.locator("input[placeholder*='标题'], input[placeholder*='作品标题']").first()
  // 只认正文编辑器，严格避开封面上传框与拖拽区
  const descBox = page.locator(
    "div.notranslate[contenteditable='true'], div.editor-kit-editor, "
    + "div[data-placeholder*='简介'], "
    + "div[contenteditable='true']:not([class*='cover']):not([class*='upload']):not([class*='zone'])",
  ).first()

  let ready = false
  for (let i = 0; i < 40; i++) {
    try {
      if ((await base.visibleWithin(titleBox, 800)) || (await base.visibleWithin(descBox, 800))) {
        ready = true
        break
      }
    } catch {
      // 按原样镜像：单轮探测异常继续等
    }
    await clock.sleep(1)
  }
  if (!ready) {
    res['stage'] = '编辑器未就绪'
    console.log('   ❌ 编辑器未就绪')
    return res
  }

  // 标题（纪律 19：录不进标题 = 带病发布，中止本条）
  if (!(await base.fillTitle(page, titleBox, t['title'], { limit: 30 }))) {
    res['stage'] = '标题未录入（已中止发布）'
    console.log('   🛑 标题没录进去 → 中止本条，不点发布')
    return res
  }

  // 正文 + 话题胶囊（录不进 = 带病发布，纪律 19）
  let descReady = false
  try {
    descReady = await base.visibleWithin(descBox, 3000)
  } catch {
    descReady = false
  }
  if (!descReady) {
    res['stage'] = '正文框未出现（已中止发布）'
    console.log('   🛑 没找到正文框 → 中止本条，不点发布')
    return res
  }
  if (!(await base.fillBody(page, descBox, t['body'], { tags: t['tags'], pause: 0.35 }))) {
    res['stage'] = '正文未录入（已中止发布）'
    console.log('   🛑 正文没录进去 → 中止本条，不点发布')
    return res
  }

  await dismissCoverModal(page)

  // ── 封面不在发布流程里做，发布后单独补 ─────────────────────────
  // 上传流程的封面面板喂不准：file input[0] 挂在 list-*（生成参考图）下，
  // 正确入口是 selectArea-* 下的那个；确认键在上传层是「保存」、
  // 在编辑层是「完成」。曾就这么把 12 条封面全发成
  // 平台默认首帧的，而脚本自报 12/12 成功。
  //
  // 改用已验证的编辑流程补封面：fixCovers(tasks, only=本条)。
  // 该流程 selectArea-* + 「完成」，逐条比对缩略图，落库可查。
  res['cover'] = false
  res['cover_pending'] = cov
  console.log('   ℹ️ 封面留到发布后用 fix_covers 补（编辑流程已验证）')

  // 把「设置封面」那一块单独截下来，便于事后核对到底用没用我们那张
  try {
    let sec: any = null
    for (const sel of ['text=设置封面', "div:has-text('设置封面')"]) {
      const loc = page.locator(sel).first()
      if (await base.visibleWithin(loc, 1500)) {
        sec = loc
        break
      }
    }
    if (sec !== null) {
      await sec.scrollIntoViewIfNeeded()
      await clock.sleep(1.2)
      const box = await sec.boundingBox()
      if (box) {
        await page.screenshot({
          path: join(logDir, `covershot-${base.pad2(t['no'])}.png`),
          clip: {
            x: Math.max(0, box['x'] - 10),
            y: Math.max(0, box['y'] - 10),
            width: Math.min(1400, box['width'] + 20),
            height: Math.min(760, box['height'] + 20),
          },
        })
        console.log(`      📷 封面区截图 covershot-${base.pad2(t['no'])}.png`)
      }
    }
  } catch (e) {
    console.log(`      （封面区截图跳过：${base.errName(e)}）`)
  }

  // 封面由发布后的 fixCovers 补，补完必须用 veriflive.verify 回查
  // 缩略图确认有文字（PUBLISH-RULES.md 规则 1/3）。
  // 这里不阻断发布，但要如实标成「封面待补」，不许算作完成。

  // 等转码完成（发布按钮解禁）
  console.log('   ⏳ 等待上传与转码…')
  let ok = false
  for (let i = 0; i < 150; i++) {
    await dismissCoverModal(page)
    try {
      const b = await base.findPublishButton(page)
      if (b !== null) {
        const disabled =
          (await b.getAttribute('disabled')) !== null
          || ((await b.getAttribute('class')) ?? '').includes('disabled')
        if (!disabled) {
          ok = true
          console.log('   ✓ 转码完成，真正的发布按钮已解禁')
          break
        }
      }
    } catch {
      // 按原样镜像：探测异常继续等
    }
    await clock.sleep(1)
  }
  if (!ok) {
    res['stage'] = '转码超时'
    console.log('   ❌ 转码等待超时')
    return res
  }

  if (!auto) {
    // 先把残留弹窗清干净，再拍能看清标题/正文的图
    for (let i = 0; i < 3; i++) {
      if (!(await dismissCoverModal(page))) break
    }
    try {
      await page.mouse.wheel(0, 600)
      await clock.sleep(1)
      await titleBox.scrollIntoViewIfNeeded()
      await clock.sleep(0.6)
    } catch {
      // 滚不动就只拍现状
    }
    return base.dryRunStop(page, res, {
      logDir,
      shotName: `dryrun-douyin-${base.pad2(t['no'])}.png`,
      blocking: () => blockingModals(page),
    })
  }

  // 点发布
  try {
    for (let i = 0; i < 3; i++) {
      if (!(await dismissCoverModal(page))) break
    }
    const left = await blockingModals(page)
    if (left.length) {
      res['stage'] = `发布前仍有弹窗 ${base.pyReprList(left)}`
      console.log(`   ❌ 发布前仍有弹窗挡着，不点发布：${base.pyReprList(left)}`)
      return res
    }
    await clock.sleep(1.2)

    const b = await base.findPublishButton(page)
    if (b === null) {
      res['stage'] = '找不到真正的发布按钮'
      console.log('   ❌ 找不到文本精确为「发布」的主按钮，拒绝乱点')
      return res
    }
    await b.scrollIntoViewIfNeeded()
    await clock.sleep(0.4)

    // 点之前拍一张，便于事后对照
    const pre = join(logDir, `prepublish-${base.pad2(t['no'])}.png`)
    try {
      await page.screenshot({ path: pre })
    } catch {
      // 截图只是留证
    }

    await b.click()
    console.log('   ✅ 已点击【发布】')
    await clock.sleep(3)

    // 点之后立刻拍一张 —— 上一版就是缺这一步，才把「点了没生效」当成成功
    const post = join(logDir, `postpublish-${base.pad2(t['no'])}.png`)
    try {
      await page.screenshot({ path: post })
    } catch {
      // 截图只是留证
    }

    // 把点击后页面上的可见提示全抓出来，失败时才有线索
    try {
      const tip = await page.innerText('body', { timeout: 8000 })
      const marks = [
        '作品已发布', '发布已完成', '请填写', '请输入', '不能为空',
        '封面检测', '审核中', '存在风险', '请确认', '声明',
      ].filter((x) => tip.includes(x))
      if (marks.length) console.log(`   ℹ️ 页面提示关键词：${base.pyReprList(marks)}`)
    } catch {
      // 提示抓不到不拦流程
    }

    for (const sel of [
      ".semi-modal button:has-text('确认发布')",
      ".semi-modal button:has-text('确定')",
      ".semi-modal button:has-text('确认')",
      "button:has-text('确认发布')",
    ]) {
      try {
        const c = page.locator(sel).first()
        if (await base.visibleWithin(c, 1500)) {
          await c.click()
          console.log('   ✓ 已确认二次弹窗')
          break
        }
      } catch {
        continue
      }
    }
  } catch (e) {
    res['stage'] = `点击发布失败:${base.errStr(e)}`
    console.log(`   ❌ 点击发布失败：${base.errStr(e)}`)
    return res
  }

  // 等确认
  const deadline = clock.now() + 180
  while (clock.now() < deadline) {
    if (page.url.includes('content/manage')) {
      res['ok'] = true
      res['stage'] = !res['cover'] ? '已发布·封面待补' : '已发布'
      console.log('   ✅ 发布成功（已跳转作品管理）')
      if (!res['cover']) {
        console.log(`   ⚠️ 封面还没补：${res['cover_pending'] ?? ''}`)
        console.log('      补完：fix_covers(tasks, only=本条)，再用 veriflive.verify 回查')
      }
      return res
    }
    try {
      if (
        (await page.locator(
          'text=发布成功, text=作品已发布, text=发布已完成, .semi-toast-success',
        ).count()) > 0
      ) {
        res['ok'] = true
        res['stage'] = !res['cover'] ? '已发布·封面待补' : '已发布'
        console.log('   ✅ 检测到【发布成功】')
        if (!res['cover']) console.log(`   ⚠️ 封面还没补：${res['cover_pending'] ?? ''}`)
        await clock.sleep(3)
        return res
      }
    } catch {
      // 探测异常继续轮询
    }
    await clock.sleep(2)
  }

  res['stage'] = '已点击但未确认'
  const fail = join(logDir, `publish-fail-${base.pad2(t['no'])}.png`)
  try {
    await page.screenshot({ path: fail })
    console.log(`   📷 失败现场截图 ${fail}`)
  } catch {
    // 截图只是留证
  }
  try {
    console.log(`   当前 URL: ${page.url}`)
  } catch {
    // URL 读不到也如实收尾
  }
  console.log('   ⚠️ 已点发布但未检测到成功提示，请人工核实这一条')
  return res
}

/** --list：打印待发布条目。 */
export function listTasks(tasks: readonly base.Task[]): void {
  for (const t of tasks) {
    console.log(
      `  ${base.pad2(t['no'])} ${String(t['lang']).padEnd(8)} `
      + `${base.clip(t['title'], 34).padEnd(36)} ${t['tags'].length}话题  ${basename(t['video'])}`,
    )
  }
}

export interface PublishOpts {
  profileDir?: string | null
  logDir: string
  only?: string | null
  frm?: number | null
  dryRun?: number
  headless?: boolean
}

/** 批量发布（骨架在 base.runTasks：异常隔离 + 循环内节流 + result JSON）。 */
export async function publish(tasks: readonly base.Task[], opts: PublishOpts): Promise<number> {
  const filtered = base.filterTasks(tasks, opts.only ?? null, opts.frm ?? null)
  const profileDir = opts.profileDir || base.profileDir('douyin')
  console.log(`待发布 ${filtered.length} 条 · profile ${profileDir}`)

  let loginOk = true
  let results: base.PubResult[] = []
  await base.launch(
    profileDir,
    { headless: opts.headless ?? false, viewport: { width: 1440, height: 900 } },
    async (_ctx, page) => {
      if (!(await ensureLogin(page))) {
        loginOk = false
        return
      }
      console.log('✅ 抖音创作者后台就绪\n')
      results = await base.runTasks(page, filtered, publishOne, {
        uploadUrl: UPLOAD_URL,
        logDir: opts.logDir,
        betweenS: 3,
        dryRun: opts.dryRun ?? 0,
        resultJson: 'publish-douyin-result.json',
      })
    },
  )
  if (!loginOk) return 1
  return base.summarize(results, '抖音')
}

// ── 封面后补（编辑流程，已验证） ────────────────────────────────────────

/** 打开封面弹窗 → 点上传封面 → 喂文件 → 完成。返回是否成功。 */
export async function setCover(
  page: base.AnyPage,
  coverPath: string,
  tag: string,
  opts: { logDir: string },
): Promise<boolean> {
  const logDir = opts.logDir
  let lbl = page.getByText('竖封面3:4', { exact: true }).first()
  if (!(await base.visibleWithin(lbl, 4000))) {
    lbl = page.getByText('竖封面 3:4', { exact: true }).first()
  }
  await lbl.scrollIntoViewIfNeeded()
  await clock.sleep(1.2)
  const b = await lbl.boundingBox()
  if (!b) {
    console.log('   ⚠️ 找不到竖封面标签')
    return false
  }
  await page.mouse.click(b['x'] + b['width'] / 2, b['y'] - 80)
  await clock.sleep(4)

  // 弹窗里有两组 file input，必须按祖先 class 区分：
  //   list-*   → 生成参考图（喂这里封面不会生效，栽过）
  //   selectArea-* → 上传封面（正确入口）
  const upIn = page.locator("div[class*='selectArea'] input[type='file']")
  const nUp = await upIn.count()
  console.log(`   selectArea 内 file input: ${nUp}`)
  if (nUp === 0) {
    await page.screenshot({ path: join(logDir, `covfail-${tag}-noselect.png`) })
    console.log('   ⚠️ 没找到上传封面的 input')
    return false
  }
  try {
    // 优先 hidden-input（非 replace），它是首次上传口
    await upIn.first().setInputFiles(coverPath, { timeout: 15000 })
    console.log('   ✓ 已喂给 selectArea（上传封面）')
  } catch (e) {
    console.log(`   ⚠️ 喂 selectArea 失败（${base.errName(e)}）`)
    return false
  }

  await clock.sleep(6)
  await page.screenshot({ path: join(logDir, `covdbg-${tag}-uploaded.png`) })

  // 裁切框里必须看得见文字：主编辑区不该还是纯叶子
  try {
    await page.getByText('完成', { exact: true }).first().click()
    console.log('   · 已点「完成」')
    await clock.sleep(4)
  } catch {
    // 完成键不在就不点，留给调用方判现场
  }

  await page.screenshot({ path: join(logDir, `covdbg-${tag}-done.png`) })
  return true
}

export async function fixOne(
  page: base.AnyPage,
  task: base.Task,
  opts: { searchKw: string; logDir: string },
): Promise<boolean> {
  const logDir = opts.logDir
  const lang = task['lang']
  console.log(`\n🔧 [${base.pad2(task['no'])}] ${lang}`)
  await page.goto(MANAGE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await clock.sleep(7)
  const box = page.locator("input[placeholder*='搜索']").first()
  await box.click()
  await box.fill(opts.searchKw)
  await page.keyboard.press('Enter')
  await clock.sleep(5)

  // 定位目标条目：按「编辑作品」按钮的纵向顺序，与同位置的标题文本对齐。
  // 每张卡片是一行：封面 | 标题+数据 | 操作区(编辑/设置权限/删除)
  //
  // ⚠️ 原定位器写死成 get_by_text(f"「{search_kw}」的")
  // ——即「**「X」的Y版**」这种标题格式。标题一旦不含该结构
  // → 匹配到 0 个，整条卡在「没找到」。
  // 这与 collections 的硬编码是同一类病：**把某个项目的文案格式当成通用格式**。
  // 现在直接用**清单里的真实标题**做前缀匹配，与文案格式无关。
  const eds = page.getByText('编辑作品', { exact: false })
  const want: string = task['title'] // 以文案里的完整标题为准
  const ne = await eds.count()
  let idx: number | null = null
  // 候选标题 = 编辑按钮所在行（xpath 上两级容器）的文本。
  // ⚠️ 不做「全页找标题 → 按出现顺序对齐第 j 个编辑按钮」的退化定位：
  // 位置对齐只是假设，标题一旦在提示条 / 置顶卡等处也出现，就会点错作品的
  // 编辑按钮——白耗修改配额（抖音每作品 5 次，纪律 19/20）。行容器对不上
  // 就按「没找到」中止，人工看行文本再修容器层级，不盲配。
  const rows: Array<[number, string]> = []
  for (let i = 0; i < ne; i++) {
    try {
      const rowBox = eds.nth(i).locator('xpath=../..')
      rows.push([i, ((await rowBox.innerText()) ?? '').replace(/\n/g, ' ')])
    } catch {
      rows.push([i, ''])
    }
  }
  for (const [i, rowText] of rows) {
    if (rowText.includes(base.clip(want, 10))) {
      idx = i
      console.log(`   匹配第 ${i} 行：${base.clip(rowText, 44)}`)
      break
    }
  }

  if (idx === null) {
    console.log(`   ⚠️ 没找到「${base.clip(want, 20)}…」那条（页面 ${ne} 个编辑按钮）`)
    for (const [, rowText] of rows.slice(0, 8)) {
      if (rowText) console.log('      -', base.clip(rowText, 56))
    }
    return false
  }

  await eds.nth(idx).click()
  await clock.sleep(7)
  console.log(`   编辑页: ${page.url}`)

  const ok = await setCover(page, task['cover'], base.pad2(task['no']), { logDir })
  if (ok) {
    try {
      await page.getByText('提交修改', { exact: true }).first().click()
      console.log('   · 已点「提交修改」')
      await clock.sleep(7)
      await page.screenshot({ path: join(logDir, `covdbg-${base.pad2(task['no'])}-submitted.png`) })
    } catch (e) {
      console.log(`   ⚠️ 提交修改失败：${base.errStr(e)}`)
    }
  }
  return ok
}

export interface FixCoversOpts {
  searchKw: string
  logDir: string
  profileDir?: string | null
  only?: string | null
  lang?: string | null
}

/**
 * 发布后补封面（编辑流程：selectArea input + 「完成」）。
 *
 * 修改预算（纪律 20）：抖音每个作品**最多修改 5 次，补封面算 1 次**——
 * 批量补之前先只筛 1–2 条验证落库（only 参数就是干这个的），
 * 补完用 veriflive.verify 回查缩略图有文字才算数。
 */
export async function fixCovers(tasks: readonly base.Task[], opts: FixCoversOpts): Promise<number> {
  let list = [...tasks]
  if (opts.lang) list = list.filter((t) => t['lang'] === opts.lang)
  list = base.filterTasks(list, opts.only ?? null, null)
  const logDir = opts.logDir
  const profileDir = opts.profileDir || base.profileDir('douyin')

  const results: Array<Record<string, any>> = []
  await base.launch(profileDir, { viewport: { width: 1700, height: 1100 } }, async (_ctx, page) => {
    for (const t of list) {
      try {
        results.push({
          no: t['no'],
          lang: t['lang'],
          ok: await fixOne(page, t, { searchKw: opts.searchKw, logDir }),
        })
      } catch (e) {
        console.log(`   ❌ 异常 ${base.errName(e)}: ${base.errStr(e)}`)
        results.push({ no: t['no'], lang: t['lang'], ok: false })
      }
      await clock.sleep(4)
    }
  })

  console.log('\n===== 封面修正汇总 =====')
  for (const r of results) {
    console.log(`  ${r['ok'] ? '✅' : '❌'} [${base.pad2(r['no'])}] ${r['lang']}`)
  }
  const out = join(logDir, 'fix-douyin-covers-result.json')
  writeFileSync(out, `${JSON.stringify(results, null, 1)}\n`, 'utf-8')
  console.log(`明细写入 ${out}`)
  return results.every((r) => r['ok']) ? 0 : 1
}

// ── CLI 适配层（CLI 路由叶子；业务在 publish()，这里只接线） ─────────

/**
 * CLI 路由入口：`feuille publish douyin <manifest.json> --log-dir D`。
 *
 * manifest.json = plans 契约经 `manifest.build_manifest` 落盘的清单，
 * 本入口取其中的 "douyin" 段作为 tasks。
 */
export async function main(argv: string[]): Promise<number> {
  const a = base.manifestArgs(argv, 'feuille publish douyin')
  if ('rc' in a) return a.rc
  const tasks = base.manifestTasks(a.manifest, 'douyin')
  return publish(tasks, {
    logDir: a.logDir,
    only: a.only,
    frm: a.frm,
    dryRun: a.dryRun,
    headless: a.headless,
  })
}
