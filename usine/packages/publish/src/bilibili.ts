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
import { existsSync } from 'node:fs'
import { basename, join } from 'node:path'

import * as base from './base.js'
import * as clock from './clock.js'

export const UPLOAD_URL = 'https://member.bilibili.com/platform/upload/video/frame'
export const BILI_WALL: readonly string[] = ['扫码登录', '密码登录', '手机号登录', '登录后']

// 必填项取值。分区与创作声明由用户明确指定：
//   分区 = 知识；创作声明 = 自制/原创（不标注 AI 生成）
export const BILI_ZONE = '知识'
// 必填的「创作声明」只认这 6 项之一。
// ⚠️ 「内容为自制：未经作者允许，禁止转载」属于**非必选**的「内容授权声明」，
// 勾上它**填不满必填字段**——点「立即投稿」会报红字「请添加创作声明」，
// 稿件一条都投不出去。栽过：日志打「✓ 创作声明 = …」是假阳性，
// 蓝色对勾只是版权声明的选中态，必填框仍是占位符。
export const BILI_STMT_REQUIRED: readonly string[] = [
  '内容无需标注', '含AI生成内容', '含虚构演绎内容',
  '内容含营销信息', '个人观点，仅供参考', '内容为转载',
]
// 用户指定：不标注 AI 生成 + 保留「自制」版权声明，两者同时勾。
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
    const btns = await page.evaluate(`() => {
          const out=[];
          document.querySelectorAll('button').forEach(el=>{
            const r=el.getBoundingClientRect();
            if(r.width<20||r.height<10) return;
            const cs=getComputedStyle(el);
            if(cs.display==='none'||cs.visibility==='hidden') return;
            out.push({t:(el.innerText||'').trim().slice(0,20),
                      cls:(el.className||'').toString().slice(0,60),
                      dis: el.disabled===true, y:Math.round(r.y)});
          });
          return out;
        }`)
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
 * 把预制带文字封面设上去。**必须上传成功且裁切框里看得见文字**。
 *
 * B 站的封面不是 file input：表单上那个 `* 封面` 是 `div.cover-empty` 的
 * 「+ 添加封面」占位块，点了才弹出「封面制作」编辑器；编辑器底部才有
 * 「上传封面 · 拖拽图片或点击上传」，对应 `cover-editor-panel-select-`
 * 下的 `input[type=file][accept='image/png, image/jpeg']`。
 * 弹窗里那排缩略图是「智能生成封面 / 系统推荐封面」——**不许用**。
 *
 * 编辑器有 4:3（首页推荐）和 16:9（个人空间）两个裁切框，两边都得有文字。
 */
export async function setBiliCover(
  page: base.AnyPage,
  coverPath: string,
  tag: string,
  opts: { logDir: string },
): Promise<boolean> {
  const logDir = opts.logDir
  // 1) 打开「添加封面」
  let pill: any = null
  for (const sel of ["div[class*='cover-empty-pill']", "div[class*='cover-empty']", "div[class*='cover-slot']"]) {
    const loc = page.locator(sel).first()
    try {
      if (await base.visibleWithin(loc, 1500)) {
        pill = loc
        break
      }
    } catch {
      continue
    }
  }
  if (pill === null) {
    console.log('      ⚠️ 找不到「添加封面」入口')
    return false
  }
  await pill.scrollIntoViewIfNeeded()
  await clock.sleep(0.8)
  await pill.click()
  await clock.sleep(3.5)

  const dlg = page.getByText('封面制作', { exact: true }).first()
  try {
    if (!(await base.visibleWithin(dlg, 4000))) {
      console.log('      ⚠️ 「封面制作」弹窗没开')
      await page.screenshot({ path: join(logDir, `coverfail-bili-${tag}-nomodal.png`) })
      return false
    }
  } catch {
    console.log('      ⚠️ 「封面制作」弹窗没开')
    return false
  }
  console.log('      · 已打开「封面制作」')

  // 2) 喂给编辑器里那个图片上传口
  let up = page.locator("div[class*='cover-editor-panel-select'] input[type='file']").first()
  try {
    if (!(await up.count())) up = page.locator("input[type='file'][accept*='image']").first()
    await up.setInputFiles(coverPath, { timeout: 15000 })
    console.log('      · 封面文件已送入上传口')
  } catch (e) {
    console.log(`      ⚠️ 上传口喂不进去：${base.errName(e)}`)
    await page.screenshot({ path: join(logDir, `coverfail-bili-${tag}-noup.png`) })
    return false
  }
  await clock.sleep(5)
  await page.screenshot({ path: join(logDir, `bilicov-${tag}-uploaded.png`) })

  // 3) 选中新加的那张（它会落在底部胶片条上），否则裁切框仍是旧帧
  try {
    const strip = page.locator("div[class*='cover-editor'] img").last()
    await strip.click({ timeout: 4000 })
    await clock.sleep(2)
    console.log('      · 已选中新上传的封面')
  } catch {
    console.log('      ⚠️ 没能点中新缩略图（可能上传后已自动选中）')
  }
  await clock.sleep(1.5)
  await page.screenshot({ path: join(logDir, `bilicov-${tag}-selected.png`) })

  // 4) 完成
  let done = false
  for (const kw of ['完成', '确定', '保存']) {
    try {
      const b = page.getByText(kw, { exact: true })
      const n = Math.min(await b.count(), 6)
      for (let i = 0; i < n; i++) {
        const el = b.nth(i)
        if (!(await base.visibleWithin(el, 500))) continue
        await el.click({ timeout: 5000 })
        console.log(`      · 已点「${kw}」`)
        await clock.sleep(3)
        done = true
        break
      }
      if (done) break
    } catch {
      continue
    }
  }
  if (!done) {
    console.log('      ⚠️ 找不到确认键')
    await page.screenshot({ path: join(logDir, `coverfail-bili-${tag}-noconfirm.png`) })
    return false
  }

  await clock.sleep(2)
  // 5) 判据：表单上那个封面位不该还是「添加封面」空块
  let stillEmpty = false
  try {
    stillEmpty = await base.visibleWithin(page.locator("div[class*='cover-empty-pill']").first(), 2500)
  } catch {
    stillEmpty = false
  }
  if (stillEmpty) {
    console.log('      ⚠️ 确认后封面位仍是空的 → 未生效')
    await page.screenshot({ path: join(logDir, `coverfail-bili-${tag}-stillempty.png`) })
    return false
  }
  console.log('      ✓ 封面已设置（占位块消失）')
  await page.screenshot({ path: join(logDir, `bilicov-${tag}-done.png`) })
  return true
}

