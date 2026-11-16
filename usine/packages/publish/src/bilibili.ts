// bilibili.ts — B 站发布器（⑨）：分区/创作声明/封面三重硬闸门 + .txt 字幕
// （publish/bilibili.py 的 TS 移植）。
//
// 硬闸门（纪律 19：宁可整条不发，也不带病发布）：分区、创作声明、封面
// 任一未生效 → 中止本条并截图留证，不点投稿键。
//
// 使用契约：
// - tasks 是 `manifest.build_manifest` 的产物；profile 默认
//   `base.PROFILES['bilibili']`；截图与 result JSON 全部落 logDir。
// - .txt 字幕从 subsDir/{lang}.txt 取，文件不存在就如实跳过——不编路径。
// - 必填项取值（BILI_ZONE / BILI_STMT_REQUIRED）由用户指定，换项目时由
//   调用方传入，不在本模块里私自改。
// - 存草稿模式（--draft）：分区/声明/封面/字幕照样填完，再点「保存草稿」停手，
//   **不点投稿**；找不到草稿键就放弃这一条（fail-closed），见 draft.ts。
import { existsSync } from 'node:fs'
import { basename, join } from 'node:path'

import * as base from './base.js'
import * as clock from './clock.js'
import * as draft from './draft.js'

// ── 浏览器侧全局（本包是 Node 包，tsconfig 的 lib 只有 ES2023，没有 DOM）──
// 下面 evaluate 的函数体**跑在浏览器上下文里**，但类型检查只认本包的 lib。
// 这里按 any 声明这几个全局，只为让类型检查过；运行期由浏览器提供。
// （此前 evaluate 一律传字符串——函数体根本不进类型检查，于是「传字符串在 JS 版
// Playwright 里不执行」这个缺陷一路绿灯活到今天。见 draft.ts 的说明。）
declare const document: any
declare const window: any
declare function getComputedStyle(el: any): any

export const UPLOAD_URL = 'https://member.bilibili.com/platform/upload/video/frame'
export const BILI_WALL: readonly string[] = ['扫码登录', '密码登录', '手机号登录', '登录后']

/**
 * 逃生阀：允许在草稿箱已满时**仍然上传并尝试存**（默认关闭）。
 *
 * 为什么需要它：满箱时平台到底「拒绝新增」还是「挤掉最旧的」，实测结论自相矛盾——
 * 2026-11-16 在同样 30 条的上限下连存 30 条全部成功（旧的最先消失），
 * 2026-11-17 第 61 条却弹出「最多保存30个稿件」。两种结论对应完全不同的做法
 * （前者可以一次灌满，后者必须先腾位置），而**探明它要花一次真实上传**。
 * ⇒ 留一个显式开关做那一次实验；日常不许开，开了就要知道可能白传一条。
 */
const IGNORE_DRAFT_CAP = process.env['BILI_IGNORE_DRAFT_CAP'] === '1'

// 必填项的兼容默认值；具体批次应由调用方用 zone / statement 显式覆盖。
export const BILI_ZONE = '知识'
// 必填「创作声明」的候选（首个为默认）。
//
// ⚠️ 结构实测更正（2026-11-15，`tools/probe-bili-stmt13.mjs` 逐字 dump）：
// `ul.bcc-select-option-list` 的直接子节点是 **9 个**，不是 7 个：
//   0–5  `article.option-hover-tips > li.bcc-option`  ← **必填创作声明**（6 个选项）
//   6    `div.option-divider`                          ← 分隔线
//   7    `div.auth-title`「是否添加内容授权声明（非必选）」
//   8    `article.option-hover-tips`「内容为自制：未经作者允许，禁止转载」
//        （无 li 子节点，内部是 `div.auth-content > span.option-text`）
//
// 也就是说**「内容为自制」不是必填声明的第 7 个选项，是另一个字段**（非必选的
// 内容授权声明）。2026-11-03 那版注释判定「它和『内容无需标注』并列，就是必填
// 声明的一个选项」——被这次的完整结构 dump 推翻：分隔线 + 「（非必选）」标题
// 把它明确划到另一个控件里去了。它点不动不是因为选择器过时，而是因为它**根本
// 不接受「当作声明选项」这种点法**。
// ⇒ 必填候选只能取 `li.bcc-option` 那 6 项；授权声明是责任项，不由本模块默认勾。
export const BILI_STMT_REQUIRED: readonly string[] = [
  '内容无需标注', '含AI生成内容', '含虚构演绎内容',
  '内容含营销信息', '个人观点，仅供参考', '内容为转载',
]
// 「内容为自制：未经作者允许，禁止转载」= **非必选的内容授权声明**（另一个字段）。
// 保留这个名字是因为调用方还引用它；它**不在** BILI_STMT_REQUIRED 里，也不会被
// setBiliStatement 默认勾上（那是责任项，由调用方显式决定）。
export const BILI_STMT_OPTIONAL = '内容为自制：未经作者允许，禁止转载'

// B 站成功页文案是「**稿件投递成功**」，不是「投稿/提交成功」。
// 栽过：词表里没有「投递」二字，脚本判成「已提交未确认」，
// 实际稿件早就进管理后台了。URL 也不会变，只能靠文案判定。
export const BILI_SUCCESS_WORDS: readonly string[] = [
  '稿件投递成功', '投递成功', '投稿成功',
  '稿件提交成功', '发布成功', '提交成功',
  '已进入审核', '审核中',
]

export async function blocking(page: base.AnyPage): Promise<string[]> {
  const out: string[] = []
  for (const [sel, name] of [
    ["button:has-text('立即投稿')", '立即投稿确认'],
    ["button:has-text('提交稿件')", '提交稿件确认'],
    [".semi-modal button:has-text('确定')", '确定弹窗'],
  ] as const) {
    try {
      if (await base.visibleWithin(page.locator(sel).first(), 500)) out.push(name)
    } catch {
      continue
    }
  }
  return out
}

/**
 * B站真正的提交键：文本**精确**为「立即投稿」/「提交稿件」。
 *
 * 踩过的坑（继承自抖音）：用子串匹配 `has-text('发布')` 会命中左上角
 * 「作品发布」导航，点完只跳草稿页。所以必须 exact。
 * 这里不强制 class 含 primary——实测 B 站那个蓝色主按钮的 class
 * 并不含该串，硬性要求会把真按钮也过滤掉；精确文本已经够严。
 */
export async function submitBtn(page: base.AnyPage): Promise<[any, string | null]> {
  // B 站的「立即投稿」不是 <button>，是 div/span 画的主按钮，
  // 所以不限定标签；但**必须 exact 文本**（子串会命中左侧「作品发布」导航，
  // 这是从抖音继承来的教训）。取纵坐标最大的那个——那才是页面底部的提交键。
  for (const txt of ['立即投稿', '提交稿件']) {
    try {
      const loc = page.getByText(txt, { exact: true })
      const cnt = Math.min(await loc.count(), 8)
      let best: any = null
      let bestY = -1
      for (let i = 0; i < cnt; i++) {
        const el = loc.nth(i)
        if (!(await base.visibleWithin(el, 400))) continue
        // 往上一层拿可点的容器
        let cand = el
        for (let _ = 0; _ < 3; _++) {
          cand = cand.locator('xpath=..')
          const b = await cand.boundingBox()
          if (b && b['height'] > 20 && b['width'] > 60) break
        }
        const bb = (await cand.boundingBox()) ?? (await el.boundingBox())
        if (!bb) continue
        if (bb['y'] > bestY) {
          best = cand
          bestY = bb['y']
        }
      }
      if (best !== null) return [best, txt]
    } catch {
      continue
    }
  }
  return [null, null]
}

/** 提交键没找到时，打印页面上所有可见 BUTTON，方便定位。 */
export async function dumpSubmitCandidates(page: base.AnyPage): Promise<void> {
  try {
    // evaluate 必须传真函数：传字符串时 JS Playwright 只把字符串当表达式求值，
    // 函数对象不可序列化 ⇒ 返回 undefined ⇒ 诊断清单恒为空。
    const btns = await page.evaluate(() => {
      const out: Array<Record<string, any>> = []
      document.querySelectorAll('button' as any).forEach((el: any) => {
        const r = el.getBoundingClientRect()
        if (r.width < 20 || r.height < 10) return
        const cs = getComputedStyle(el)
        if (cs.display === 'none' || cs.visibility === 'hidden') return
        out.push({
          t: (el.innerText || '').trim().slice(0, 20),
          cls: (el.className || '').toString().slice(0, 60),
          dis: el.disabled === true,
          y: Math.round(r.y),
        })
      })
      return out
    })
    console.log(`   ⚠️ 页面可见 BUTTON 共 ${btns.length} 个：`)
    for (const b of btns) {
      console.log(
        `      y=${String(b['y']).padStart(5)} disabled=${b['dis']} ${base.pyRepr(b['t'])} cls=${b['cls']}`,
      )
    }
  } catch (e) {
    console.log(`   ⚠️ 诊断失败：${base.errName(e)}`)
  }
}

/**
 * 关掉挡路的浮层。返回关掉几个。
 *
 * 踩过的坑：上传完视频后 B 站弹「开启后视频上传完成第一时间通知」，
 * 遮罩会拦标题、简介、封面的点击，表现成「封面上传失败」，实际是弹窗挡路。
 * 另外浏览器级的通知授权框也会叠上来，用 grantPermissions 提前授予就不会弹。
 */
export async function dismissBiliDialogs(page: base.AnyPage): Promise<number> {
  let closed = 0
  for (let round = 0; round < 4; round++) {
    let hit = false
    // batch-dialog：上条投稿后表单没重置，再传文件被当成「批量上传」，
    // 弹「批量上传将生成多条动态，打扰粉丝」，遮罩会拦死标题/简介/封面的点击。
    for (const [sel, kws] of [
      ["div[class*='videoup-notification-dialog']", ['知道了', '我知道了']],
      ["div[class*='batch-dialog']", ['知道了', '我知道了', '取消', '确定', '关闭']],
      ["div[class*='bcc-dialog__wrap']", ['知道了', '我知道了', '取消', '确定', '关闭']],
    ] as const) {
      const dlg = page.locator(sel).first()
      try {
        if (!(await base.visibleWithin(dlg, 800))) continue
      } catch {
        continue
      }
      for (const kw of kws) {
        try {
          const btn = dlg.getByText(kw, { exact: true }).first()
          if (!(await base.visibleWithin(btn, 500))) continue
          await btn.click({ timeout: 3000 })
          console.log(`      · 已关闭浮层（${kw}）`)
          await clock.sleep(1.2)
          closed++
          hit = true
          break
        } catch {
          continue
        }
      }
      if (hit) break
    }
    if (!hit) break
  }
  return closed
}

/**
 * 视频上传状态。返回：
 * - `done`     平台自己显示了「上传完成」
 * - `bytes-done` 字节数已满（已上传 X/Y，X==Y）但平台还没切到完成态
 * - `uploading …` 还在传
 * - `unknown`  读不到
 *
 * 为什么要单独读：**标题框一出现，编辑表单就能填**，所以「表单就绪」≠「视频传完」。
 * 实测（2026-11-03）：条 3 的视频 256.4MB，封面步骤时视频区还显示
 * 「已上传：256.4MB/256.4MB 当前速度：3.6MB/s 剩余时间：>1天」——
 * 字节满了但平台没切到「上传完成」态。
 * 这跟抖音「转码完成是假绿灯」是同一类：**半成品的素材不能进草稿**。
 */
export async function videoUploadState(page: base.AnyPage): Promise<string> {
  try {
    return await page.evaluate(() => {
      const t = document.body.innerText || ''
      if (t.includes('上传完成')) return 'done'
      const m = t.match(/已上传[：:]\s*([\d.]+)\s*(MB|GB)\s*\/\s*([\d.]+)\s*(MB|GB)/)
      if (m) {
        const a = parseFloat(m[1]) * (m[2] === 'GB' ? 1024 : 1)
        const b = parseFloat(m[3]) * (m[4] === 'GB' ? 1024 : 1)
        return b > 0 && Math.abs(a - b) < 0.01 ? 'bytes-done' : `uploading ${m[0]}`
      }
      return 'unknown'
    })
  } catch {
    return 'unknown'
  }
}

