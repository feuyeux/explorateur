// draft.ts —— 存草稿模式（填完存草稿就停，**不点发布**）。
//
// **为什么要有这个模式**：本工程的纪律是「发布永不自动」——真发布由人喊了才发。
// 但「填稿」与「发布」是两件事：传视频、选封面、填标题正文、传字幕这些步骤
// 可以在**不产生任何流量**的前提下完整跑一遍并留证，最后那一下「发布」由人按。
// 存草稿 = 这一轮跑批的终点（草稿躺在后台，人看一眼再发）。
//
// **fail-closed 是硬要求**：找不到存草稿键 → 放弃这一条、如实报失败，
// **绝不点发布键**。「找不到草稿键就退而求其次去点发布」是最坏的一种错——
// 不可撤销、真的发到线上了。本模块没有这个降级分支，也不许后来加。
//
// **不许靠猜**：草稿键的文本候选是**枚举**（按平台实测），不是「含『草稿』就点」——
// 「草稿箱」是列表页导航、「保存并发布」是另一个动作，子串匹配会点到它们。
// 匹配口径 = 可见文本**精确**等于候选之一（与 findPublishButton 同口径）。
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

import * as base from './base.js'
import * as clock from './clock.js'

// ── 浏览器侧全局（本包是 Node 包，tsconfig 的 lib 只有 ES2023，没有 DOM）──
// evaluate 的函数体**跑在浏览器上下文里**，但类型检查只认本包的 lib。
// 按 any 声明，只为让类型检查过；运行期由浏览器提供。
declare const document: any
// getComputedStyle 同理：它在**浏览器上下文**里跑（evaluate 的函数体），
// 但本包 tsconfig 的 lib 只有 ES2023、没有 DOM ⇒ 类型检查认不出来 ⇒ 显式声明。
declare const getComputedStyle: any

/** 各平台的草稿键候选（可见文本精确匹配，顺序即优先级）。 */
export const DRAFT_BTN_TEXTS: Record<string, readonly string[]> = {
  // 「暂存离开」是**实测**出来的抖音文案：2026-11-03 首次实跑，抖音投稿页的
  // 可见按钮是 ['作品发布','首页','AI分身','随变','世界书','造世界','AI工坊','0',
  // '《付费内容功能使用协议》','查看详情','发布','暂存离开']——**没有**「存草稿」。
  // 原来的候选表按字面猜，于是每一条都 fail-closed 放弃（行为正确，词表错）。
  douyin: ['存草稿', '保存草稿', '暂存离开', '暂存草稿'],
  // ⚠️ B站的真键是「**存草稿**」（实测 2026-11-03，DOM 探针：`<span class="submit-draft">`，
  // 在页面底部的 `.submit-container` 里）。
  // ⚠️ 旧注释说它「在投稿页可见按钮清单里」——**不实**：诊断用的按钮清单只查
  // `button,[role=button],.semi-button,.bcc-button,a`，而真键是 span ⇒ 清单里压根没有它，
  // 正是这份清单把人带偏了（看起来像「这个平台上没有草稿键」）。
  // 两个文案都留着——枚举不是猜测，多一个候选不改变行为，
  // 而漏掉真键会让每一条都 fail-closed 放弃。
  bilibili: ['存草稿', '保存草稿'],
}

/**
 * 存草稿成功的可见文案（判成功用，判不出就报「未确认」，不谎报成功）。
 *
 * ⚠️ B 站这一栏**实测没有任何 toast**：点完「存草稿」没有提示气泡，
 * 页面直接跳到草稿箱（`/platform/upload-manager/article?group=draft`），
 * 只在页面上留两行 tips（「部分草稿可能会过期，仅保存部分字段 草稿箱最多保存30个稿件」
 * 「暂不保存：卡片配置、章节配置等信息」）。⇒ B 站的真判据是 **URL 落地**
 * （见 DRAFT_LANDED_URLS），下面这些词只是退路。
 *
 * ⚠️ 2026-11-03 17:00 复核：抖音那一栏里的**泛用词**（「暂存成功」「已暂存」「保存成功」）
 * 是本轮假绿灯的来源——它们不点明「草稿」，而封面上传完、转码完成、封面保存都可能飘
 * 同族提示；**它们证明不了「这一条进了槽位」**。抖音实测唯一的落库信号是横幅
 * （见 douyin.DRAFT_LANDED_BANNER），所以这里只留**明写「草稿」**的词，
 * 泛用词一律不留（留着就是给假绿灯开门）。
 */
