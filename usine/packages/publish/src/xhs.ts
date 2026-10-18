// xhs.ts — 小红书发布器（⑨）：像素探测发布键 + 风控停等 + 每条 reset_page
// （publish/xhs.py 的 TS 移植）。
//
// **发布键为什么用像素探测**：底栏「发布」不在主文档流里（get_by_text /
// querySelectorAll / elementFromPoint 全扫不到，很可能是跨源 iframe 合成层），
// 唯一可信的证据是**真实像素**——品牌红 #FF2442 的实心药丸（见 submitBtn）。
//
// 防风控节流在 `base.runTasks` 循环内（between_s=35）——连发 2 条就撞风控
// 是实测教训，节流必须在每条之间。
//
// 使用契约：
// - tasks 是 `manifest.build_manifest` 的产物；profile 默认
//   `base.PROFILES['xiaohongshu']`；截图与 result JSON 全部落 logDir。
// - 封面是硬闸门：换不上预制带文字版就整条不发（纪律 19）。
// - 风控撞上**绝不自动重试**（纪律 21）：停下等你本人扫码，解除后确认遮罩消失。
import { existsSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'

import * as base from './base.js'
import * as clock from './clock.js'

export const UPLOAD_URL = 'https://creator.xiaohongshu.com/publish/publish'

// 小红书登录墙/风控/成功词表（实测）
export const XHS_WALL: readonly string[] = ['扫码登录', '验证码登录', '手机号登录', '立即登录']
export const XHS_SUCCESS_WORDS: readonly string[] = ['发布成功', '提交成功', '笔记已发布']

/**
 * 每条开始前强制回到干净的投稿页。
 *
 * 这不是洁癖，是实测踩出来的坑：风控「Scan to verify」弹窗扫完之后，
 * 页面会留下一层 `d-modal-mask` + WebGL canvas 不消失，把后续所有点击
 * 都拦下来（Playwright 报 'intercepts pointer events'）。原先只在
 * URL 不匹配时才 goto，于是脏状态跨条污染——第 5 条的编辑器里躺着的
 * 还是第 3 条的德语封面。
 */
export async function resetPage(page: base.AnyPage, label = ''): Promise<boolean> {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await page.goto(UPLOAD_URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
    } catch (e) {
      console.log(`   ⚠️ 重置导航失败 ${base.errName(e)}`)
      await clock.sleep(3)
      continue
    }
    await clock.sleep(6)
    const blocked = await base.modalMask(page)
    if (!blocked || blocked['disp'] === 'none' || (blocked['w'] ?? 0) < 50) return true
    console.log(`   ⚠️ 残留遮罩 ${JSON.stringify(blocked)}${label ? ` ${label}` : ''}，重置第 ${attempt + 1} 次`)
    await page.keyboard.press('Escape')
    await clock.sleep(1.5)
  }
  return false
}

/** 切到「上传视频」页签。小红书默认可能是图文页。 */
export async function pickTab(page: base.AnyPage, name: string): Promise<boolean> {
  try {
    const loc = page.getByText(name, { exact: true })
    const n = Math.min(await loc.count(), 6)
    for (let i = 0; i < n; i++) {
      const el = loc.nth(i)
      if (await base.visibleWithin(el, 800)) {
        await el.click()
        await clock.sleep(3)
        return true
      }
    }
  } catch {
    // 按原样镜像：页签不在是常态
  }
  return false
}

// 品牌红像素判据的阈值（实测校准过：底栏药丸 #FF2442）。
// 集中成常量——平台改版后重摸 DOM 时，调参只动这一处。
const RED_MIN_PIXELS = 800 // 少于这个数说明不是那颗实心药丸
const RED_MIN_W = 60
const RED_MIN_H = 24
const RED_MAX_W = 300
const RED_MAX_H = 80