/**
 * 等视频上传完成（平台自己显示「上传完成」）。
 *
 * 超时返回 false —— 调用方必须 fail-closed（视频没传完就不许进草稿：
 * 存进去的是残片，跟抖音那条「转码完成是假绿灯」是同一个坑）。
 *
 * 超时给得宽（默认 240s）：256MB 的视频在实测里要传一两分钟，
 * 判据不许比被改进对象更严（AGENTS.md 的红线）。
 */
export async function waitVideoUploaded(page: base.AnyPage, rounds = 240): Promise<boolean> {
  for (let i = 0; i < rounds; i++) {
    const st = await videoUploadState(page)
    if (st === 'done') return true
    if (i === 0 || i % 15 === 0) console.log(`      · 视频上传状态：${st}`)
    await clock.sleep(1)
  }
  return false
}

export type BiliCoverOutcome = 'custom' | 'auto' | 'failed'

/**
 * 从目标秒数映射到帧条上最近的采样帧序号。
 *
 * 帧条是片长上的等距采样点（实测 41s 的片子给 7 帧 ≈ 0 / 6.8 / 13.7 …），
 * 所以「第 6.0 秒」只能落到最近的采样点上——取帧精度被平台量化，这是平台约束，不是我们可以选的。
 */
export function frameIndexFor(targetS: number, maxS: number, count: number): number {
  if (count <= 0) return -1
  if (!(maxS > 0) || count === 1) return 0
  const step = maxS / (count - 1)
  const i = Math.round(targetS / step)
  return Math.max(0, Math.min(count - 1, i))
}

/** 从封面文件名里读回「第几秒」，读不到就按 6 秒。文件名带时刻就是为这个。 */
export function coverSecondOf(coverPath: string): number {
  const m = /-cover@([\d.]+)s\.[a-z]+$/i.exec(coverPath)
  const s = m === null ? NaN : Number(m[1])
  return Number.isFinite(s) && s >= 0 ? s : 6
}

/**
 * 主表单封面位现在是什么。返回「长度 + 前 64 字符」当指纹。
 *
 * ⚠️ 封面位**永远是满的**：视频传完后 B 站会自己取一帧当默认封面，落在
 * `div.cover-module-main div.cover-img` 的 `background-image` 上（base64，约 20 万字符），
 * 而那个 div 里**没有任何 `<img>`**。所以「封面设上了没有」不能用
 * `querySelectorAll('img').length` 判——那个数一直是 0，会把每次运行都判成没设上。
 * 能判的是「指纹变没变」：变了 = 换成了我们的；没变 = 还是平台自动帧。
 */
async function coverFingerprint(page: base.AnyPage): Promise<string> {
  try {
    return await page.evaluate(() => {
      const el = document.querySelector('div.cover-module-main div.cover-img')
      if (el === null) return ''
      const bg = getComputedStyle(el).backgroundImage || ''
      return `${bg.length}:${bg.slice(0, 64)}`
    })
  } catch {
    return ''
  }
}

async function pollTrue(fn: () => Promise<boolean>, timeoutS: number): Promise<boolean> {
  for (let i = 0; i < timeoutS; i++) {
    if (await fn()) return true
    await clock.sleep(1)
  }
  return false
}

/** 关掉封面编辑器（等于取消）。关不掉就留着，由调用方的判据去处理。 */
async function cancelCoverEditor(page: base.AnyPage): Promise<void> {
  try {
    const cancel = page.locator('div.cover-editor div.button').filter({ hasText: '取消' }).first()
    if (await base.visibleWithin(cancel, 1200)) await cancel.click({ timeout: 4000 })
  } catch {
    // 取消键点不动不是致命项：调用方会再看弹窗关没关
  }
}

/**
 * 把封面定到视频第 N 秒那一帧。返回值是**结果分类**，不是布尔：
 *
 * - `custom`  已把封面换成指定帧（主表单封面指纹变了，且变成 `archive.biliimg.com` 上的真封面）
 * - `auto`    编辑器里没有可选帧 / 「完成」没落地 ⇒ 草稿用平台自动取帧。**不中止**，但要如实记下来
 * - `failed`  封面位或「封面制作」弹窗打不开 ⇒ 页面结构变了，调用方 fail-closed
 *
 * 为什么把「这次没设上」和「页面结构变了」分开：前者会让 118 集里零星几集退回自动封面，
 * 后者说明我们的选择器与被改进对象脱节，两条的处置完全不同——
 * 混成一个 false 会让零星退化杀掉整条产线，也会让真的结构变化被当成偶发而放过。
 *
 * ⚠️ 不要走「上传自定义图片」那条路：`div.bcc-upload` 的隐藏 input 直灌 `setInputFiles`
 * 会让 `input.files` 变成 1、`createObjectURL` 也被调用，但组件的 change 处理器**不接**，
 * 上传区与画布都不动、页面零报错；走 filechooser 也时成时不成（2026-11-15 实测 2 成 6 败）。
 * 而且即使图接住了，它也不等于「当前帧」——「完成」照样不提交。帧条这条路是确定性的。
 */
export async function setBiliCover(
  page: base.AnyPage,
  coverPath: string,
  tag: string,
  opts: { logDir: string },
): Promise<BiliCoverOutcome> {
  const logDir = opts.logDir
  const fpBefore = await coverFingerprint(page)

  // 1) 打开「封面制作」。入口是 `div.cover-slot`；`cover-empty-pill` 在本机恒为 0，别再用它。
  const slot = page.locator("div[class*='cover-slot']").first()
  if (!(await base.visibleWithin(slot, 2500))) {
    console.log('      ⚠️ 找不到封面位（视频可能还没传完）')
    return 'failed'
  }
  await slot.scrollIntoViewIfNeeded()
  await clock.sleep(0.8)
  await slot.click()

  const editor = page.locator('div.cover-editor').first()
  if (!(await pollTrue(() => base.visibleWithin(editor, 500), 8))) {
    console.log('      ⚠️ 「封面制作」弹窗没开')
    await page.screenshot({ path: join(logDir, `coverfail-bili-${tag}-nomodal.png`) })
    return 'failed'
  }
  console.log('      · 已打开「封面制作」')

  // 2) **选一帧**。这是整条链路上最反直觉的一步：
  //
  // 没选中任何帧时点「完成」，弹窗不关、主表单不变、页面**也不报错**——
  // 看上去像「点了没反应」，实际是在等你选。2026-11-15 为此白跑了七八轮探针：
  // 一直以为是「完成」键点得不对，真相是编辑器里压根没有「当前帧」。
  //
  // 帧条是片长上的等距采样点（实测 41s 给 7 帧），所以「第 N 秒」只能落到最近的采样点上。
  const targetS = coverSecondOf(coverPath)
  const thumbs = page.locator('div.cover-slider-image-list div.cover-slider-image')
  let frames = 0
  for (let i = 0; i < 15; i++) {
    frames = await thumbs.count()
    if (frames > 0) break
    await clock.sleep(1)
  }
  if (frames === 0) {
    console.log('      ⚠️ 帧条里没有可选的帧（平台还没出图）')
    await page.screenshot({ path: join(logDir, `coverfail-bili-${tag}-noframes.png`) })
    await cancelCoverEditor(page)
    return 'auto'
  }
  const maxS = await page.evaluate(() => {
    const dot = document.querySelector('div.cover-slider-time .vue-slider-dot')
    if (dot === null) return 0
    return Number(dot.getAttribute('aria-valuemax')) || 0
  })
  const idx = frameIndexFor(targetS, maxS, frames)
  try {
    await thumbs.nth(idx).click({ timeout: 6000 })
  } catch (e) {
    console.log(`      ⚠️ 点第 ${idx} 帧失败：${base.errName(e)}`)
    await cancelCoverEditor(page)
    return 'auto'
  }
  console.log(`      · 已选第 ${idx} 帧（共 ${frames} 帧，片长 ${maxS}s，目标 ${targetS}s）`)
  await clock.sleep(1.5)
  await page.screenshot({ path: join(logDir, `bilicov-${tag}-frame.png`) })

  // 3) 完成键精确是 `div.cover-editor div.button.submit`。
  // `getByText('完成', {exact:true})` 点到的是别的节点：弹窗不关、表单不变、也不报错。
  const done = page.locator('div.cover-editor div.button.submit').first()
  if (!(await base.visibleWithin(done, 2500))) {
    console.log('      ⚠️ 找不到「完成」键')
    await page.screenshot({ path: join(logDir, `coverfail-bili-${tag}-noconfirm.png`) })
    await cancelCoverEditor(page)
    return 'auto'
  }
  await done.click({ timeout: 8000 })
  const closed = await pollTrue(async () => !(await editor.isVisible().catch(() => false)), 25)
  console.log(`      · 已点「完成」${closed ? '，弹窗已关' : '，弹窗没关'}`)
  if (!closed) {
    await page.screenshot({ path: join(logDir, `coverfail-bili-${tag}-modalopen.png`) })
    await cancelCoverEditor(page)
    await pollTrue(async () => !(await editor.isVisible().catch(() => false)), 6)
  }

  // 4) 判据：指纹变了才算换成我们的。没变就是平台自动帧，如实报 'auto'。
  const fpAfter = await coverFingerprint(page)
  await page.screenshot({ path: join(logDir, `bilicov-${tag}-done.png`) })
  if (fpAfter === '' || fpAfter === fpBefore) {
    console.log('      ⚠️ 封面指纹没变（仍是平台自动取帧）')
    return 'auto'
  }
  return 'custom'
}

/**
 * 用 DOM 直接派发 click，绕开 Playwright 的 actionability 检查。
 *
 * B 站这两个下拉框有进场动画，Playwright 判定 element is not stable，
 * 普通 click 会一直重试到超时（栽过）。DOM click 立刻生效。
 */
export async function jsClick(page: base.AnyPage, locator: any): Promise<boolean> {
  try {
    // evaluate 必须传真函数：传字符串时 JS Playwright 只把字符串当表达式求值，
    // 函数对象不可序列化 ⇒ 返回 undefined ⇒ **点击根本没发生，但这里照样返回 true**。
    // 这个假成功会让「分区/创作声明/二次确认」三处静默失效。
    await locator.evaluate((e: any) => e.click())
    return true
  } catch {
    return false
  }
}

/**
 * 设主分区。点开下拉 → 在 `human-type-list` 里点目标分区。
 *
 * 踩过的坑：点左侧「分区」标签文字没用，得点右边显示当前值的框。
 * 主分区列表容器 class 是 `drop-list-v2-container human-type-list`。
 */
export async function setBiliZone(page: base.AnyPage, zone: string): Promise<boolean> {
  // 分区框的当前值在 `p.select-item-cont` 里，每次加载可能是 vlog/动物/音乐…
  // 不一样，不能按「当前值文本」反查，直接按容器 class 定位。
  const ctl = page.locator('div.video-human-type div.select-controller').first()
  try {
    if (!(await base.visibleWithin(ctl, 4000))) {
      console.log('   ⚠️ 找不到分区选择框')
      return false
    }
    await ctl.scrollIntoViewIfNeeded()
    await clock.sleep(0.6)
  } catch {
    console.log('   ⚠️ 找不到分区选择框')
    return false
  }
  if (!(await jsClick(page, ctl))) return false
  await clock.sleep(2.2)

  const lst = page.locator("div[class*='human-type-list']").first()
  try {
    if (!(await base.visibleWithin(lst, 2500))) {
      console.log('   ⚠️ 主分区列表没弹出来')
      return false
    }
    const item = lst.getByText(zone, { exact: true }).first()
    await item.scrollIntoViewIfNeeded()
    await clock.sleep(0.4)
    await jsClick(page, item)
    await clock.sleep(2)
  } catch (e) {
    console.log(`   ⚠️ 分区选择失败：${base.errName(e)}`)
    return false
  }

  // 确认：`.select-item-cont` 的文本应该变成目标分区
  try {
    const cur = page.locator('div.video-human-type p.select-item-cont').first()
    if (await base.visibleWithin(cur, 2500)) {
      const got = ((await cur.innerText()) ?? '').trim()
      if (got === zone) {
        console.log(`   ✓ 分区已设为「${zone}」`)
        return true
      }
      console.log(`   ⚠️ 分区现在是「${got}」，不是「${zone}」`)
      return false
    }
  } catch {
    // 确认控件读不到就按失败处理
  }
  console.log(`   ⚠️ 分区没设成「${zone}」`)
  return false
}