export const DRAFT_SUCCESS_WORDS: Record<string, readonly string[]> = {
  douyin: ['已保存草稿', '草稿保存成功', '存草稿成功'],
  bilibili: ['草稿保存成功', '已保存草稿', '存草稿成功', '保存成功'],
}

/**
 * 该平台的「未发布槽位」是不是**只有一个**（实测 2026-11-03）。
 *
 * 抖音：上传页顶部横幅写的是「你还有**上次未发布的**视频」（单数），
 * 点「继续编辑」回填出来是**空表单**（读不出是哪一条）⇒ 槽位单数。
 * ⇒ 批量存 N 条 = **后一条覆盖前一条**，跑完最多只剩 1 条。
 * ⇒ 且抖音 PC 端**没有任何草稿列表**（创作者中心只有「作品(N)」/「作品合集(N)」，
 * 网页端同样没有）⇒ 存完在任何一个界面上都**看不到**。
 *
 * 这个常量只用于**如实说明**（提示语 + 判据口径），不改变点键行为。
 */
export const DRAFT_SINGLE_SLOT: Record<string, boolean> = {
  douyin: true,
  bilibili: false,
}

/**
 * 存草稿后**应该到达**的 URL 片段（判「页面已经跳到草稿列表」用）。
 *
 * ⚠️ 方向：这里是**命中即算跳走**，不是「不再含投稿页片段」。
 * 写成「不再含 upload」的话，投稿页本来就不含它 ⇒ 每一条都当场判成功
 * （假绿灯）。命中式才守得住：没跳到草稿列表就不算跳走。
 *
 * ⚠️ 由此带出一条不变式：**这些片段不许出现在投稿页 URL 里**。
 * 投稿页 URL 形如 `.../content/upload`（抖音）、`.../platform/upload/video/frame`（B 站），
 * 都不含下面的片段——哪天真撞上了，这条判据就退化成「站在投稿页也判跳走」，
 * 又变回假绿灯。用例里有这条不变式的直接断言。
 */
export const DRAFT_LANDED_URLS: Record<string, readonly string[]> = {
  douyin: ['content/manage'],
  // B 站实测：点「存草稿」⇒ POST /x/vupre/web/draft/add ⇒ 页面跳到
  // `member.bilibili.com/platform/upload-manager/article?group=draft`（草稿箱）。
  // ⇒ `upload-manager` 就是 B 站的落库判据。
  bilibili: ['upload-manager', 'platform/home'],
}

/**
 * 发布键文本（只读）：草稿键绝不能与它重合。
 * 留着它是为了在代码里显式断言「点下去的绝不是发布键」——
 * 候选表与它不相交是事实，这个断言是那道事实的护栏。
 */
export const PUBLISH_BTN_TEXTS: readonly string[] = [
  '发布', '立即投稿', '提交稿件', '投稿', '发布视频',
]

/**
 * **会删掉东西**的按钮文本（存草稿模式绝不许点）。
 *
 * 抖音上传页的横幅「你还有上次未发布的视频，是否继续编辑？」上有个「放弃」键——
 * 它是**删除**上一条已存草稿的，不是「清掉提示」。
 * 存草稿模式下一条一条地存，每条开头点「放弃」= 把上一条刚存的稿子删掉
 * ⇒ 跑 4 条只剩 1 条，而且脚本还会自报「已存草稿」。
 *
 * 这里把它显式列出来，让「存草稿路径不许点它」成为可断言的事实。
 */
export const DESTRUCTIVE_BTN_TEXTS: readonly string[] = [
  '放弃', '删除', '丢弃', '清空', '删除作品',
]

export interface DraftBtn {
  el: any
  text: string
  y: number
}