/**
 * 把 Playwright 截图喂回浏览器，用 canvas 解码，**一次扫描**同时量出
 * 底栏品牌红像素数与包围盒。
 *
 * 为什么要绕这一圈：底栏「发布」既不在主文档流里（elementsFromPoint /
 * querySelectorAll / get_by_text 全部扫不到，很可能是跨源 iframe 合成层），
 * 但 Playwright 截图能合成出来。所以唯一可信的证据就是**真实像素**。
 * 这里不依赖成像库（发布环境可能没装），改用浏览器自带的 canvas。
 *
 * 为什么必须单帧单扫：判定几何与点击坐标必须出自同一张截图——
 * 分开截两张，期间页面一动（懒渲染/弹层浮动），两边就对不上号了。
 */
async function pixelProbe(page: base.AnyPage, b64: string): Promise<Record<string, any>> {
  return await page.evaluate(`async (b64) => {
      const img = new Image();
      img.src = 'data:image/png;base64,' + b64;
      try { await img.decode(); } catch (e) { return {err: 'decode:' + e}; }
      const c = document.createElement('canvas');
      c.width = img.width; c.height = img.height;
      const ctx = c.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      const H = c.height, W = c.width;
      const y0 = Math.max(0, H - 90), y1 = H - 2;
      const d = ctx.getImageData(0, y0, W, y1 - y0).data;
      const iw = W, ih = y1 - y0;
      // 小红书品牌红 #FF2442
      let n = 0, minx = 1e9, maxx = -1, miny = 1e9, maxy = -1;
      for (let y = 0; y < ih; y++) {
        for (let x = 0; x < iw; x++) {
          const o = (y * iw + x) * 4;
          const r = d[o], g = d[o+1], b = d[o+2];
          if (r > 220 && g < 90 && b < 105 && (r - g) > 140) {
            n++;
            if (x < minx) minx = x;
            if (x > maxx) maxx = x;
            if (y < miny) miny = y;
            if (y > maxy) maxy = y;
          }
        }
      }
      const box = n ? {x0: minx, x1: maxx, y0: miny + y0, y1: maxy + y0, n} : null;
      return { W, H, n, scanY: [y0, y1], box };
    }`, b64)
}

export type RedBox = [number, number, number, number] // x0, y0, x1, y1

/** 在底栏里框出品牌红药丸，返回 [中心x, 中心y, 红像素数, 包围盒]。 */
export async function findRedButton(
  page: base.AnyPage,
): Promise<[number, number, number, RedBox] | null> {
  const shot = await page.screenshot()
  const info = await pixelProbe(page, Buffer.from(shot).toString('base64'))
  if (info['err']) {
    console.log(`   ⚠️ 截图解码失败 ${info['err']}`)
    return null
  }
  const n: number = info['n'] ?? 0
  if (n < RED_MIN_PIXELS) {
    // 抑制重复的「未找到」噪音：轮询期间同一状态只提示一次
    const msg = `底栏红像素 ${n}（阈值 ${RED_MIN_PIXELS}）`
    if (msg !== lastHint) {
      console.log(`   · ${msg}，不认定`)
      lastHint = msg
    }
    return null
  }

  const box = info['box']
  if (!box) return null
  const cx = Math.floor((box['x0'] + box['x1']) / 2)
  const cy = Math.floor((box['y0'] + box['y1']) / 2)
  const bw = box['x1'] - box['x0']
  const bh = box['y1'] - box['y0']
  if (bw < RED_MIN_W || bh < RED_MIN_H || bw > RED_MAX_W || bh > RED_MAX_H) {
    console.log(`   · 红块尺寸 ${bw}x${bh} 不像按钮，不认定`)
    return null
  }
  return [cx, cy, box['n'], [box['x0'], box['y0'], box['x1'], box['y1']]]
}

// find_red_button._last_hint 的模块级落点（Python 函数属性移植）
let lastHint = ''

export type SubmitBtn =
  | { kind: 'loc'; el: any }
  | { kind: 'xy'; x: number; y: number }