// ── 定时发布（稿件侧预置「几点发」） ──────────────────────────────────
//
// **这个能力解决的是哪一段**：日更产线要在稿件里预置「定时发布」时刻，
// 但**终点仍然是存草稿**——脚本从不点投稿（纪律：发布永不自动）。
// 人工在草稿箱点「投稿」后，稿件按预置时刻定时发出。
// 两者是分工不是替代：--draft 决定终点，--publish-at 决定稿件里预置的时刻。
//
// ⚠️ **时刻必须晚于当前时间**：B 站拒收早于现在的定时时刻
//   （页面自己写着「可选择距离当前最早≥5分钟/最晚≤15天的时间」）。
// ⇒ 「今天 09:00 跑批」能预置的最早时刻是**次日 09:00**。
//
// ── 实测形态（2026-11-15 DOM 探针）──────────────────────────────────
//   div.time-container
//     ├ div.section-title-container > h3「定时发布」
//     └ div.time-switch-wrp
//         ├ div.switch-container        ← 自绘开关（**不是** input[type=checkbox]）
//         ├ span.time-switch-wrp-text   ← 「可选择距离当前最早≥5分钟…」
//         └ div.time-picker             ← 点开开关才出现
//             └ div.d-time-container
//                 ├ div.date-picker-timezone-wrp > div.bcc-select  ← 时区，默认 (UTC+08:00) Beijing
//                 ├ div.date-picker-date-wrp > div.date-picker-date
//                 │     ├ p.date-show      ← 日期显示「2026-11-15」
//                 │     └ i.date-show-icon ← 点开日历面板
//                 └ div.date-picker-date-wrp > div.date-picker-timer
//                       ├ p.date-show      ← 时间显示「19:12」
//                       └ i.date-show-icon ← 点开时分面板
//
//   日历面板：div.date-picker-container
//     ├ div.date-picker-nav-wrp  ← 「2026年11月」+ 4 个 svg 箭头（左右各两个）
//     ├ div.date-picker-body-wrp > div.date-wrp
//     │     └ div.date-picker-body-item.date-item[.date-item-selected|.date-item-disabled]
//     └ div.date-picker-footer-wrp > span.date-picker-select-today「默认」
//
//   时分面板：div.time-picker-container
//     └ div.time-picker-body-wrp
//         ├ div.time-picker-panel-select-wrp × 2
//         │     第一个 = 小时（24 个 span.time-picker-panel-select-item）
//         │     第二个 = 分钟（12 个，步长 5 分钟）
//
// ── 三条实测出来的硬约束（不按这三条写就会静默选不中）────────────────
//  1. **禁用态跟当前时刻绑定**：没选日期时，早于当前小时的格子带
//     `time-select-disabled`（点了没反应）。**必须先选日期**——
//     选完「明天」后 24 个小时格全部解禁。
//  2. **点小时不带分钟**：点完小时 09，分钟仍保留原值（显示 09:12）——分钟要另点。
//  3. **分钟步长 5 分钟**：可选值 00/05/…/55；不是 5 的倍数选不中。
//
// ── 页面里有**两个** .time-container（一个可见、一个隐藏副本）────────
// ⇒ 所有定位都必须在页面内**按可见性**筛，不能用 Playwright 的默认唯一性
//   （strict mode 直接报「resolved to 2 elements」）。
export const BILI_SCHEDULE_WORDS: readonly string[] = ['定时发布', '预约发布时间']

/** 'YYYY-MM-DD HH:mm' → {date:'YYYY-MM-DD', time:'HH:mm'}；格式不对返回 null。 */
export function parseScheduleAt(when: string): { date: string; time: string } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})$/.exec(String(when).trim())
  if (!m) return null
  return { date: `${m[1]}-${m[2]}-${m[3]}`, time: `${m[4]}:${m[5]}` }
}

/** 「2026年11月」→ 月序（年*12+月），认不出返回 null。 */
export function monthOrdinal(title: string): number | null {
  const m = /(\d{4})\s*年\s*(\d{1,2})\s*月/.exec(String(title))
  if (!m) return null
  return Number(m[1]) * 12 + Number(m[2])
}

/** 分钟格只有 5 分钟步长：把分钟对齐到 ≤ 原值的最近 5 的倍数。 */
export function alignMinute(mm: string): { value: string; exact: boolean } {
  const n = Number(mm)
  if (!Number.isInteger(n) || n < 0 || n > 59) return { value: '00', exact: false }
  const v = Math.floor(n / 5) * 5
  return { value: String(v).padStart(2, '0'), exact: v === n }
}

/**
 * 打开「定时发布」并把时刻设成 `when`。
 *
 * 返回 true = 表单里的时刻**回读得到**（不是「点了就算」）。
 */
export async function setBiliPublishAt(
  page: base.AnyPage,
  when: string,
  opts: { logDir: string; tag?: string },
): Promise<boolean> {
  const parsed = parseScheduleAt(when)
  if (parsed === null) {
    console.log(`   ⚠️ 定时发布时刻格式不对（要 'YYYY-MM-DD HH:mm'）：${when}`)
    return false
  }
  const logDir = opts.logDir
  const tag = opts.tag ?? 'schedule'
  const dp = parsed.date.split('-')
  const tp = parsed.time.split(':')
  const yy = dp[0] ?? ''
  const mo = dp[1] ?? ''
  const dd = dp[2] ?? ''
  const hh = tp[0] ?? ''
  const mm = tp[1] ?? ''
  const minute = alignMinute(mm)
  if (!minute.exact) {
    console.log(`   ⚠️ 分钟 ${mm} 不是 5 的倍数（平台只有 5 分钟步长）→ 按 ${minute.value} 设`)
  }

  const shot = async (name: string) => {
    try {
      await page.screenshot({ path: join(logDir, `schedulefail-bili-${tag}-${name}.png`) })
    } catch {
      // 截图只是留证
    }
  }

  // ---- 1) 打开「定时发布」自绘开关 ----
  const sw = await page.evaluate(() => {
    const vis = (e: any) => {
      const r = e.getBoundingClientRect()
      const cs = getComputedStyle(e)
      return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
    }
    const el = Array.from<any>(document.querySelectorAll('div.time-switch-wrp div.switch-container' as any)).find(vis)
    if (!el) return 'no-switch'
    if (/switch-container-active/.test(String(el.className || ''))) return 'already-on'
    el.click()
    return 'clicked'
  })
  if (sw === 'no-switch') {
    console.log('   ⚠️ 找不到「定时发布」开关')
    await shot('noswitch')
    return false
  }
  await clock.sleep(1.5)
  console.log(`   ✓ 已打开「定时发布」开关（${sw}）`)

  // ---- 2) 日期 ----
  // 2a. 开日历面板
  await page.evaluate(() => {
    const vis = (e: any) => {
      const r = e.getBoundingClientRect()
      const cs = getComputedStyle(e)
      return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
    }
    const el = Array.from<any>(document.querySelectorAll('div.date-picker-date p.date-show' as any)).find(vis)
    if (el) el.click()
  })
  await clock.sleep(1.2)

  // 2b. 月份对齐。**翻页箭头不靠 class 猜，靠试**：
  //     逐个点标题右侧的 svg，看月份序有没有 +1；+12 的是「下一年」不是「下一月」。
  const wantOrd = Number(yy) * 12 + Number(mo)
  let nextArrowIdx = -1
  for (let i = 0; i < 18; i++) {
    const title = await page.evaluate(() => {
      const vis = (e: any) => {
        const r = e.getBoundingClientRect()
        const cs = getComputedStyle(e)
        return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
      }
      const t = Array.from<any>(document.querySelectorAll('p.date-picker-nav-title' as any)).find(vis)
      return t ? (t.innerText || '').trim() : null
    })
    if (title === null) {
      console.log('   ⚠️ 读不到日历月份标题')
      await shot('nomonth')
      return false
    }
    const cur = monthOrdinal(title)
    if (cur === null) {
      console.log(`   ⚠️ 月份标题认不出：${title}`)
      await shot('badmonth')
      return false
    }
    if (cur === wantOrd) break
    if (cur > wantOrd) {
      // 面板只能往后翻（平台不允许选过去）⇒ 目标月比当前月还早 = 不可能
      console.log(`   ⚠️ 目标 ${parsed.date} 早于面板当前月份（${title}）——平台不收过去的时刻`)
      await shot('pastmonth')
      return false
    }
    // 还没到目标月 → 翻一页
    if (nextArrowIdx < 0) {
      // 首次：逐个试右侧箭头，找那个「月份 +1」的
      const probed = await page.evaluate(() => {
        const vis = (e: any) => {
          const r = e.getBoundingClientRect()
          const cs = getComputedStyle(e)
          return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
        }
        const w = Array.from<any>(document.querySelectorAll('div.date-picker-nav-wrp' as any)).find(vis)
        if (!w) return { svgs: [] as number[], title: '' }
        const svgs = Array.from<any>(w.querySelectorAll('svg')).filter(vis)
        return { svgs: svgs.map((_, k) => k) }
      })
      let advanced = false
      for (const k of probed.svgs) {
        const before = await page.evaluate(() => {
          const vis = (e: any) => {
            const r = e.getBoundingClientRect()
            const cs = getComputedStyle(e)
            return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
          }
          const t = Array.from<any>(document.querySelectorAll('p.date-picker-nav-title' as any)).find(vis)
          return t ? (t.innerText || '').trim() : ''
        })
        await page.evaluate((idx: number) => {
          const vis = (e: any) => {
            const r = e.getBoundingClientRect()
            const cs = getComputedStyle(e)
            return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
          }
          const w = Array.from<any>(document.querySelectorAll('div.date-picker-nav-wrp' as any)).find(vis)
          if (!w) return
          const svgs = Array.from<any>(w.querySelectorAll('svg')).filter(vis)
          const el = svgs[idx]
          if (el) el.click()
        }, k)
        await clock.sleep(0.6)
        const after = await page.evaluate(() => {
          const vis = (e: any) => {
            const r = e.getBoundingClientRect()
            const cs = getComputedStyle(e)
            return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
          }
          const t = Array.from<any>(document.querySelectorAll('p.date-picker-nav-title' as any)).find(vis)
          return t ? (t.innerText || '').trim() : ''
        })
        const b = monthOrdinal(before)
        const a = monthOrdinal(after)
        if (b !== null && a !== null && a === b + 1) {
          nextArrowIdx = k
          advanced = true
          break
        }
      }
      if (!advanced) {
        console.log('   ⚠️ 找不到「下一月」箭头（月份翻不动）')
        await shot('noarrow')
        return false
      }
    } else {
      await page.evaluate((idx: number) => {
        const vis = (e: any) => {
          const r = e.getBoundingClientRect()
          const cs = getComputedStyle(e)
          return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
        }
        const w = Array.from<any>(document.querySelectorAll('div.date-picker-nav-wrp' as any)).find(vis)
        if (!w) return
        const svgs = Array.from<any>(w.querySelectorAll('svg')).filter(vis)
        const el = svgs[idx]
        if (el) el.click()
      }, nextArrowIdx)
      await clock.sleep(0.6)
    }
  }

  // 2c. 点目标日
  const dayRes = await page.evaluate((day: string) => {
    const vis = (e: any) => {
      const r = e.getBoundingClientRect()
      const cs = getComputedStyle(e)
      return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
    }
    const cells = Array.from<any>(document.querySelectorAll('.date-picker-body-item' as any))
      .filter((e: any) => vis(e) && (e.textContent || '').trim() === day)
    if (!cells.length) return 'no-cell'
    const ok = cells.find((e: any) => !/disabled/i.test(String(e.className || '')))
    if (!ok) return 'disabled'
    ok.click()
    return 'clicked'
  }, dd)
  if (dayRes !== 'clicked') {
    console.log(`   ⚠️ 选日期失败：${dayRes}`)
    await shot('nodate')
    return false
  }
  await clock.sleep(1.2)

  // 2d. 回读日期
  const dateNow = await page.evaluate(() => {
    const vis = (e: any) => {
      const r = e.getBoundingClientRect()
      const cs = getComputedStyle(e)
      return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
    }
    const el = Array.from<any>(document.querySelectorAll('div.date-picker-date p.date-show' as any)).find(vis)
    return el ? (el.innerText || '').trim() : null
  })
  if (dateNow !== parsed.date) {
    console.log(`   ⚠️ 日期回读是「${dateNow}」，不是「${parsed.date}」`)
    await shot('baddate')
    return false
  }
  console.log(`   ✓ 日期已设为 ${dateNow}`)

  // 2e. **关掉日历面板再开时间面板**：日历开着的时候时分面板拿到的是
  //     「旧状态」的格子（禁用态没跟着日期刷新）⇒ 点小时没反应。
  await page.evaluate(() => {
    const vis = (e: any) => {
      const r = e.getBoundingClientRect()
      const cs = getComputedStyle(e)
      return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
    }
    const el = Array.from<any>(document.querySelectorAll('div.date-picker-date p.date-show' as any)).find(vis)
    if (el) el.click()
  })
  await clock.sleep(0.8)
  const datePanelOpen = await page.evaluate(() => {
    const vis = (e: any) => {
      const r = e.getBoundingClientRect()
      const cs = getComputedStyle(e)
      return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
    }
    return Array.from<any>(document.querySelectorAll('div.date-picker-container' as any)).some(vis)
  })
  if (datePanelOpen) {
    await page.keyboard.press('Escape').catch(() => {})
    await clock.sleep(0.6)
  }

  // ---- 3) 时间 ----
  await page.evaluate(() => {
    const vis = (e: any) => {
      const r = e.getBoundingClientRect()
      const cs = getComputedStyle(e)
      return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
    }
    const el = Array.from<any>(document.querySelectorAll('div.date-picker-timer p.date-show' as any)).find(vis)
    if (el) el.click()
  })
  await clock.sleep(1.2)

  // 3a. 点小时
  const hourRes = await page.evaluate((h: string) => {
    const vis = (e: any) => {
      const r = e.getBoundingClientRect()
      const cs = getComputedStyle(e)
      return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
    }
    const cols = Array.from<any>(document.querySelectorAll('.time-picker-panel-select-wrp' as any)).filter(vis)
    if (cols.length < 2) return 'no-cols'
    const hourCol = cols.find((c: any) => c.querySelectorAll('.time-picker-panel-select-item').length >= 24)
    if (!hourCol) return 'no-hour-col'
    const cell = Array.from<any>(hourCol.querySelectorAll('.time-picker-panel-select-item'))
      .find((e: any) => (e.textContent || '').trim() === h)
    if (!cell) return 'no-cell'
    if (/disabled/i.test(String(cell.className || ''))) return 'disabled'
    cell.click()
    return 'clicked'
  }, hh)
  if (hourRes !== 'clicked') {
    console.log(`   ⚠️ 选小时失败：${hourRes}`)
    await shot('nohour')
    return false
  }
  await clock.sleep(0.8)

  // 3b. 点分钟（**点小时不带分钟**，分钟保留原值，必须另点）
  const minRes = await page.evaluate((m: string) => {
    const vis = (e: any) => {
      const r = e.getBoundingClientRect()
      const cs = getComputedStyle(e)
      return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
    }
    const cols = Array.from<any>(document.querySelectorAll('.time-picker-panel-select-wrp' as any)).filter(vis)
    if (cols.length < 2) return 'no-cols'
    const hourCol = cols.find((c: any) => c.querySelectorAll('.time-picker-panel-select-item').length >= 24)
    const minCol = cols.find((c: any) => c !== hourCol)
    if (!minCol) return 'no-min-col'
    const cell = Array.from<any>(minCol.querySelectorAll('.time-picker-panel-select-item'))
      .find((e: any) => (e.textContent || '').trim() === m)
    if (!cell) return 'no-cell'
    if (/disabled/i.test(String(cell.className || ''))) return 'disabled'
    cell.click()
    return 'clicked'
  }, minute.value)
  if (minRes !== 'clicked') {
    console.log(`   ⚠️ 选分钟失败：${minRes}`)
    await shot('nomin')
    return false
  }
  await clock.sleep(1)

  // ---- 4) 回读确认（点了不算，填进去才算） ----
  const timeNow = await page.evaluate(() => {
    const vis = (e: any) => {
      const r = e.getBoundingClientRect()
      const cs = getComputedStyle(e)
      return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
    }
    const el = Array.from<any>(document.querySelectorAll('div.date-picker-timer p.date-show' as any)).find(vis)
    return el ? (el.innerText || '').trim() : null
  })
  if (timeNow !== `${hh}:${minute.value}`) {
    console.log(`   ⚠️ 时间回读是「${timeNow}」，不是「${hh}:${minute.value}」`)
    await shot('badtime')
    return false
  }
  console.log(`   ✓ 定时发布时刻已预置：${dateNow} ${timeNow}`)
  return true
}
const STMT_NOISE: readonly string[] = [
  '主站', '试试更多', '成为UP主', '投稿', '首页', '内容管理',
  '数据中心', '粉丝管理', '互动管理', '收益管理', '花生',
  'updream', '创作成长', '任务中心', '必火推广', '创作学院',
  '创作权益', '社区公约', '创作设置', '添加封面', '以下为系统',
  'AI生成', '标题', '创作声明', '分区', '标签', '记录',
  '中国', '歪果仁', '还可以添加', '是否添加内容授权声明',
  '遇到问题',
]