/**
 * 元素像不像一个可点的按钮。
 *
 * 判据有两路：
 * ① 结构路：button / a / role=button|link / class 含 button|btn。
 * ② **光标形态路**：`getComputedStyle(el).cursor === 'pointer'`。
 *
 * ② 是为了 B 站的真键补的坑（2026-11-03 实测）：B 站投稿页的草稿键是
 * `<span class="submit-draft">存草稿</span>`——tag 是 span、role 空、
 * class 是 `submit-draft`（既不含 `button` 也不含 `btn`）⇒ ① 全不命中 ⇒
 * 候选被跳过 ⇒ 每一条都「找不到存草稿键」fail-closed 放弃。
 * 而它的 `cursor` 是浏览器算出来的 `pointer`（且 `pointer-events:auto`），
 * 这才是「它是个可点的东西」的**真实**证据，比猜 class 名可靠，也与框架无关
 * （实测该节点上没有 React props ⇒ 也不是靠 React 事件委托挂的）。
 */
async function looksClickable(el: any): Promise<boolean> {
  try {
    // ⚠️ 必须传真函数：JS 版 Playwright 的 evaluate 收到字符串时只把它**当表达式求值**，
    // `'(e) => {...}'` 求值出来是函数对象 → 不可序列化 → 返回 undefined。
    // 这里恒返回 undefined ⇒ 所有非 <button> 的候选全被误杀 ⇒ 真平台的
    // 「存草稿」键（多半是 div/span）永远找不到 ⇒ 每条都 fail-closed 放弃。
    return await el.evaluate((e: any) => {
      const t = (e.tagName || '').toLowerCase()
      if (t === 'button' || t === 'a') return true
      const r = e.getAttribute('role') || ''
      if (r === 'button' || r === 'link') return true
      const c = (typeof e.className === 'string' ? e.className : '').toLowerCase()
      if (c.includes('button') || c.includes('btn')) return true
      // 光标形态：浏览器算出来的 affordance（cursor 是继承属性 ⇒ 内层 span 也算）
      const cs = getComputedStyle(e)
      if (cs.cursor === 'pointer' && cs.pointerEvents !== 'none') return true
      return false
    })
  } catch {
    return false
  }
}

/**
 * 找草稿键。找不到返回 null——**调用方必须 fail-closed**（不许退回点发布）。
 *
 * 取**最靠下**的那个：页面底部是操作区，顶部常有同名导航。
 */
export async function findDraftButton(page: base.AnyPage, platform: string): Promise<DraftBtn | null> {
  const texts = DRAFT_BTN_TEXTS[platform] ?? []
  let best: DraftBtn | null = null
  for (const txt of texts) {
    const cands: any[] = []
    try {
      const bl = page.locator(`button:text-is("${txt}")`)
      const n = await bl.count()
      for (let i = 0; i < n; i++) cands.push(bl.nth(i))
    } catch {
      // 单个选择器失败继续下一个候选
    }
    try {
      const gl = page.getByText(txt, { exact: true })
      const n = await gl.count()
      for (let i = 0; i < n; i++) {
        const el = gl.nth(i)
        if (!(await looksClickable(el))) continue
        cands.push(el)
      }
    } catch {
      // 同上
    }
    for (const el of cands) {
      try {
        if (!(await base.visibleWithin(el, 400))) continue
        const inner = ((await el.innerText()) ?? '').trim()
        if (inner !== txt) continue
        if (PUBLISH_BTN_TEXTS.includes(inner)) continue
        // 草稿键不许是「会删东西」的键（「放弃」= 删上一条草稿）
        if (DESTRUCTIVE_BTN_TEXTS.includes(inner)) continue
        const box = await el.boundingBox()
        if (!box) continue
        if (best === null || box['y'] > best.y) best = { el, text: txt, y: box['y'] }
      } catch {
        continue
      }
    }
  }
  return best
}