/**
 * 发布键：底栏右侧的小红书红药丸「发布」。
 *
 * 这个按钮的怪癖（连踩五轮实测）：
 *   - get_by_text('发布') count=0
 *   - querySelectorAll('*') 全文遍历也找不到
 *   - document.elementFromPoint 在视口底部扫不到
 * → 它不在主文档的可命中区域里（很可能是跨源 iframe / 合成层），
 *   但 Playwright 截图能合成出来。
 * 所以唯一可信的判据是**真实像素**：在底栏找品牌红 #FF2442 的实心药丸。
 * 找不到就不点，宁可不发布。
 */
export async function submitBtn(page: base.AnyPage): Promise<[SubmitBtn | null, string | null]> {
  // 先试文本（万一以后 DOM 改了能命中）
  for (const cand of ['发布', '提交']) {
    try {
      const loc = page.getByText(cand, { exact: true })
      const n = Math.min(await loc.count(), 8)
      for (let i = 0; i < n; i++) {
        const el = loc.nth(i)
        if (!(await base.visibleWithin(el, 400))) continue
        const b = await el.boundingBox()
        if (b && b['x'] > 400 && b['y'] > 600) return [{ kind: 'loc', el }, cand]
      }
    } catch {
      continue
    }
  }

  const r = await findRedButton(page)
  if (r === null) return [null, null]
  const [cx, cy, n, box] = r
  console.log(
    `   · 像素命中：红色药丸 ${box[2] - box[0]}x${box[3] - box[1]} @(${cx},${cy}) 红像素 ${n}`,
  )
  return [{ kind: 'xy', x: cx, y: cy }, '发布']
}