/**
 * 设创作声明。返回实际选中的文案，没选成返回空串。
 *
 * 这是对外声明，涉及责任，**选不中就如实报错，绝不跳过**。
 * 调用方传单个候选时只尝试该值，不回退成另一项对外声明。
 *
 * ⚠️ **声明区只有一个 select**（实测 2026-11-03，`probe_bili_statement.ts`）：
 * `div.statement-main div.bcc-select` 计数 = 1，展开后 13 个选项全在**同一个**
 * `ul.bcc-select-option-list` 里：
 *   内容无需标注 / 含AI生成内容 / 含虚构演绎内容 / 内容含营销信息 /
 *   个人观点，仅供参考 / 内容为转载 / **内容为自制：未经作者允许，禁止转载**
 *
 * 也就是说「内容为自制」**不是**独立的「内容授权声明」字段，
 * 而是必填创作声明的一个**选项**。原来那版按「两件事」办：
 * 先选必填的「内容无需标注」、再「另勾」版权声明——**同一个 input** 被后写覆盖成
 * 「内容为自制」，收尾校验判「必填框现在不是『内容无需标注』」⇒ 4 条全被中止。
 *
 * 正确做法：**只选一个值**，然后以「input 的值」+「投稿键是否解禁」
 * 两道闸门验收。
 */