/** 二次确认：**只有弹窗里出现「草稿」二字**才点它的确定/确认**。
 * 无条件的「点确定」会在别的弹窗上乱按（点掉一个「放弃草稿？」就白填了）。
 *
 * ⚠️ 抖音的草稿键是「暂存离开」，它的二次弹窗写的是「确认暂存离开？」——
 * 里面**没有**「草稿」二字。所以判据不能只认「草稿」；但也不能放宽成
 * 「有弹窗就点确定」——那会在「确认发布？」这种弹窗上按下去（不可撤销）。
 * 口径 = 弹窗里必须出现**存草稿语义**的词（草稿 / 暂存），别的弹窗一律不碰。
 */
async function confirmDraftModal(page: base.AnyPage): Promise<boolean> {
  for (const word of ['草稿', '暂存']) {
    for (const act of ['确定', '确认']) {
      for (const sel of [
        `.semi-modal:has-text('${word}') button:has-text('${act}')`,
        `div[role='dialog']:has-text('${word}') button:has-text('${act}')`,
      ]) {
        try {
          const b = page.locator(sel).first()
          if (await base.visibleWithin(b, 800)) {
            await b.click()
            console.log(`   ✓ 已确认「存草稿」二次弹窗（含「${word}」）`)
            await clock.sleep(1.5)
            return true
          }
        } catch {
          continue
        }
      }
    }
  }
  return false
}

/** 找不到草稿键时把页面上可见的按钮文本倒出来——留证 + 便于定位。 */
async function dumpButtons(page: base.AnyPage, logDir: string, tag: string): Promise<void> {
  try {
    // 同样必须传真函数（传字符串 ⇒ undefined ⇒ 这里再 .slice() 就是 TypeError，
    // 留证文件一个都写不出来）。
    //
    // ⚠️ 选择器必须**够宽**：原版只查 `button,[role=button],.semi-button,.bcc-button,a`，
    // 而 B 站的真键是 `<span class="submit-draft">` ⇒ 清单里没有它 ⇒
    // 这份清单会把人带偏成「这个平台上没有草稿键」。
    // 现在把 `[class*="submit"]` 也纳进来（操作栏容器与草稿键都在这一类里）。
    const list: string[] = await page.evaluate(() => Array.from(
      document.querySelectorAll('button,[role=button],.semi-button,.bcc-button,a,[class*="submit"]'),
    ).map((e: any) => ((e.innerText || '') as string).trim()).filter(Boolean).slice(0, 60))
    console.log(`   页面可见按钮文本（最多 60 个）：${base.pyReprList(list.slice(0, 20))}`)
    writeFileSync(
      join(logDir, `draft-btn-candidates-${tag}.json`),
      `${JSON.stringify(list, null, 1)}\n`,
      'utf-8',
    )
  } catch (e) {
    console.log(`   （按钮清单抓取失败：${base.errName(e)}）`)
  }
}

export interface SaveDraftOpts {
  platform: string
  logDir: string
  no: number
  /** 等草稿键出现的秒数（表单在加载时键还没挂上）。 */
  waitS?: number
  /** 等「保存成功」确认的秒数。 */
  timeoutS?: number
  /**
   * 落库判据词（**点击后新出现**才算）。
   *
   * 为什么要单独一路：抖音 PC 端的落库信号是横幅
   * 「你还有上次未发布的视频，是否继续编辑？」——而这个横幅在**存第二条时
   * 点击前就已经在了**（单槽位，第一条的稿还占着）。
   * 若不看「点击前是否已存在」，第二条会当场命中 ⇒ 假绿灯。
   */
  landedWords?: readonly string[]
}

/**
 * 存一条草稿。返回的 res 里 `ok` 只在**确认落库**时为 true。
 *
 * 判不到成功 = 如实报「已点存草稿但未确认」，不谎报成功（与发布流程同口径）。
 */