/**
 * 用 DOM 直接派发 click，绕开 Playwright 的 actionability 检查。
 *
 * B 站这两个下拉框有进场动画，Playwright 判定 element is not stable，
 * 普通 click 会一直重试到超时（栽过）。DOM click 立刻生效。
 */
export async function jsClick(page: base.AnyPage, locator: any): Promise<boolean> {
  try {
    await locator.evaluate('e => e.click()')
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
 * 用户明确指示：选「自制 / 原创」，不标注 AI 生成。
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

  // 把浮层里所有可点的选项文本捞出来
  // 创作声明不是下拉浮层，是点开后**内联**在页面上的选项列表，
  // 用 dropdown/popup 那套选择器读不到（栽过）。改成扫视口内可见文本。
  let candList: string[] = await page.evaluate(`() => {
      const out=[];
      document.querySelectorAll('body *').forEach(el=>{
        const r=el.getBoundingClientRect();
        if(r.width<6||r.height<6) return;
        if(r.y<0||r.y>window.innerHeight) return;
        const cs=getComputedStyle(el);
        if(cs.display==='none'||cs.visibility==='hidden') return;
        const own=[...el.childNodes].filter(n=>n.nodeType===3)
                    .map(n=>n.textContent.trim()).join('').trim();
        if(own&&own.length<40&&!out.includes(own)) out.push(own);
      });
      return out;
    }`)
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

  /** 在已展开的浮层里点中 target，并以「是否回写到 input」为准。 */
  const pick = async (target: string): Promise<boolean> => {
    let el: any = null
    for (const selStr of [
      'ul.bcc-select-option-list article.option-hover-tips span.option-text',
      'ul.bcc-select-option-list li.bcc-option span',
    ]) {
      const cand = page.locator(selStr).filter({ hasText: target })
      try {
        if (await cand.count()) {
          el = cand.first()
          break
        }
      } catch {
        continue
      }
    }
    if (el === null) return false
    try {
      await el.scrollIntoViewIfNeeded()
      await clock.sleep(0.3)
      const bb = await el.boundingBox()
      if (!bb) return false
      // 真实鼠标点击：JS 合成 click 触发不了 Vue 的选项事件
      await page.mouse.click(bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2)
      await clock.sleep(1.5)
    } catch {
      return false
    }
    return (await curValue()) === target
  }

  // ① 必填项：必须真的回写到 input 才算数。
  //    「内容为自制…」在**非必选**的版权声明区，勾上它填不满必填框，
  //    点提交会报红字「请添加创作声明」，稿件一条都投不出去。
  let want: string | null = null
  for (const kw of keywords) {
    for (const o of candList) {
      if (o.includes(kw)) {
        want = o
        break
      }
    }
    if (want) break
  }
  if (!want) {
    // Python 打印的是 tuple repr（圆括号），不是 list repr
    console.log(`   ⚠️ 必填声明选项里没有含 (${keywords.map((k) => `'${k}'`).join(', ')}) 的`)
    return ''
  }
  if (!(await pick(want))) {
    console.log(`   ⚠️ 必填声明「${want}」点了但没进框里`)
    return ''
  }
  console.log(`   ✓ 必填创作声明 = ${want}`)

  // ② 选填：用户指定的版权声明，勾上但不作必填依据
  try {
    if (candList.includes(BILI_STMT_OPTIONAL)) {
      // Python page.evaluate("e => e.click()", locator) 把元素传参进 JS；
      // JS Playwright 的 evaluate 不吃 locator 参数——同一语义就是 jsClick。
      await jsClick(page, page.locator('div.statement-main div.bcc-select').first())
      await clock.sleep(1.8)
      const o2: string[] = await page.evaluate(`() => {
              const out=[];
              document.querySelectorAll('ul.bcc-select-option-list span')
                .forEach(s => { const t=(s.innerText||'').trim();
                                if(t&&!out.includes(t)) out.push(t); });
              return out;
            }`)
      if (o2.includes(BILI_STMT_OPTIONAL) && (await pick(BILI_STMT_OPTIONAL))) {
        console.log(`   ✓ 另勾版权声明：${BILI_STMT_OPTIONAL}`)
      } else {
        console.log('   ⚠️ 版权声明没勾上（不影响必填）')
      }
      await page.keyboard.press('Escape')
      await clock.sleep(1.2)
    } else {
      console.log('   （浮层里没有版权声明项，跳过）')
    }
  } catch (e) {
    console.log(`   ⚠️ 补勾版权声明异常：${base.errName(e)}`)
  }

  if ((await curValue()) !== want) {
    console.log(`   ⚠️ 收尾校验：必填框现在是「${(await curValue()) || '空'}」`)
    return ''
  }
  return want
}

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
    console.log(stage === '已发布' ? `   ✅ ${stage}` : `   ✅ 已跳转 ${page.url}`)
  } else {
    console.log(`   ⚠️ 已提交但未确认，URL=${page.url}`)
  }
  return res
}