export async function setBiliStatement(
  page: base.AnyPage,
  keywords: readonly string[],
  opts: { logDir: string },
): Promise<string> {
  const logDir = opts.logDir
  // 「请选择符合…」是 input 的 placeholder，不是文本节点，getByText
  // 永远找不到；按容器 class 定位。
  const sel = page.locator('div.statement-main div.bcc-select').first()
  try {
    if (!(await base.visibleWithin(sel, 4000))) {
      console.log('   ⚠️ 找不到创作声明选择框')
      return ''
    }
    await sel.scrollIntoViewIfNeeded()
    await clock.sleep(0.6)
  } catch {
    console.log('   ⚠️ 找不到创作声明选择框')
    return ''
  }
  if (!(await jsClick(page, sel))) return ''
  await clock.sleep(2.2)

  // 读**必填声明区**的选项文本。
  //
  // ⚠️ 判据必须落在结构上，不能落在「列表里有什么文字」上（2026-11-15 实测）：
  // `ul.bcc-select-option-list` 里既有 6 个必填选项，也有「内容授权声明（非必选）」
  // 那一块（`div.option-divider` + `div.auth-title` + 一个无 li 的 article）。
  // 旧写法 `querySelectorAll('ul … li, ul … article')` 把两边混成一张表，于是
  // 「内容为自制」被当成必填候选去点——它那行不接受这种点法，永远点不动，
  // 而每个「点不动」都会让循环去点下一个候选，最后落在表里最后一项。
  //
  // 结构性判据：**必填选项都有 `li.bcc-option` 子节点，授权声明那行没有**。
  // 首选按 li 读；读不到再按「分隔线之前的 article」读（同一条结构事实的另一种
  // 写法）；两者都读不到就 fail-closed，**不退回扫视口**——扫视口分不清必填与
  // 非必选，正是这条歧义的来源。
  let listItems: string[] = await page.evaluate(() => {
    const out: string[] = []
    document.querySelectorAll('ul.bcc-select-option-list li.bcc-option' as any)
      .forEach((li: any) => {
        const t = ((li.innerText || '') as string).trim()
        if (t && !out.includes(t)) out.push(t)
      })
    return out
  })
  if (!listItems.length) {
    listItems = await page.evaluate(() => {
      const out: string[] = []
      const ul: any = document.querySelector('ul.bcc-select-option-list')
      if (!ul) return out
      for (const child of Array.from(ul.children) as any[]) {
        // 分隔线之后是「内容授权声明」区，不是必填声明
        if ((child.className || '').toString().includes('option-divider')) break
        if (child.tagName !== 'ARTICLE') continue
        const t = ((child.innerText || '') as string).trim()
        if (t && !out.includes(t)) out.push(t)
      }
      return out
    })
  }
  let candList: string[] = listItems
  // 只保留像声明项的（排除导航/栏位等噪声）
  let stmtOpts = candList.filter(
    (o) =>
      !STMT_NOISE.includes(o)
      && Array.from(o).length >= 4
      && !o.startsWith('*')
      && !['12/80', '80', '7'].includes(o),
  )
  if (!stmtOpts.length) {
    console.log('   ⚠️ 创作声明选项没读到')
    await page.screenshot({ path: join(logDir, 'bili-stmt-debug.png') })
    return ''
  }
  console.log(`   · 创作声明可选：${base.pyReprList(stmtOpts)}`)
  candList = stmtOpts

  const inp = page.locator('div.statement-main input.bcc-select-input-inner').first()

  const curValue = async (): Promise<string> => {
    try {
      return ((await inp.inputValue({ timeout: 2000 })) ?? '').trim()
    } catch {
      return ''
    }
  }

  /** 下拉是不是开着的（选项列表可见）。 */
  const listOpen = async (): Promise<boolean> => page.evaluate(() => {
    const vis = (e: any) => {
      const r = e.getBoundingClientRect()
      const cs = getComputedStyle(e)
      return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'
    }
    return Array.from(document.querySelectorAll('ul.bcc-select-option-list' as any)).some(vis)
  })

  /** 确保下拉开着。关着的��话点选项等于点空白 ⇒ 浮层被关掉，后面全废。 */
  const ensureOpen = async (): Promise<boolean> => {
    if (await listOpen()) return true
    if (!(await jsClick(page, sel))) return false
    await clock.sleep(1.8)
    return await listOpen()
  }

  /**
   * 等 input 回写成 target。
   *
   * ⚠️ 为什么不能「睡固定时长再读一次」（2026-11-15 实测踩过）：B 站把选中值写回
   * `input.value` 有**肉眼可见的延迟**（>1.5s），定长睡眠后读到空串 ⇒ 判「这一项
   * 点不动」⇒ 继续点下一个候选 ⇒ 每个候选都真的点下去了、每次都覆盖前一个，
   * 最后落在候选表里的**最后一个**（实测落成「含AI生成内容」），而脚本还以为
   * 自己在「逐个试到能点动为止」。症状是「选项乱跳」，根因是等待方式。
   * ⇒ 一律用「轮询到不变量成立」代替「睡死再读一次」。
   */
  const waitValue = async (target: string, timeoutS = 6): Promise<boolean> => {
    const deadline = clock.now() + timeoutS
    while (clock.now() < deadline) {
      if ((await curValue()) === target) return true
      await clock.sleep(0.25)
    }
    return false
  }

  /**
   * 在已展开的浮层里点中 target，并以「是否回写到 input」为准。
   *
   * ⚠️ 候选取自**必填声明区**，判据是 `li.bcc-option`（结构，不是文字）：
   * 授权声明那行「内容为自制」没有 li 子节点，它属于另一个字段（见
   * BILI_STMT_REQUIRED 的结构 dump）。旧版把 article 层也当候选，等于把
   * 「非必选的内容授权声明」塞进必填候选表——它永远点不动（2026-11-15 实测）。
   */
  const pick = async (target: string): Promise<boolean> => {
    const sels = [
      'ul.bcc-select-option-list li.bcc-option',
    ]
    for (const selStr of sels) {
      let el: any = null
      try {
        const cand = page.locator(selStr)
        const n = await cand.count()
        for (let i = 0; i < n; i++) {
          const one = cand.nth(i)
          const txt = ((await one.innerText()) ?? '').trim()
          if (txt === target) {
            el = one
            break
          }
        }
      } catch {
        continue
      }
      if (el === null) {
        console.log(`      · 没找到「${target}」的节点（${selStr}）`)
        continue
      }
      try {
        if (!(await ensureOpen())) {
          console.log(`      · 下拉没打开，点不了「${target}」`)
          continue
        }
        // 下拉是 overflow:auto 的容器 ⇒ 选项要滚进**视口**才能点。
        // 浏览器原生 scrollIntoView 会把 overflow 容器与页面一起滚到位。
        await el.evaluate((e: any) => e.scrollIntoView({ block: 'center' }))
        await clock.sleep(0.5)
        const bb = await el.boundingBox()
        if (!bb) continue
        // ⚠️ **绝不在视口外点**：那里的坐标落在浮层之外 ⇒ 这一击会把下拉关掉，
        //   后面每一个候选都点不动（实测踩过：点「内容为自制」失败后，
        //   剩下 6 个候选全被判「点不动」，真因是浮层已经被关掉了）。
        const vp = page.viewportSize()
        if (vp) {
          const inside = bb['y'] >= 0 && bb['x'] >= 0
            && bb['y'] + bb['height'] <= vp.height
            && bb['x'] + bb['width'] <= vp.width
          if (!inside) {
            console.log(`      · 「${target}」滚不进视口（y=${Math.round(bb['y'])}），换一种方式`)
            // 兜底：直接派发 DOM click（Vue 的选项事件通常在 li 上）
            const done = await el.evaluate((e: any) => {
              e.click()
              return true
            }).catch(() => false)
            if (done) {
              if (await waitValue(target)) return true
            }
            continue
          }
        }
        // 真实鼠标点击：JS 合成 click 触发不了 Vue 的选项事件
        const cx = bb['x'] + bb['width'] / 2
        const cy = bb['y'] + bb['height'] / 2
        await page.mouse.click(cx, cy)
        if (await waitValue(target)) return true
        // 只有在没生效时才诊断：点之前先问页面「这个坐标上到底是谁」——
        // 坐标算错、被浮层盖住、目标在视口外却给出视口内坐标，全靠这一条分辨
        // （否则只能看到「没生效」，然后开始怀疑选择器）。
        const afterClick = await curValue()
        const atPoint = await page.evaluate(([px, py]: number[]) => {
          const e: any = (document as any).elementFromPoint(px, py)
          return e ? ((e.innerText || e.textContent || '') as string).trim().slice(0, 40) : null
        }, [cx, cy]).catch(() => null)
        console.log(`      · 点「${target}」没生效（点后 input=「${afterClick || '空'}」，`
          + `点处 (${Math.round(cx)}, ${Math.round(cy)}) 上是「${atPoint || '空'}」）`)
        // 点 li 没生效（有些项的可点层是外层 article）⇒ 再点 article
        const parent = el.locator('xpath=..')
        const pbb = await parent.boundingBox().catch(() => null)
        if (pbb) {
          await page.mouse.click(pbb['x'] + pbb['width'] / 2, pbb['y'] + pbb['height'] / 2)
          if (await waitValue(target)) return true
        }
      } catch (err) {
        console.log(`      · 点「${target}」时抛错：${String((err as any)?.message ?? err).slice(0, 200)}`)
        continue
      }
    }
    return false
  }

  // 选**一个**值：声明区只有一个 select，选项互斥（后写的覆盖先写的）。
  //
  // 候选按**优先级**依次试，取第一个「点了能真正回写到 input」的。
  // 单候选调用没有退路：用户拍板的是哪项，就只能落哪项。
  //
  // 为什么是「试到回写成功为止」而不是「点第一个」：UI 变体里某个选项可能
  // 点不动（浮层动画、选项被折叠）。旧版是「点第一个 + 收尾再校」，
  // 于是点不动就直接整条中止——这里改成逐个试，仍然 fail-closed
  // （一个都点不上才返回空串）。
  const ordered: string[] = []
  for (const kw of keywords) {
    for (const o of candList) {
      if (o.includes(kw) && !ordered.includes(o)) ordered.push(o)
    }
  }
  if (!ordered.length) {
    // Python 打印的是 tuple repr（圆括号），不是 list repr
    console.log(`   ⚠️ 声明选项里没有含 (${keywords.map((k) => `'${k}'`).join(', ')}) 的`)
    return ''
  }

  let want: string | null = null
  for (const cand of ordered) {
    if (await pick(cand)) {
      want = cand
      console.log(`   ✓ 创作声明 = ${cand}`)
      break
    }
    console.log(`   · 声明「${cand}」点不动，试下一个`)
  }
  if (!want) {
    console.log('   ⚠️ 所有声明选项都点不动')
    return ''
  }

  // 收尾校验：**以 input 的实际值为准**。
  // 旧版在这里判「必填框必须是『内容无需标注』」，而它此前刚把同一个 input
  // 写成了版权声明 ⇒ 4 条全被误判中止。现在选什么就校什么。
  const got = await curValue()
  if (got !== want) {
    console.log(`   ⚠️ 收尾校验：声明框现在是「${got || '空'}」，不是「${want}」`)
    return ''
  }
  return want
}

/**
 * B 站的风控文案（**只等，不代填** —— 纪律 21）。
 *
 * 实测（2026-11-15）：上传后弹「请完成短信验证」——验证码发到该账号注册的手机号。
 * 它用 `div.base-verify-bg` 盖住整个表单 ⇒ 标题框**点不动** ⇒ 表现成
 * 「标题没录进去（已中止投稿）」，真实原因却是风控弹窗挡路。
 * ⇒ 填标题之前必须先判风控、并在人工过完验证后确认遮罩真的没了。
 */
export const BILI_RISK_WORDS: readonly string[] = [
  '请完成短信验证', '请完成验证', '短信验证', '获取验证码',
  'Scan to verify', '操作过于频繁', '请稍后再试', '发布失败，请稍后重试',
]

/** 硬闸门中止：记 stage + 现场截图 + 返回结果（宁可整条不发）。 */
async function bail(
  res: base.PubResult,
  page: base.AnyPage,
  logDir: string,
  tag: string,
  stage: string,
  msg: string,
): Promise<base.PubResult> {
  res['stage'] = stage
  console.log(`   🛑 ${msg}`)
  try {
    await page.screenshot({ path: join(logDir, `coverfail-bili-${tag}.png`) })
  } catch {
    // 截图只是留证
  }
  return res
}

// ── 单条发布（按阶段拆分：上传 → 表单就绪 → 必填闸门 → 填词 → 提交） ────

export const DESC_SEL = (
  "div[contenteditable='true'], textarea[placeholder*='简介'], "
  + 'div.editor-kit-editor, .ql-editor'
)

/**
 * 送入上传口。页面上一个 file input 都没有 → 如实报错返回 false。
 *
 * 栽过的坑：v1 这里直接对 null 调 set_input_files 报 AttributeError，
 * 报错信息与真实原因（上传口没挂上）对不上，排障绕了远路。
 */
export async function uploadVideo(page: base.AnyPage, vid: string): Promise<boolean> {
  const fis = page.locator("input[type='file']")
  let vinput: any = null
  const cnt = await fis.count()
  for (let i = 0; i < cnt; i++) {
    const acc = (await fis.nth(i).getAttribute('accept')) ?? ''
    if (acc.includes('.mp4')) {
      vinput = fis.nth(i)
      break
    }
  }
  if (vinput === null && cnt) vinput = fis.first()
  if (vinput === null) {
    console.log('   ❌ 投稿页上找不到任何 file input（上传口未挂上）')
    return false
  }
  await vinput.setInputFiles(vid)
  console.log('   ✓ 视频已送入上传通道')
  return true
}

/** 等上传完成：出现标题输入框。返回标题框 locator，未就绪返回 null。 */
export async function waitFormReady(
  page: base.AnyPage,
  rounds = 120,
): Promise<any> {
  for (let i = 0; i < rounds; i++) {
    for (const sel of ["input[placeholder*='标题']", "input[maxlength='80']"]) {
      const loc = page.locator(sel).first()
      try {
        if (await base.visibleWithin(loc, 600)) return loc
      } catch {
        continue
      }
    }
    await clock.sleep(1.5)
  }
  return null
}

/**
 * 删掉标签区里**不在清单内**的平台预填胶囊，返回被删掉的文字。
 *
 * 为什么要删：B 站标签区的结构（2026-11-15 用 `tools/probe-bili-tags.mjs` 逐字 dump）
 * 是
 * ```
 * div#tag-container.tag-container
 *   div.tag-input-wrp > div.input-container
 *     div.tag-pre-wrp > div.label-item-v2-container
 *                          p.label-item-v2-content   ← 标签文字
 *                          svg.close                 ← 删除「×」
 *     div.input-instance > input[placeholder='按回车键Enter创建标签']
 *     p.tag-last-wrp                                ← 「还可以添加7个标签」
 * ```
 * 平台会预填 3 个推荐标签（当天实测「影视剪辑 / 原创 / 剪辑」；同一账号几小时前
 * 是「化学 / 初中 / 学习」——预填内容自己会漂），而**总上限是 10 个**：
 * 我们的 8 个 + 预填 3 个 = 11 ⇒ 最后一个被平台拒绝，弹「允许添加的标签已经达到
 * 上限了」，回读判 missing ⇒ 整条中止（2026-11-15 第 5 集「铷」，连撞两次）。
 *
 * 口径：预填的是平台猜的，不是作者写的。按 `data/publish-copy/*.json` 的标签集发，
 * 不让平台猜测挤掉它。删不掉就留着——配额不够时后面的 missing 会照实报出来。
 */
async function pruneForeignTags(page: base.AnyPage, wanted: ReadonlySet<string>): Promise<string[]> {
  const removed: string[] = []
  const pills = page.locator('#tag-container .tag-pre-wrp .label-item-v2-container')
  // ⚠️ 必须「每轮重查」而不是先 count 再按下标遍历：点掉一个胶囊后 DOM 会重排，
  // 用旧下标继续点会漏掉紧邻的那个（2026-11-15 实测：预填 3 个只清掉 2 个，
  // 「原创」被跳过）。总上限 10，所以轮数上限给 12 足够。
  for (let round = 0; round < 12; round++) {
    let count = 0
    try {
      count = await pills.count()
    } catch {
      break
    }
    let target = -1
    let targetText = ''
    for (let i = 0; i < count; i++) {
      let text = ''
      try {
        text = ((await pills.nth(i).locator('.label-item-v2-content').innerText()) ?? '').trim()
      } catch {
        continue
      }
      if (text && !wanted.has(text)) {
        target = i
        targetText = text
        break
      }
    }
    if (target < 0) break
    try {
      await pills.nth(target).locator('svg.close').first().click({ timeout: 3000 })
      await clock.sleep(0.3)
      removed.push(targetText)
    } catch {
      // 删不掉就停手：配额不够时后面的 missing 会照实报出来，不静默
      break
    }
  }
  return removed
}

/**
 * 填 B 站的**标签**（不是简介）。
 *
 * 实测（2026-11-15）：标签框是 `input[placeholder="按回车键Enter创建标签"]`，
 * 逐个填 + 回车才会变成标签片（`xx ×` 的胶囊）。平台会**预填**几个推荐标签
 * （实测「化学 / 初中 / 学习」，同日又实测「影视剪辑 / 原创 / 剪辑」），所以必填项
 * 本身不会空——但**预填的占配额**（总上限 10 个），所以填之前先清掉不在清单里的
 * 预填标签，见 `pruneForeignTags`。
 *
 * ⚠️ 为什么不再把标签塞进简介（老行为）：B 站的「标签」与「话题」是两套东西——
 * 标签决定**检索与分发**，话题只是简介里的一个链接。老做法把 '#标签' 打进简介，
 * 结果检索侧一个标签都没有。
 *
 * 失败口径：输入框**找不到** → 只告警不中止（页面形态变了，或平台已预填够用）；
 * 输入框在但**标签没贴上** → 返回 false（这是本机能做而没做好的事）。
 */