export async function saveDraft(
  page: base.AnyPage,
  res: base.PubResult,
  opts: SaveDraftOpts,
): Promise<base.PubResult> {
  const logDir = opts.logDir
  const tag = base.pad2(opts.no)
  const waitS = opts.waitS ?? 90
  const timeoutS = opts.timeoutS ?? 40

  console.log('   📝 存草稿模式：找「存草稿 / 保存草稿」键…')
  let btn: DraftBtn | null = null
  const deadline = clock.now() + waitS
  while (clock.now() < deadline) {
    btn = await findDraftButton(page, opts.platform)
    if (btn !== null) break
    await clock.sleep(2)
  }
  if (btn === null) {
    res['ok'] = false
    res['stage'] = '找不到存草稿键（已放弃，绝不点发布）'
    console.log('   ❌ 找不到存草稿键 → 放弃本条，**不点发布**')
    await dumpButtons(page, logDir, tag)
    try {
      await page.screenshot({ path: join(logDir, `draftfail-${tag}.png`) })
    } catch {
      // 截图只是留证
    }
    return res
  }
  if (PUBLISH_BTN_TEXTS.includes(btn.text)) {
    res['ok'] = false
    res['stage'] = '草稿键与发布键文本重合（已放弃，绝不点发布）'
    console.log('   ❌ 草稿键与发布键文本重合 → 放弃本条')
    return res
  }
  console.log(`   ✓ 找到「${btn.text}」`)

  try {
    await page.screenshot({ path: join(logDir, `predraft-${tag}.png`) })
  } catch {
    // 截图只是留证
  }

  // **点击前就挂在页面上的成功文案不算证据**。
  // 封面刚传完时可能还飘着「封面保存成功」这类 toast——它包含「保存成功」，
  // 而词表里的「保存成功」是子串匹配 ⇒ 点存草稿之前就命中 ⇒ 当场判成功（假绿灯）。
  // 只留「点了存草稿之后才出现」的词；被判掉的词由 URL 落地判据兜底。
  const evidenceWords: string[] = []
  for (const w of DRAFT_SUCCESS_WORDS[opts.platform] ?? []) {
    if (!(await base.visibleTextHit(page, [w]))) evidenceWords.push(w)
  }

  // 落库判据词同理：点击前就有的（如抖音那条「你还有上次未发布的视频」，
  // 存第二条时它还占着上一条的位置）不算这一条的证据。
  const landedWords: string[] = []
  for (const w of opts.landedWords ?? []) {
    if (!(await base.visibleTextHit(page, [w]))) landedWords.push(w)
  }

  // 点之前先记下草稿键的状态：点了没反应时，要能一眼看出它是不是**禁用态**
  // （实测 2026-11-03 条 4：点了「存草稿」页面纹丝不动 ⇒ 键是灰的/禁用态，
  //  而点击本身在 Playwright 看来是「成功」的 ⇒ 没有这行诊断就无从下手）。
  try {
    const st = await btn.el.evaluate((e: any) => {
      const cs = getComputedStyle(e)
      return {
        tag: (e.tagName || '').toLowerCase(),
        cls: String(e.className || '').slice(0, 80),
        disabled: e.getAttribute('disabled'),
        ariaDisabled: e.getAttribute('aria-disabled'),
        cursor: cs.cursor,
        pointerEvents: cs.pointerEvents,
        opacity: cs.opacity,
        color: cs.color,
      }
    })
    console.log(`   · 草稿键状态：${JSON.stringify(st)}`)
  } catch {
    // 诊断而已，取不到不拦流程
  }

  try {
    await btn.el.scrollIntoViewIfNeeded()
    await clock.sleep(0.4)
    await btn.el.click({ timeout: 10000 })
  } catch (e) {
    // 顽固按钮：普通点击超时 → DOM click（与 bilibili.jsClick 同口径）
    try {
      await btn.el.evaluate((e: any) => e.click())
      console.log('   · 普通点击失败，改用 DOM click')
    } catch (e2) {
      res['ok'] = false
      res['stage'] = `点存草稿失败:${base.errStr(e2)}`
      console.log(`   ❌ 点存草稿失败：${base.errStr(e2)}`)
      return res
    }
  }
  console.log(`   ✅ 已点击「${btn.text}」`)
  await clock.sleep(2)
  await confirmDraftModal(page)

  try {
    await page.screenshot({ path: join(logDir, `postdraft-${tag}.png`) })
  } catch {
    // 截图只是留证
  }

  const landed = DRAFT_LANDED_URLS[opts.platform] ?? []
  // 点一次没动静就再点一次：平台在某些前置条件没满足时会**静默**忽略点击
  // （键还在、点击也「成功」，但页面不动）。重试比直接报失败更接近真相，
  // 而且草稿存重复一次是无害的（同一个槽位/同一条稿）。
  let ok = false
  for (let attempt = 1; attempt <= 2 && !ok; attempt++) {
    ok = await waitDraftSaved(
      page, evidenceWords, landed,
      attempt === 1 ? Math.min(timeoutS, 25) : timeoutS,
      landedWords,
    )
    if (ok) break
    if (attempt === 1) {
      console.log('   ⚠️ 点击后没检测到落库信号 → 再点一次草稿键')
      try {
        await btn.el.scrollIntoViewIfNeeded()
        await clock.sleep(0.6)
        await btn.el.click({ timeout: 10000 })
        console.log(`   ✅ 已再次点击「${btn.text}」`)
        await clock.sleep(2)
        await confirmDraftModal(page)
      } catch (e) {
        console.log(`   ⚠️ 再次点击失败：${base.errStr(e)}`)
      }
      try {
        await page.screenshot({ path: join(logDir, `postdraft-${tag}-retry.png`) })
      } catch {
        // 截图只是留证
      }
    }
  }
  if (!ok) {
    // 如实报现场：页面 URL + 可见提示（点了没反应时，这是唯一能定位的线索）
    try {
      const u = await base.pageUrl(page)
      const hints = await page.evaluate(() => {
        const out: string[] = []
        document.querySelectorAll(
          '[class*="toast"],[class*="message"],[class*="tips"],[class*="notice"],[class*="alert"]',
        ).forEach((e: any) => {
          const t = (e.innerText || '').trim().replace(/\s+/g, ' ')
          if (t && t.length < 100) out.push(t)
        })
        return [...new Set(out)]
      })
      console.log(`   ⚠️ 未确认落库。URL：${u}`)
      console.log(`   ⚠️ 页面可见提示：${JSON.stringify(hints)}`)
    } catch {
      // 取不到就取不到
    }
  }
  res['ok'] = ok
  res['stage'] = ok ? '已存草稿' : '已点存草稿但未确认'
  if (ok) {
    console.log('   ✅ 草稿已保存（可见文案或页面跳转确认）')
  } else {
    console.log('   ⚠️ 已点存草稿但未检测到确认提示——请人工看截图核验')
  }
  return res
}