export async function publishOne(
  page: base.AnyPage,
  t: base.Task,
  auto: boolean,
  opts: { logDir: string; subsDir?: string | null },
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

  // 标题（纪律 19：录不进标题 = 带病发布，中止本条）
  if (!(await base.fillTitle(page, titleBox, t['title'], { limit: 80 }))) {
    return bail(res, page, logDir, `${tag}-title`, '标题未录入（已中止投稿）', '标题没录进去 → 中止，不投')
  }

  // 必填项：分区 + 创作声明（B 站不填这两个 投稿键不解禁）
  if (!(await setBiliZone(page, BILI_ZONE))) {
    return bail(res, page, logDir, `${tag}-zone`, '主分区未生效（已中止投稿）', '主分区没设上 → 中止，不投')
  }
  if (!(await setBiliStatement(page, BILI_STMT_REQUIRED, { logDir }))) {
    return bail(res, page, logDir, `${tag}-stmt`, '创作声明未选定（已中止投稿）', '创作声明没选上 → 中止，不投')
  }

  // 简介：B站正文是 contenteditable；正文+话题录不进 = 带病发布（纪律 19）
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
  if (!(await base.fillBody(page, desc, t['body'], { tags: t['tags'], pause: 0.3 }))) {
    return bail(res, page, logDir, `${tag}-desc`, '简介未录入（已中止投稿）', '简介没录进去 → 中止，不投')
  }

  await uploadSubtitle(page, t, subsDir)

  // 封面：必须换成预制带文字版，不允许退回视频首帧或系统推荐封面
  const coverOk = await setBiliCover(page, cov, tag, { logDir })
  if (!coverOk) {
    console.log(`      预制封面：${cov}`)
    return bail(res, page, logDir, tag, '封面未生效（已中止投稿）', '封面未生效 → 中止本条，不点投稿')
  }
  console.log('   ✓ 封面已是预制带文字版，继续')

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

  if (!auto) {
    return base.dryRunStop(page, res, {
      logDir,
      shotName: `dryrun-bili-${base.pad2(t['no'])}.png`,
      blocking: () => blocking(page),
    })
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
}

/** 批量投稿（骨架在 base.runTasks：异常隔离 + 循环内节流 + result JSON）。 */
export async function publish(tasks: readonly base.Task[], opts: BiliPublishOpts): Promise<number> {
  const filtered = base.filterTasks(tasks, opts.only ?? null, opts.frm ?? null)
  const profileDir = opts.profileDir || base.profileDir('bilibili')
  const subsDir = opts.subsDir ?? null

  let loginOk = true
  let results: base.PubResult[] = []
  await base.launch(
    profileDir,
    { headless: opts.headless ?? false, viewport: { width: 1600, height: 1000 } },
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

      const one: base.PublishOneFn = (p, t, auto, o) =>
        publishOne(p, t, auto, { logDir: o.logDir, subsDir })

      results = await base.runTasks(page, filtered, one, {
        uploadUrl: UPLOAD_URL,
        logDir: opts.logDir,
        betweenS: 4,
        dryRun: opts.dryRun ?? 0,
        resultJson: 'publish-bilibili-result.json',
      })
    },
  )
  if (!loginOk) return 1
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
  const a = base.manifestArgs(argv, 'feuille publish bilibili', { subsDir: true })
  if ('rc' in a) return a.rc
  const tasks = base.manifestTasks(a.manifest, 'bilibili')
  return publish(tasks, {
    logDir: a.logDir,
    subsDir: a.subsDir,
    only: a.only,
    frm: a.frm,
    dryRun: a.dryRun,
    headless: a.headless,
  })
}