export async function setBiliTags(page: base.AnyPage, tags: readonly string[]): Promise<boolean> {
  if (!tags.length) return true
  const input = page.locator("input[placeholder*='创建标签']").first()
  let has = false
  try {
    has = await base.visibleWithin(input, 2500)
  } catch {
    has = false
  }
  if (!has) {
    console.log('   ⚠️ 找不到标签输入框（页面形态可能变了）——跳过标签')
    return true
  }

  const wanted = new Set(tags.map((t) => String(t).trim().replace(/^#/, '')).filter((t) => t !== ''))
  const removed = await pruneForeignTags(page, wanted)
  if (removed.length) {
    console.log(`   · 已清掉平台预填标签 ${base.pyReprList(removed)}（占标签配额）`)
  }

  for (const t of tags) {
    const tag = String(t).trim().replace(/^#/, '')
    if (!tag) continue
    try {
      await input.click()
      await input.fill(tag)
      await page.keyboard.press('Enter')
      await clock.sleep(0.35)
    } catch (e) {
      console.log(`   ⚠️ 标签「${tag}」没贴上：${base.errStr(e)}`)
      return false
    }
  }
  // 回读：标签区的文本里应当能看到刚填的标签
  const area = page.locator("input[placeholder*='创建标签']").first()
  const areaText = await area.evaluate((el: any) => {
    let node: any = el
    for (let i = 0; i < 6 && node.parentElement; i++) node = node.parentElement
    return (node.innerText || '').replace(/\s+/g, ' ')
  })
  const missing = tags
    .map((t) => String(t).trim().replace(/^#/, ''))
    .filter((t) => t !== '' && !areaText.includes(t))
  if (missing.length) {
    // 配额是这条判据最可能的成因（上限 10 个，预填会占名额）——把计数器一起报出来，
    // 免得下次又只能靠截图猜。
    let quota = ''
    try {
      quota = ((await page.locator('#tag-container p.tag-last-wrp').first().innerText()) ?? '').trim()
    } catch {
      quota = ''
    }
    console.log(`   ⚠️ 标签没出现在标签区：${base.pyReprList(missing.slice(0, 6))}${quota ? `（${quota}）` : ''}`)
    return false
  }
  console.log(`   ✓ 标签已填 ${tags.length} 个`)
  return true
}

/**
 * .txt 字幕口（文件从 subsDir/{lang}.txt 取，参数化不写死）。
 *
 * 字幕是可选步骤：没给 subsDir / 没有字幕文件 / 没有字幕口都如实跳过，
 * 但喂失败要报出来——「没喂上」与「本来就不用喂」是两回事。
 */
export async function uploadSubtitle(
  page: base.AnyPage,
  t: base.Task,
  subsDir: string | null,
): Promise<void> {
  const fis = page.locator("input[type='file']")
  const cnt = await fis.count()
  let txtf: any = null
  for (let i = 0; i < cnt; i++) {
    const f = fis.nth(i)
    try {
      if (((await f.getAttribute('accept')) ?? '') === '.txt') {
        txtf = f
        break
      }
    } catch {
      continue
    }
  }
  if (txtf !== null && subsDir != null) {
    const srt = join(subsDir, `${t['lang']}.txt`)
    if (existsSync(srt)) {
      try {
        await txtf.setInputFiles(srt)
        console.log(`   ✓ 字幕已上传 ${basename(srt)}`)
      } catch (e) {
        console.log(`   ⚠️ 字幕上传失败：${base.errStr(e)}`)
      }
    } else {
      console.log(`   （无字幕文件 ${basename(srt)}，跳过）`)
    }
  } else {
    console.log(txtf === null ? '   （未找到 .txt 字幕口，跳过）' : '   （未给 subs_dir，跳过字幕）')
  }
}

/** 点投稿键 → 二次确认 → 成功轮询。 */
export async function submitAndConfirm(
  page: base.AnyPage,
  res: base.PubResult,
  t: base.Task,
  opts: { logDir: string },
): Promise<base.PubResult> {
  const logDir = opts.logDir
  const [el, txt] = await submitBtn(page)
  await el.scrollIntoViewIfNeeded()
  await clock.sleep(0.5)
  await el.click()
  console.log(`   ✅ 已点「${txt}」`)
  await clock.sleep(4)
  await page.screenshot({ path: join(logDir, `postbili-${base.pad2(t['no'])}.png`) })

  // ⚠️ 点「立即投稿」之后**还有一道二次确认**，不点等于没投。
  // 栽过：首轮 11 条全卡在这，稿件管理里一条都没有，
  // 而汇总只打「已提交未确认」。这里把可能的确认键全试一遍。
  for (const kw2 of ['确认投稿', '确定', '确认', '提交稿件', '知道了', '完成']) {
    try {
      const b = page.getByText(kw2, { exact: true })
      const n = Math.min(await b.count(), 6)
      let clicked = false
      for (let i = 0; i < n; i++) {
        const el2 = b.nth(i)
        if (!(await base.visibleWithin(el2, 500))) continue
        await el2.scrollIntoViewIfNeeded()
        await clock.sleep(0.3)
        if (await jsClick(page, el2)) {
          console.log(`      · 已点二次确认「${kw2}」`)
          await clock.sleep(3)
          clicked = true
          break
        }
      }
      if (!clicked) continue
      break
    } catch {
      continue
    }
  }
  await clock.sleep(2)
  await page.screenshot({ path: join(logDir, `postbili-${base.pad2(t['no'])}-confirm.png`) })

  // B 站成功页文案是「**稿件投递成功**」，不是「投稿/提交成功」。
  // 栽过：词表里没有「投递」二字，脚本判成「已提交未确认」，
  // 实际稿件早就进管理后台了。URL 也不会变，只能靠文案判定。
  const [ok, stage] = await base.waitSuccessStage(page, BILI_SUCCESS_WORDS, 120, 2, {
    urlGone: ['upload', 'frame'],
  })
  res['ok'] = ok
  res['stage'] = stage
  if (ok) {
    console.log(stage === '已发布' ? `   ✅ ${stage}` : `   ✅ 已跳转 ${await base.pageUrl(page)}`)
  } else {
    console.log(`   ⚠️ 已提交但未确认，URL=${await base.pageUrl(page)}`)
  }
  return res
}

// ── 已存草稿 → 投稿 ─────────────────────────────────────────────────

/**
 * 草稿箱列表 URL。
 *
 * 实测（2026-11-15，`examples/periodic-12lang/tools/probe-bili-drafts*.mjs` 逐字 dump）：
 * - 每页 **10 条**，行容器 `section.bcc-cmad-card`，标题 `.bcc-cmadc-title-time p.title`，
 *   保存时间 `p.time`，分页 `li.bcc-pagination-item` / `.bcc-pagination-next`；
 * - 列表按**保存时间倒序**（最近存的在最前）⇒「第几集」不能按位置读，必须按标题认；
 * - 卡片右侧还有一个 `button.bcc-cmadc-btn`（**删除**）——本模块永不点它。
 */
export const DRAFT_LIST_URL = 'https://member.bilibili.com/platform/upload-manager/article?group=draft'

export interface BiliDraftRef {
  draftId: string
  title: string
  savedAt: string
}

/**
 * 读草稿箱里**真实**的条数（不是本地记过几条）。
 *
 * 为什么必须问平台：草稿箱有条数上限（`draft.DRAFT_CAPACITY`），到顶之后
 * 平台**静默挤掉最旧的**。于是「本地记了 60 条成功」与「箱里只剩 30 条」
 * 可以同时为真——2026-11-16 就是这么丢了 30 集，而脚本一直以为它们还在。
 *
 * 数法按页面自报：页脚 `.bcc-pagination-total` 的文本是「共3页 / 30个，」。
 * 认不出就退回去数当前页卡片，再不行返回 null（**不许**用 0 冒充「空箱」——
 * 那会让调用方以为可以随便存）。
 */
export async function countDrafts(page: base.AnyPage): Promise<number | null> {
  try {
    await page.goto(DRAFT_LIST_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 })
    await clock.sleep(8)
    const n = await page.evaluate(() => {
      const el = document.querySelector('.bcc-pagination-total')
      const txt = el ? ((el as any).innerText || '') : ''
      const m = String(txt).match(/(\d+)\s*个/)
      if (m) return Number(m[1])
      return document.querySelectorAll('section.bcc-cmad-card').length
    })
    return typeof n === 'number' && Number.isFinite(n) ? n : null
  } catch {
    return null
  }
}

/**
 * 草稿编辑页 URL。
 *
 * 卡片上封面框 / 标题 / 「编辑」三处 `<a>` 的 href 都是
 * `/platform/upload/video/frame?type=draft&draftId=<id>` ⇒ **免点击直达**。
 * 别去点卡片：卡片常在首屏下方，不先滚入视口就 mouse.click 等于点在视口外
 * （2026-11-15 第一版探针就栽在这里，URL 一点没变而看不出原因）。
 */
export function draftEditUrl(draftId: string): string {
  return `${UPLOAD_URL}?type=draft&draftId=${encodeURIComponent(draftId)}`
}

/** 读当前页的草稿卡片（每页 10 条）。 */
export async function readDraftCards(page: base.AnyPage): Promise<BiliDraftRef[]> {
  const rows = await page.evaluate(() => {
    const out: Array<Record<string, string>> = []
    document.querySelectorAll('section.bcc-cmad-card').forEach((card: any) => {
      const titleEl = card.querySelector('.bcc-cmadc-title-time p.title')
      const timeEl = card.querySelector('.bcc-cmadc-title-time p.time')
      const link = card.querySelector('.bcc-cmadc-title-time p.title a')
      const href = link ? String(link.getAttribute('href') ?? '') : ''
      const m = /draftId=(\d+)/.exec(href)
      out.push({
        draftId: m ? (m[1] ?? '') : '',
        title: titleEl ? String(titleEl.innerText ?? '').trim() : '',
        savedAt: timeEl ? String(timeEl.innerText ?? '').trim() : '',
      })
    })
    return out
  })
  return (rows as Array<Record<string, string>>)
    .filter((r) => (r['draftId'] ?? '') !== '' && (r['title'] ?? '') !== '')
    .map((r) => ({
      draftId: String(r['draftId']),
      title: String(r['title']),
      savedAt: String(r['savedAt'] ?? ''),
    }))
}

/** 翻完草稿箱所有页，返回全部草稿（按 draftId 去重，保持列表顺序）。 */
export async function listDrafts(
  page: base.AnyPage,
  opts: { maxPages?: number } = {},
): Promise<BiliDraftRef[]> {
  const maxPages = opts.maxPages ?? 12
  await page.goto(DRAFT_LIST_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 })
  await clock.sleep(7)
  const total = await page.evaluate(() => {
    const el = document.querySelector('.bcc-pagination-total')
    return el ? String(el.innerText ?? '').trim() : ''
  })
  console.log(`   草稿箱分页：${total === '' ? '（读不到分页总数，按空页停）' : total}`)
  const seen = new Map<string, BiliDraftRef>()
  for (let p = 1; p <= maxPages; p++) {
    const rows = await readDraftCards(page)
    let added = 0
    for (const r of rows) {
      if (seen.has(r.draftId)) continue
      seen.set(r.draftId, r)
      added++
    }
    console.log(`   第 ${p} 页：${rows.length} 条（新增 ${added}）`)
    if (rows.length === 0) break
    const moved = await page.evaluate((nextNo: number) => {
      const items: any[] = Array.from(document.querySelectorAll('.bcc-pagination-item') as any)
      const li = items.find((x) => String(x.innerText ?? '').trim() === String(nextNo))
      if (!li) return false
      const a = li.querySelector('a')
      if (a) {
        a.click()
        return true
      }
      li.click()
      return true
    }, p + 1)
    if (!moved) break
    await clock.sleep(3.5)
  }
  return [...seen.values()]
}

export interface BiliPublishDraftOpts {
  logDir: string
  /** 'YYYY-MM-DD HH:mm'；不给则沿用草稿里已有的定时设置。 */
  publishAt?: string | null
  riskWaitMin?: number
  /** 截图命名用的任务号（只影响文件名，不影响行为）。 */
  no?: number
}

/**
 * 把**已存在的草稿**改成定时发布并投稿。
 *
 * 与 `publishOne` 的分工：这里不传视频、不填标题正文标签、不设封面——草稿里
 * 早就有了。只做三件事：
 *   ① **核对身份**（按 draftId 打开的到底是哪条，只能靠标题回读）；
 *   ② 改定时时刻（`setBiliPublishAt`，回读得到才算设上）；
 *   ③ 点投稿 + 二次确认 + 成功判定（复用 `submitAndConfirm`）。
 *
 * 为什么①是硬闸门：按 draftId 打开成功不代表 id 就是目标那条（列表是另一台机器
 * 生成的排序），而**投稿不可撤回**——认错稿子就是发错视频。宁可不发。
 */
export async function publishDraft(
  page: base.AnyPage,
  ref: BiliDraftRef,
  opts: BiliPublishDraftOpts,
): Promise<base.PubResult> {
  const logDir = opts.logDir
  const no = opts.no ?? 0
  const tag = base.pad2(no)
  const res: base.PubResult = { no, lang: '', ok: false, stage: '' }
  console.log(`\n🚀 草稿 ${ref.draftId}（保存于 ${ref.savedAt}）`)
  console.log(`   ${ref.title}`)

  await page.goto(draftEditUrl(ref.draftId), { waitUntil: 'domcontentloaded', timeout: 90_000 })
  await clock.sleep(6)

  const titleBox = await waitFormReady(page)
  if (titleBox === null) {
    return bail(res, page, logDir, `${tag}-draft`, '草稿未打开（已中止投稿）', '标题框未出现 → 中止，不投')
  }
  const cur = String((await titleBox.inputValue().catch(() => '')) ?? '').trim()
  const want = ref.title.trim()
  if (cur !== want) {
    console.log(`   ❌ 标题不符：页面「${cur}」≠ 期望「${want}」`)
    return bail(res, page, logDir, `${tag}-draft`, '草稿身份不符（已中止投稿）', '打开的不是要找的草稿 → 中止，不投')
  }
  console.log('   ✓ 草稿身份核对通过（标题逐字一致）')

  const n = await dismissBiliDialogs(page)
  if (n) console.log(`   ✓ 已清掉 ${n} 个浮层`)

  if (await base.riskHit(page, BILI_RISK_WORDS)) {
    const cleared = await base.waitRiskClear(page, {
      no,
      logDir,
      limitMin: opts.riskWaitMin ?? 10,
      kws: BILI_RISK_WORDS,
      maskSel: '.base-verify-bg, .base-verify',
      hint: '完成短信验证（验证码已发到该账号注册的手机号）',
    })
    if (!cleared) {
      return bail(res, page, logDir, `${tag}-risk`, '风控未解除（已中止投稿）', '风控没过（短信验证未完成）→ 中止，不投')
    }
    console.log('   ✓ 风控已解除')
  }

  if (opts.publishAt) {
    const schedOk = await setBiliPublishAt(page, opts.publishAt, { logDir, tag })
    if (!schedOk) {
      return bail(res, page, logDir, `${tag}-schedule`, '定时发布未生效（已中止投稿）', '定时时刻没设上 → 中止，不投')
    }
  }

  let ready = false
  for (let i = 0; i < 90; i++) {
    const [el, txt] = await submitBtn(page)
    if (el !== null && (await el.getAttribute('disabled')) === null) {
      ready = true
      console.log(`   ✓ 提交键「${txt}」已可用`)
      break
    }
    await clock.sleep(1)
  }
  if (!ready) {
    res['stage'] = '提交按钮未就绪'
    console.log('   ❌ 提交按钮未就绪')
    await dumpSubmitCandidates(page)
    return res
  }

  return submitAndConfirm(page, res, { no, lang: '', title: ref.title } as base.Task, { logDir })
}

/**
 * 删掉草稿箱里的**一条**草稿。
 *
 * 这是破坏性动作（不可恢复），所以每条闸门都朝「宁可不删」一侧倒：
 *   ① 只按**标题逐字**匹配定位卡片——绝不按位置、序号或下标（列表按保存时间倒序，
 *      位置会随每次保存而变）；
 *   ② 匹配到 **0 条**或**不止 1 条**都拒绝执行（认不准就不删）；
 *   ③ 确认弹窗里只认 `button.bili-btn.ok`（实测文案「确定」；「取消」是 `.bili-btn.cancel`）；
 *   ④ 删完**回读**：同一标题还能在列表里找到 = 失败，如实返回 false。
 *
 * 实测（2026-11-15，`tools/probe-bili-delete.mjs`）：点卡片右下角那个
 * `button.bcc-cmadc-btn`（内含垃圾桶图标）会弹出确认框，正文写明要删的标题。
 */
export async function deleteDraft(
  page: base.AnyPage,
  ref: BiliDraftRef,
  opts: { logDir: string },
): Promise<boolean> {
  const want = ref.title.trim()
  const findCard = async (): Promise<{ hits: number; x: number; y: number }> => {
    return await page.evaluate((title: string) => {
      const cards: any[] = Array.from(document.querySelectorAll('section.bcc-cmad-card') as any)
      const hits = cards.filter((c) => {
        const t = c.querySelector('.bcc-cmadc-title-time p.title')
        return t !== null && String(t.innerText ?? '').trim() === title
      })
      if (hits.length !== 1) return { hits: hits.length, x: 0, y: 0 }
      const card = hits[0]
      const btn = card.querySelector('button.bcc-cmadc-btn')
      if (btn === null) return { hits: 1, x: 0, y: 0 }
      card.scrollIntoView({ block: 'center' })
      const r = btn.getBoundingClientRect()
      return { hits: 1, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) }
    }, want)
  }

  await page.goto(DRAFT_LIST_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 })
  // 列表是**异步渲染**的：固定 sleep 会在「页面还在加载/重排」时读到 0 条卡片，于是这条
  // 草稿被判成「没找到」而漏删（2026-11-15 实测：30 条清空漏掉 1 条，其余 29 条全中，
  // 而那条其实一直在箱里）。判据要「有内容才往下走」；真空箱靠超时兜底，最终仍按
  // 「命中 0 条」拒绝删除——朝「宁可不删」一侧倒的方向没变。
  const waitCards = async (): Promise<number> => {
    for (let i = 0; i < 24; i++) {
      const n = await page.evaluate(
        () => document.querySelectorAll('section.bcc-cmad-card').length,
      )
      if (n > 0) return n
      await clock.sleep(0.5)
    }
    return 0
  }
  await clock.sleep(3)
  await waitCards()
  for (let p = 1; p <= 12; p++) {
    const hit = await findCard()
    if (hit.hits > 1) {
      console.log(`   ⚠️ 标题命中 ${hit.hits} 条草稿（认不准），不删：${want}`)
      return false
    }
    if (hit.hits === 1) {
      if (hit.x === 0 && hit.y === 0) {
        console.log('   ⚠️ 卡片上找不到删除键，不删')
        return false
      }
      await clock.sleep(0.6)
      await page.mouse.click(hit.x, hit.y)
      await clock.sleep(2)
      const okBtn = page.locator('button.bili-btn.ok')
      if (!(await base.visibleWithin(okBtn.first(), 4000))) {
        console.log('   ⚠️ 删除确认弹窗没出现，不删')
        try {
          await page.screenshot({ path: join(opts.logDir, 'del-no-dialog.png') })
        } catch {
          // 截图只是留证
        }
        return false
      }
      await okBtn.first().click()
      await clock.sleep(2.5)
      const after = await findCard()
      if (after.hits === 0) {
        console.log(`   🗑  已删草稿：${want}`)
        return true
      }
      console.log(`   ⚠️ 点了确定但草稿还在（命中 ${after.hits}）`)
      return false
    }
    const moved = await page.evaluate((nextNo: number) => {
      const items: any[] = Array.from(document.querySelectorAll('.bcc-pagination-item') as any)
      const li = items.find((x) => String(x.innerText ?? '').trim() === String(nextNo))
      if (!li) return false
      const a = li.querySelector('a')
      if (a) {
        a.click()
        return true
      }
      li.click()
      return true
    }, p + 1)
    if (!moved) break
    await clock.sleep(3)
    await waitCards()
  }
  console.log(`   ⚠️ 草稿箱里没找到这条草稿（可能已被删）：${want}`)
  return false
}

export async function publishOne(
  page: base.AnyPage,
  t: base.Task,
  auto: boolean,
  opts: {
    logDir: string
    subsDir?: string | null
    draft?: boolean
    zone?: string
    statement?: string
    publishAt?: string | null
    /** 等风控解除的分钟数（人工过短信验证用）；默认 10 分钟。 */
    riskWaitMin?: number
  },
): Promise<base.PubResult> {
  const logDir = opts.logDir
  const vid = t['video']
  const cov = t['cover']
  const subsDir = opts.subsDir ?? null
  const res: base.PubResult = { no: t['no'], lang: t['lang'], ok: false, stage: '' }
  // tag 只用于日志/截图命名（任务号），绝不再作循环变量名——
  // 栽过的坑：话题循环用同名 tag 把任务号覆盖成 #话题串，
  // 封面/中止证据截图全拿错文件名。
  const tag = base.pad2(t['no'])
  console.log(`\n🚀 [${base.pad2(t['no'])}] ${t['lang']}  ${basename(vid)}`)
  console.log(`   标题: ${t['title']}`)

  if (!existsSync(vid)) {
    res['stage'] = '素材缺失'
    console.log('   ❌ 视频不存在')
    return res
  }

  // 每条都**强制**重新导航到投稿页，不能只在 URL 不含 upload 时才刷。
  // 否则上条投稿后表单还留着旧视频，再送一个文件会被 B 站当成「批量上传」，
  // 弹出 batch-dialog 遮罩，后面标题/简介/封面的点击全被拦死。
  await page.goto(UPLOAD_URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await clock.sleep(5)

  if (!(await uploadVideo(page, vid))) {
    return bail(res, page, logDir, `${tag}-noupload`, '上传口未就绪（已中止投稿）', '找不到上传 input → 中止，不投')
  }
  // 批量上传弹窗往往在送入文件后才冒出来，先清一轮
  for (let i = 0; i < 2; i++) {
    await clock.sleep(2)
    await dismissBiliDialogs(page)
  }

  const titleBox = await waitFormReady(page)
  if (titleBox === null) {
    res['stage'] = '上传/表单未就绪'
    console.log('   ❌ 标题框未出现（上传可能失败）')
    return res
  }
  console.log('   ✓ 上传完成，编辑表单就绪')

  // 通知弹窗会盖住整个表单，先清干净再动输入框
  const n = await dismissBiliDialogs(page)
  if (n) console.log(`   ✓ 已清掉 ${n} 个浮层`)

  // 风控（短信验证 / 扫码）：**只等，不代填**（纪律 21）。
  // 触发时表单被 `div.base-verify-bg` 盖住 ⇒ 标题框点不动 ⇒ 表现成
  // 「标题没录进去」。不先判风控，就会把风控误报成标题录不进去。
  if (await base.riskHit(page, BILI_RISK_WORDS)) {
    const cleared = await base.waitRiskClear(page, {
      no: t['no'],
      logDir,
      limitMin: opts.riskWaitMin ?? 10,
      kws: BILI_RISK_WORDS,
      maskSel: '.base-verify-bg, .base-verify',
      hint: '完成短信验证（验证码已发到该账号注册的手机号）',
    })
    if (!cleared) {
      return bail(res, page, logDir, `${tag}-risk`, '风控未解除（已中止投稿）',
        '风控没过（短信验证未完成）→ 中止，不投')
    }
    console.log('   ✓ 风控已解除，继续填表')
  }

  // 标题（纪律 19：录不进标题 = 带病发布，中止本条）
  if (!(await base.fillTitle(page, titleBox, t['title'], { limit: 80 }))) {
    return bail(res, page, logDir, `${tag}-title`, '标题未录入（已中止投稿）', '标题没录进去 → 中止，不投')
  }

  // 必填项：分区 + 创作声明（B 站不填这两个 投稿键不解禁）
  if (!(await setBiliZone(page, opts.zone ?? BILI_ZONE))) {
    return bail(res, page, logDir, `${tag}-zone`, '主分区未生效（已中止投稿）', '主分区没设上 → 中止，不投')
  }
  const statements = opts.statement ? [opts.statement] : BILI_STMT_REQUIRED
  if (!(await setBiliStatement(page, statements, { logDir }))) {
    return bail(res, page, logDir, `${tag}-stmt`, '创作声明未选定（已中止投稿）', '创作声明没选上 → 中止，不投')
  }

  // 简介：B站正文是 contenteditable；正文录不进 = 带病发布（纪律 19）
  //
  // ⚠️ 标签**不**打进简介（B 站的「标签」是独立字段，决定检索；老做法把
  // '#标签' 塞进简介，检索侧一个标签都没有）——见 setBiliTags 的说明。
  const desc = page.locator(DESC_SEL).first()
  let descReady = false
  try {
    descReady = await base.visibleWithin(desc, 2500)
  } catch {
    descReady = false
  }
  if (!descReady) {
    return bail(res, page, logDir, `${tag}-desc`, '简介框未出现（已中止投稿）', '没找到简介框 → 中止，不投')
  }
  if (!(await base.fillBody(page, desc, t['body'], { tags: [], pause: 0.3 }))) {
    return bail(res, page, logDir, `${tag}-desc`, '简介未录入（已中止投稿）', '简介没录进去 → 中止，不投')
  }

  // 标签：填进标签框（找不到输入框只告警；贴不上才中止）
  if (!(await setBiliTags(page, t['tags'] ?? []))) {
    return bail(res, page, logDir, `${tag}-tags`, '标签未贴上（已中止投稿）', '标签没贴上 → 中止，不投')
  }

  await uploadSubtitle(page, t, subsDir)

  // 视频必须**真的传完**才继续：封面与草稿都依赖它。
  // ⚠️ 「标题框出现」≠「视频传完」——编辑表单在传的过程中就能填。
  // 实测（2026-11-03）：条 3 的视频 256.4MB，封面步骤时视频区还显示
  // 「已上传：256.4MB/256.4MB 当前速度：3.6MB/s 剩余时间：>1天」——
  // 字节满了但平台没切到「上传完成」态。
  // 半成品的素材进草稿 = 抖音那条「转码完成是假绿灯」的同一个坑。
  console.log('   ⏳ 等待视频上传完成…')
  if (!(await waitVideoUploaded(page))) {
    return bail(res, page, logDir, `${tag}-upload`, '视频未上传完成（已中止投稿）', '视频没传完 → 中止，不存半成品草稿')
  }
  console.log('   ✓ 视频已上传完成')

  // 封面：优先换成预制带文字版。
  //
  // 三种结局要分开处理（`setBiliCover` 的文档里写了为什么）：
  // - 'custom' 换成我们的封面，继续
  // - 'auto'   B 站封面编辑器偶发吞图 ⇒ 草稿用平台自动取帧。**不中止**，但结果里必须写明
  // - 'failed' 封面位或「封面制作」弹窗都打不开 ⇒ 页面结构变了，fail-closed
  const cover = await setBiliCover(page, cov, tag, { logDir })
  res['cover'] = cover
  if (cover === 'failed') {
    console.log(`      预制封面：${cov}`)
    return bail(res, page, logDir, tag, '封面编辑器打不开（已中止投稿）', '封面编辑器打不开 → 中止本条，不点投稿')
  }
  if (cover === 'auto') {
    console.log('   ⚠️ 封面 = 平台自动取帧（指定帧没设上；草稿照样保存，交付里会列出这些集）')
  } else {
    console.log(`   ✓ 封面已定为视频第 ${coverSecondOf(cov)}s 帧`)
  }

  // 定时发布预置（可选）：把「几点发」写进稿件。
  // 放在封面之后、提交键解禁之前——这个开关会改变提交键的解禁条件。
  // ⚠️ 存草稿模式下也照填：草稿里带着预置时刻，人点投稿才按此刻发出。
  if (opts.publishAt) {
    const schedOk = await setBiliPublishAt(page, opts.publishAt, { logDir, tag })
    if (!schedOk) {
      return bail(res, page, logDir, `${tag}-schedule`, '定时发布未生效（已中止投稿）',
        '定时发布时刻没设上 → 中止，不投')
    }
  }

  // 等投稿按钮解禁
  console.log('   ⏳ 等待提交按钮解禁…')
  let ok = false
  for (let i = 0; i < 90; i++) {
    const [el, txt] = await submitBtn(page)
    if (el !== null && (await el.getAttribute('disabled')) === null) {
      ok = true
      console.log(`   ✓ 提交键「${txt}」已可用`)
      break
    }
    await clock.sleep(1)
  }
  if (!ok) {
    if (!opts.draft) {
      res['stage'] = '提交按钮未就绪'
      console.log('   ❌ 提交按钮未就绪')
      await dumpSubmitCandidates(page)
      try {
        await page.screenshot({ path: join(logDir, `coverfail-bili-${base.pad2(t['no'])}-submit.png`) })
      } catch {
        // 截图只是留证
      }
      return res
    }
    // 存草稿模式：提交键未解禁也先试存草稿（草稿键若在就存，找不到就 fail-closed）
    console.log('   ⚠️ 提交键未解禁，仍尝试存草稿')
  }

  if (!auto) {
    return base.dryRunStop(page, res, {
      logDir,
      shotName: `dryrun-bili-${base.pad2(t['no'])}.png`,
      blocking: () => blocking(page),
    })
  }

  // 存草稿模式：填完点「保存草稿」就停，**绝不点投稿**（找不到草稿键 = 放弃本条）
  if (opts.draft) {
    // timeoutS 给足：B站的落库信号是**跳转到草稿箱**，大文件那条可能要等一会儿
    return draft.saveDraft(page, res, { platform: 'bilibili', logDir, no: t['no'], timeoutS: 90 })
  }

  return submitAndConfirm(page, res, t, { logDir })
}

export interface BiliPublishOpts {
  profileDir?: string | null
  logDir: string
  subsDir?: string | null
  only?: string | null
  frm?: number | null
  dryRun?: number
  headless?: boolean
  /** 存草稿模式：填完存草稿就停，不点投稿。 */
  draft?: boolean
  /** 本批用户拍板的分区与创作声明；不给才走兼容默认值。 */
  zone?: string
  statement?: string
  /**
   * 稿件侧的**定时发布时刻**（'YYYY-MM-DD HH:mm'）。
   *
   * 与 --draft 的分工：--draft 决定**终点**（存草稿、不点投稿），
   * publishAt 决定**稿件里预置的时刻**——人工点投稿后按此刻定时发出。
   * 两者一起用 = 「每天 9 点定时发布、但由人点投稿」那条日更产线。
   */
  publishAt?: string | null
  /** 固定用 user-data-dir 里的哪一个 profile 目录（见 base.LaunchOpts.profileName）。 */
  profileName?: string | null
  /** 等风控解除的分钟数（人工过短信验证）；不给 = 10 分钟。 */
  riskWaitMin?: number
}

/** 批量投稿（骨架在 base.runTasks：异常隔离 + 循环内节流 + result JSON）。 */
export async function publish(tasks: readonly base.Task[], opts: BiliPublishOpts): Promise<number> {
  const filtered = base.filterTasks(tasks, opts.only ?? null, opts.frm ?? null)
  const profileDir = opts.profileDir || base.profileDir('bilibili')
  const subsDir = opts.subsDir ?? null

  let loginOk = true
  // 草稿箱满而整批未开跑：与「登录超时」同级的前置失败，退出码必须非 0，
  // 否则上游会把「一条都没存」读成「成功跑完 0 条」。
  let draftBoxBlocked = false
  let results: base.PubResult[] = []
  await base.launch(
    profileDir,
    {
      headless: opts.headless ?? false,
      viewport: { width: 1600, height: 1000 },
      profileName: opts.profileName ?? null,
    },
    async (ctx, page) => {
      // 提前授予通知权限，否则上传完会弹浏览器级授权框盖住整个表单
      try {
        await ctx.grantPermissions(['notifications'], { origin: 'https://member.bilibili.com' })
        console.log('✓ 已授予通知权限（避免上传完成弹授权框）')
      } catch (e) {
        console.log(`⚠️ 授予通知权限失败：${base.errName(e)}`)
      }
      await page.goto(UPLOAD_URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
      await clock.sleep(5)
      if (await base.loginWall(page, BILI_WALL)) {
        console.log('⚠️ B站未登录，请在弹出的 Chrome 窗口扫码')
        if (!(await base.waitLogin(page, 600, { kws: BILI_WALL }))) {
          console.log('❌ 登录超时')
          loginOk = false
          return
        }
      }
      console.log('✅ B站创作中心就绪\n')

      // 存草稿模式的**前置闸**：草稿箱有条数上限，满了再传视频是纯浪费——
      // 上传要几十秒，而落库一定失败（平台弹「最多保存N个稿件」，本条不入库）。
      // 先在草稿箱页读平台自报的条数，到顶就整批不跑。
      // 读不到条数（null）不作为阻塞理由：那是判据自身的问题，不该冒充「箱子空」。
      if (opts.draft) {
        const cap = draft.DRAFT_CAPACITY['bilibili'] ?? 0
        const occupied = await countDrafts(page)
        if (occupied !== null && cap > 0) {
          console.log(`· 草稿箱占用 ${occupied}/${cap}`)
          if (occupied >= cap && IGNORE_DRAFT_CAP) {
            console.log('⚠️ BILI_IGNORE_DRAFT_CAP=1：满箱仍继续（这是一次实验，可能白传一条）')
          } else if (occupied >= cap) {
            console.log(`❌ 草稿箱已满（${occupied}/${cap}）⇒ 不上传、不存草稿`)
            console.log('   处置：先在草稿箱投稿或删除一条腾出位置；平台上限不腾出就存不进去。')
            draftBoxBlocked = true
            return
          }
        } else {
          console.log('⚠️ 读不到草稿箱条数（不影响本次，但满了会以上传后失败的形式暴露）')
        }
      }

      const one: base.PublishOneFn = (p, t, auto, o) =>
        publishOne(p, t, auto, {
          logDir: o.logDir, subsDir, draft: o.draft, zone: opts.zone, statement: opts.statement,
          publishAt: opts.publishAt ?? null, riskWaitMin: opts.riskWaitMin,
        })

      results = await base.runTasks(page, filtered, one, {
        uploadUrl: UPLOAD_URL,
        logDir: opts.logDir,
        betweenS: 4,
        dryRun: opts.dryRun ?? 0,
        draft: opts.draft ?? false,
        resultJson: 'publish-bilibili-result.json',
      })
    },
  )
  if (!loginOk) return 1
  // 草稿箱满：整批一条没跑，必须非 0（别让上游把「0 条」当「跑完了」）。
  // 退出码 3 与 argparse(2) / 单条失败(1) 区分开，便于产线脚本按码分流。
  if (draftBoxBlocked) return 3
  return base.summarize(results, 'B站')
}

// ── CLI 适配层（CLI 路由叶子；业务在 publish()，这里只接线） ──────────

/**
 * CLI 路由入口：`feuille publish bilibili <manifest.json> --log-dir D`。
 *
 * manifest.json = plans 契约经 `manifest.build_manifest` 落盘的清单，
 * 本入口取其中的 "bilibili" 段作为 tasks。
 */
export async function main(argv: string[]): Promise<number> {
  const a = base.manifestArgs(argv, 'feuille publish bilibili', { subsDir: true, publishAt: true })
  if ('rc' in a) return a.rc
  const tasks = base.manifestTasks(a.manifest, 'bilibili')
  return publish(tasks, {
    logDir: a.logDir,
    subsDir: a.subsDir,
    only: a.only,
    frm: a.frm,
    dryRun: a.dryRun,
    headless: a.headless,
    draft: a.draft,
    publishAt: a.publishAt,
    profileName: a.profileName,
  })
}