/**
 * 存草稿成功判定：可见文案命中，或页面**已经落到**草稿列表，
 * 或**落库判据词**命中（如抖音的「你还有上次未发布的视频」横幅）。
 *
 * ⚠️ URL 判据的方向：**命中式**——`landed` 里的片段**出现**才算跳走。
 *
 * 这里**不能**照搬 base.waitSuccessStage 那套 `urlGone` 语义：那边的
 * `urlGone` 是「**投稿页**的标志片段」（含了 = 还在投稿页，消失了 = 跳走了），
 * 而 `landed` 是「**草稿列表**的标志片段」（含了 = 已经跳走）——两个方向正好相反。
 * 照搬的那一版写成 `!landed.some(u => url.includes(u))`，于是投稿页 URL
 * （`.../content/upload` 本来就不含 `content/manage`）**当场**返回 true：
 * 每一条都立刻判「已存草稿」（假绿灯），点没点成功根本测不出来。
 *
 * `landedWords` 是**点击后才算**的落库词（调用方已剔除点击前就存在的）。
 *
 * 至少查一遍：timeoutS=0 时也走一次判据（先判后超时），
 * 否则「查了一次」和「一次都没查」分不开。
 */
export async function waitDraftSaved(
  page: base.AnyPage,
  words: readonly string[],
  landed: readonly string[],
  timeoutS: number,
  landedWords: readonly string[] = [],
): Promise<boolean> {
  const deadline = clock.now() + timeoutS
  for (;;) {
    if (words.length && (await base.visibleTextHit(page, words))) return true
    if (landedWords.length && (await base.visibleTextHit(page, landedWords))) return true
    if (landed.length) {
      const cur = await base.pageUrl(page)
      if (cur && landed.some((u) => cur.includes(u))) return true
    }
    if (clock.now() >= deadline) return false
    await clock.sleep(2)
  }
}