export async function blocking(page: base.AnyPage): Promise<string[]> {
  const out: string[] = []
  for (const [sel, name] of [
    [".semi-modal button:has-text('确定')", '确定弹窗'],
    ["button:has-text('去发布')", '去发布提示'],
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
 * 小红书封面画布是 3:4。优先用预裁好的 3:4 版（零裁切，位置与裁切审计一致），
 * 没有就退回 9:16 原图让平台自己适配。
 *
 * altDir/fromSize/toSize 是**调用方**的素材目录约定（封面 9:16 与预裁 3:4
 * 分放两个目录、同名不同尺寸后缀），参数化不写死。
 */
export function pickCover(
  cov: string,
  opts: { altDir?: string; fromSize?: string; toSize?: string } = {},
): string {
  const altDir = opts.altDir ?? 'covers-3x4'
  const fromSize = opts.fromSize ?? '1080x1920'
  const toSize = opts.toSize ?? '1080x1440'
  const alt = join(
    dirname(dirname(cov)),
    altDir,
    basename(cov).replace(`_${fromSize}.png`, `_${toSize}.png`),
  )
  return existsSync(alt) ? alt : cov
}

/**
 * 换封面：hover 缩略图 → 点「编辑封面」→ 「+ 上传」喂预制图 → 「完成」。
 *
 * 真实结构（probe_xhs_cover4 实测）：
 * .default--ai-cover-layout  封面缩略图（默认是纯叶子的视频首帧）
 * .cover-edit-entry          hover 才显形的「编辑封面」按钮
 * .upload-slot > .upload-label「上传」  编辑器底部「+ 上传」
 * input[type=file][accept*=image]     编辑器打开后才动态挂上
 * 「完成」按钮
 * 注意：编辑器里还有「✨生成封面」「✨获取封面建议」两个 AI 入口，一律不碰。
 */
export async function setXhsCover(page: base.AnyPage, cov: string): Promise<boolean> {
  // 1) 滚到封面区
  await page.evaluate(`() => {
        const t = document.querySelector('.cover-plugin-title');
        if (t) t.scrollIntoView({block: 'center'});
    }`)
  await clock.sleep(1.2)

  const thumb = page.locator('.default--ai-cover-layout').first()
  let tb: any = null
  try {
    // Python bounding_box(timeout=8000) 会先等可见；JS boundingBox() 即时——先 waitFor 补齐
    await thumb.waitFor({ state: 'visible', timeout: 8000 })
    tb = await thumb.boundingBox()
  } catch (e) {
    console.log(`   ⚠️ 封面缩略图没出现：${base.errName(e)}`)
    return false
  }
  if (!tb) {
    console.log('   ⚠️ 封面缩略图无尺寸')
    return false
  }

  // 2) hover 让「编辑封面」显形，再点它
  await page.mouse.move(tb['x'] + tb['width'] / 2, tb['y'] + tb['height'] / 2)
  await clock.sleep(1.0)
  const entry = page.locator('.cover-edit-entry').first()
  let eb: any = null
  try {
    // 同上：JS boundingBox() 无 timeout，先 waitFor 补齐 Python bounding_box(timeout) 语义
    await entry.waitFor({ state: 'visible', timeout: 4000 })
    eb = await entry.boundingBox()
  } catch {
    eb = null
  }
  if (!eb) {
    console.log('   ⚠️ hover 后「编辑封面」未显形')
    return false
  }
  await page.mouse.move(eb['x'] + eb['width'] / 2, eb['y'] + eb['height'] / 2)
  await clock.sleep(0.3)
  await page.mouse.click(eb['x'] + eb['width'] / 2, eb['y'] + eb['height'] / 2)
  console.log('   ✓ 打开封面编辑器')

  // 3) 等编辑器里的图片 file input 挂上来
  const imgIn = page.locator("input[type='file'][accept*='image']").first()
  try {
    await imgIn.waitFor({ state: 'attached', timeout: 15000 })
  } catch {
    console.log('   ⚠️ 编辑器里没出现图片上传口')
    return false
  }
  await clock.sleep(1.0)
  await imgIn.setInputFiles(cov)
  console.log(`   ✓ 预制封面已送入 ${basename(cov)}`)
  await clock.sleep(4.0)

  // 4) 「完成」
  for (const kw of ['完成', '确定', '保存']) {
    const loc = page.getByText(kw, { exact: true })
    const n = Math.min(await loc.count(), 6)
    for (let i = 0; i < n; i++) {
      const el = loc.nth(i)
      try {
        if (!(await base.visibleWithin(el, 500))) continue
        const b = await el.boundingBox()
        if (!b || b['y'] < 600) continue // 「完成」在编辑器右下角
        await el.click()
        console.log(`   ✓ 点「${kw}」关闭编辑器`)
        await clock.sleep(2.5)
        return true
      } catch {
        continue
      }
    }
  }
  console.log('   ⚠️ 找不到「完成」键，封面可能未落库')
  return false
}

/** 重置页面后重走上传 + 填词（封面重试用）。 */
export async function republishAfterReset(page: base.AnyPage, t: base.Task): Promise<boolean> {
  const vid = t['video']
  try {
    await pickTab(page, '上传视频')
    const fis = page.locator("input[type='file']").first()
    await fis.setInputFiles(vid)
    const tb = page.locator("input[placeholder*='标题']").first()
    let vis = false
    for (let i = 0; i < 140; i++) {
      if (await base.visibleWithin(tb, 600)) {
        vis = true
        break
      }
      await clock.sleep(1.5)
    }
    if (!vis) return false
    for (const kw of ['我知道了', '知道了']) {
      const loc = page.getByText(kw, { exact: true })
      const n = Math.min(await loc.count(), 3)
      for (let i = 0; i < n; i++) {
        try {
          if (await base.visibleWithin(loc.nth(i), 500)) {
            await loc.nth(i).click()
            await clock.sleep(1.2)
          }
        } catch {
          continue
        }
      }
    }
    await tb.click()
    await tb.fill(base.clip(t['title'], 20))
    const body = page.locator(
      "div[contenteditable='true'], textarea, .ql-editor, "
      + "div[placeholder*='正文'], div[data-placeholder*='正文']",
    ).first()
    if (await base.visibleWithin(body, 3000)) {
      await body.click()
      await base.selectAllClear(page)
      await page.keyboard.type(t['body'])
      await clock.sleep(0.5)
    }
    console.log('   ✓ 重置后已重填标题/正文')
    return true
  } catch (e) {
    console.log(`   ⚠️ 重填失败 ${base.errName(e)}: ${base.clip(base.errStr(e), 80)}`)
    return false
  }
}

export async function publishOne(
  page: base.AnyPage,
  t: base.Task,
  auto: boolean,
  opts: { logDir: string },
): Promise<base.PubResult> {
  const logDir = opts.logDir
  const vid = t['video']
  const cov = pickCover(t['cover'])
  const res: base.PubResult = { no: t['no'], lang: t['lang'], ok: false, stage: '' }
  console.log(`\n🚀 [${base.pad2(t['no'])}] ${t['lang']}  ${basename(vid)}`)
  console.log(`   标题: ${t['title']}`)

  if (!existsSync(vid)) {
    res['stage'] = '素材缺失'
    console.log('   ❌ 视频不存在')
    return res
  }

  // 每条都强制回到干净投稿页（脏状态会跨条污染，见 resetPage 注释）
  if (!(await resetPage(page, `[${base.pad2(t['no'])}]`))) {
    res['stage'] = '页面重置失败'
    console.log('   ❌ 页面重置失败，放弃本条')
    return res
  }
  await pickTab(page, '上传视频')

  const fis = page.locator("input[type='file']")
  if ((await fis.count()) === 0) {
    res['stage'] = '无上传控件'
    console.log('   ❌ 没有 file input')
    return res
  }
  await fis.first().setInputFiles(vid)
  console.log('   ✓ 视频已送入上传通道')

  // 等标题框（上传+校验完成）
  let titleBox: any = null
  for (let i = 0; i < 140; i++) {
    for (const sel of ["input[placeholder*='标题']", "input[placeholder*='写标题']"]) {
      const loc = page.locator(sel).first()
      try {
        if (await base.visibleWithin(loc, 600)) {
          titleBox = loc
          break
        }
      } catch {
        continue
      }
    }
    if (titleBox) break
    await clock.sleep(1.5)
  }
  if (titleBox === null) {
    res['stage'] = '上传/表单未就绪'
    console.log('   ❌ 标题框未出现')
    return res
  }
  console.log('   ✓ 上传完成，编辑表单就绪')

  // 标题（纪律 19：录不进标题 = 带病发布，中止本条；小红书标题上限 20）
  if (!(await base.fillTitle(page, titleBox, t['title'], { limit: 20 }))) {
    res['stage'] = '标题未录入（已中止发布）'
    console.log('   🛑 标题没录进去 → 中止本条，不点发布')
    return res
  }

  // 正文：话题已在 body 末行，整体一次填入（录不进 = 带病发布，纪律 19）
  const body = page.locator(
    "div[contenteditable='true'], textarea, .ql-editor, "
    + "div[placeholder*='正文'], div[data-placeholder*='正文']",
  ).first()
  let bodyReady = false
  try {
    bodyReady = await base.visibleWithin(body, 3000)
  } catch {
    bodyReady = false
  }
  if (!bodyReady) {
    res['stage'] = '正文框未出现（已中止发布）'
    console.log('   🛑 没找到正文框 → 中止本条，不点发布')
    return res
  }
  if (!(await base.fillBody(page, body, t['body']))) {
    res['stage'] = '正文未录入（已中止发布）'
    console.log('   🛑 正文没录进去 → 中止本条，不点发布')
    return res
  }
  await clock.sleep(0.5) // 正文录入后的缓冲：xhs 编辑器对输入事件有节流，立即切封面会丢尾部字符

  // 封面：必须换成预制带文字版（PUBLISH-RULES.md 规则 1）。
  // 小红书默认截视频第一帧，那是纯叶子的画面，不算封面。
  let coverOk = await setXhsCover(page, cov)
  if (!coverOk) {
    // 编辑器开不出来通常是脏状态残留，重置一次再来
    console.log('   ⚠️ 封面首次失败，重置页面重试一次')
    try {
      await page.keyboard.press('Escape')
      await clock.sleep(1.5)
    } catch {
      // Esc 按不按得上都如实继续
    }
    if (await resetPage(page, `[${base.pad2(t['no'])}] 封面重试`)) {
      // 重置后要重走一遍上传与填词
      if (await republishAfterReset(page, t)) {
        coverOk = await setXhsCover(page, cov)
      }
    }
  }

  // 硬闸门：封面没换上就整条不发
  if (!coverOk) {
    res['stage'] = '封面未生效（已中止发布）'
    console.log('   🛑 封面未生效 → 中止本条，不点发布')
    console.log(`      预制封面：${cov}`)
    try {
      await page.screenshot({ path: join(logDir, `coverfail-xhs-${base.pad2(t['no'])}.png`) })
    } catch {
      // 截图只是留证
    }
    return res
  }
  console.log('   ✓ 封面已是预制带文字版，继续')

  console.log('   ⏳ 等待发布键解禁…')
  let btn: SubmitBtn | null = null
  let txt: string | null = null
  for (let k = 0; k < 24; k++) {
    ;[btn, txt] = await submitBtn(page)
    if (btn !== null) {
      console.log(`   ✓ 发布键「${txt}」已就绪`)
      break
    }
    if (k === 6) {
      // 底栏有时懒渲染，滚到底再试
      await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
      await clock.sleep(1.5)
    }
    await clock.sleep(2.5)
  }
  if (btn === null) {
    res['stage'] = '发布键未就绪'
    console.log('   ❌ 找不到可用的发布键')
    try {
      await page.screenshot({ path: join(logDir, `nobtn-xhs-${base.pad2(t['no'])}.png`) })
      console.log(
        `      frame 数=${page.frames().length}  innerH=${await page.evaluate('window.innerHeight')}`
        + `  scrollY=${await page.evaluate('window.scrollY')}`,
      )
      for (const fr of page.frames()) {
        let hits: any[] = []
        try {
          hits = await fr.evaluate(`() => {
                      const out=[];
                      document.querySelectorAll('*').forEach(e=>{
                        const t=(e.textContent||'').trim();
                        if (!/^发布$|^暂存离开$|^发布\\s*$/.test(t) && t!=='发布') return;
                        const r=e.getBoundingClientRect();
                        const cs=getComputedStyle(e);
                        out.push({t, tag:e.tagName,
                          cls:(e.className||'').toString().slice(0,130),
                          box:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)],
                          pos:cs.position, vis:cs.visibility, disp:cs.display, opa:cs.opacity,
                          path:(()=>{let s=[],n=e;for(let i=0;i<6&&n;i++){
                            s.push(n.tagName+(typeof n.className==='string'&&n.className
                              ?'.'+n.className.split(' ').filter(Boolean).slice(0,2).join('.') :''));n=n.parentElement;}
                            return s.join(' < ');})()});
                      });
                      return out;
                    }`)
        } catch {
          hits = []
        }
        for (const h of hits) {
          console.log(
            `      [${base.clip(String(fr.url().split('/').slice(-1)[0]), 28)}|${h['tag']}] 「${h['t']}」 `
            + `box=${base.pyReprList(h['box'])} pos=${h['pos']} vis=${h['vis']} disp=${h['disp']} opa=${h['opa']}`,
          )
          console.log(`          cls=${base.clip(String(h['cls']), 100)}`)
          console.log(`          path=${base.clip(String(h['path']), 190)}`)
        }
      }
    } catch (e) {
      console.log('      诊断异常', base.errName(e), base.errStr(e))
    }
    return res
  }

  if (!auto) {
    return base.dryRunStop(page, res, {
      logDir,
      shotName: `dryrun-xhs-${base.pad2(t['no'])}.png`,
      blocking: () => blocking(page),
    })
  }

  if (btn.kind === 'xy') {
    await page.mouse.click(btn.x, btn.y)
  } else {
    await btn.el.scrollIntoViewIfNeeded()
    await clock.sleep(0.5)
    await btn.el.click()
  }
  console.log(`   ✅ 已点「${txt}」`)
  await clock.sleep(4)
  await page.screenshot({ path: join(logDir, `postxhs-${base.pad2(t['no'])}.png`) })

  // 风控检测：撞上就停下来等用户扫码，不自动重试
  if (await base.riskHit(page)) {
    if (
      !(await base.waitRiskClear(page, {
        no: t['no'],
        logDir,
        hint: '用 REDnote APP 扫码',
        reset: (pg) => resetPage(pg, '风控后'),
      }))
    ) {
      res['stage'] = '风控未解除（已中止）'
      return res
    }
    await clock.sleep(3)
    await page.screenshot({ path: join(logDir, `postxhs-${base.pad2(t['no'])}.png`) })
  }

  if (await base.waitSuccess(page, XHS_SUCCESS_WORDS)) {
    res['ok'] = true
    res['stage'] = '已发布'
    console.log('   ✅ 发布成功')
    return res
  }

  res['stage'] = '已提交未确认'
  console.log(`   ⚠️ 已提交但未确认，URL=${page.url}`)
  return res
}

export interface XhsPublishOpts {
  profileDir?: string | null
  logDir: string
  only?: string | null
  frm?: number | null
  dryRun?: number
  headless?: boolean
}

/** 批量发布。**节流在循环内**（缺陷①修复）：between_s=35，每条之间都歇。 */
export async function publish(tasks: readonly base.Task[], opts: XhsPublishOpts): Promise<number> {
  const filtered = base.filterTasks(tasks, opts.only ?? null, opts.frm ?? null)
  const profileDir = opts.profileDir || base.profileDir('xiaohongshu')

  let loginOk = true
  let results: base.PubResult[] = []
  await base.launch(
    profileDir,
    { headless: opts.headless ?? false, viewport: { width: 1600, height: 1000 } },
    async (_ctx, page) => {
      await page.goto(UPLOAD_URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
      await clock.sleep(6)
      if (await base.loginWall(page, XHS_WALL)) {
        console.log('⚠️ 小红书未登录，请在弹出的 Chrome 窗口扫码')
        if (!(await base.waitLogin(page, 600, { kws: XHS_WALL }))) {
          console.log('❌ 登录超时')
          loginOk = false
          return
        }
      }
      console.log('✅ 小红书创作服务平台就绪\n')

      results = await base.runTasks(page, filtered, publishOne, {
        uploadUrl: UPLOAD_URL,
        logDir: opts.logDir,
        betweenS: 35,
        dryRun: opts.dryRun ?? 0,
        resultJson: 'publish-xhs-result.json',
      })
    },
  )
  if (!loginOk) return 1
  return base.summarize(results, '小红书')
}

// ── CLI 适配层（CLI 路由叶子；业务在 publish()，这里只接线） ──────────

/**
 * CLI 路由入口：`feuille publish xhs <manifest.json> --log-dir D`。
 *
 * manifest.json = plans 契约经 `manifest.build_manifest` 落盘的清单，
 * 本入口取其中的 "xiaohongshu" 段作为 tasks。
 */
export async function main(argv: string[]): Promise<number> {
  const a = base.manifestArgs(argv, 'feuille publish xhs')
  if ('rc' in a) return a.rc
  const tasks = base.manifestTasks(a.manifest, 'xiaohongshu')
  return publish(tasks, {
    logDir: a.logDir,
    only: a.only,
    frm: a.frm,
    dryRun: a.dryRun,
    headless: a.headless,
  })
}
