// login.ts — 逐平台扫码登录（⑨ 前置）：打开 + 等待 + 存盘，不碰任何发布按钮
// （publish/login.py 的 TS 移植）。
//
// 逐个而不是一次全开：二维码有效期约 1–3 分钟，一次全开会有人过期。
// 本模块的 waitLogin 走 probe() 的三通道判据（可见文本 → URL 特征）；
// base.waitLogin 是通用登录墙轮询（关键词表由调用方传），两者用途不同。
//
// 使用契约：认证一律人工（纪律 21）——脚本只等扫码，不代填任何凭据；
// profile 用 base.PROFILES 的持久 user-data 目录，登录态存盘勿删。
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

import * as base from './base.js'
import * as clock from './clock.js'

// 每个平台：入口 URL、常驻 profile、登录成功判据、登录墙判据
// profile 值从 base.PROFILES 派生（单一事实源），这里只放各平台的判据数据。
export interface SiteInfo {
  label: string
  url: string
  /** 登录后：内容区可见判据词 */
  in: string[]
  in_url: string[]
  /** 登录墙：扫码登录面板判据词 */
  wall: string[]
}

export const SITES: Record<string, SiteInfo> = {
  douyin: {
    label: '抖音创作者中心',
    url: 'https://creator.douyin.com/creator-micro/home',
    // 登录后：左上角有「发布视频」入口，或落在内容管理页
    in: ['发布视频', '作品管理', '数据概览'],
    in_url: ['/creator-micro/content', '/creator-micro/home'],
    // 登录墙：出现扫码登录面板
    wall: ['扫码登录', '验证码登录', '密码登录'],
  },
  xiaohongshu: {
    label: '小红书创作服务平台',
    url: 'https://creator.xiaohongshu.com/publish/publish',
    in: ['发布笔记', '上传视频', '创作中心', '数据中心'],
    in_url: ['/publish/publish', '/new/note'],
    wall: ['扫码登录', '验证码登录', '手机号登录', '立即登录'],
  },
  bilibili: {
    label: 'B站创作中心',
    url: 'https://member.bilibili.com/platform/upload/video/frame',
    in: ['投稿', '上传稿件', '内容管理', '创作中心'],
    in_url: ['/platform/upload', '/platform/home'],
    wall: ['扫码登录', '密码登录', '手机号登录', '登录后'],
  },
  zhihu: {
    label: '知乎创作中心',
    url: 'https://www.zhihu.com/creator',
    in: ['创作中心', '发布文章', '发布视频', '内容管理', '数据概览'],
    in_url: ['/creator', '/creator/manage'],
    wall: ['扫码登录', '验证码登录', '手机号登录', '立即登录'],
  },
}

export const ORDER: readonly string[] = ['douyin', 'xiaohongshu', 'bilibili', 'zhihu']

export const KEYWORDS: readonly string[] = [
  '扫码登录', '验证码登录', '密码登录', '手机号登录', '立即登录', '登录后',
  '发布视频', '作品管理', '数据概览', '创作中心',
  '发布笔记', '上传视频', '投稿', '上传稿件', '内容管理', '发布文章',
]

/**
 * 只取**可见**的文本节点。
 *
 * 踩过的两个坑：
 * 1) 登录弹窗是浮层，底层页面的「作品管理」等文案仍在 body 文本里，
 *    用 inner_text('body') 会把「未登录」误判成「已登录」。必须按可见性过滤。
 * 2) Playwright 的 `text=` 引擎不能写成逗号并用（会被当成 CSS 解析），
 *    必须逐个关键词 get_by_text 查。
 */
async function visibleTexts(page: base.AnyPage): Promise<string[]> {
  const seen: string[] = []
  for (const kw of KEYWORDS) {
    try {
      const loc = page.getByText(kw, { exact: false })
      const n = Math.min(await loc.count(), 3)
      for (let i = 0; i < n; i++) {
        const el = loc.nth(i)
        if (await el.isVisible()) {
          const t = ((await el.innerText()) ?? '').trim()
          if (t && !seen.includes(t)) seen.push(t)
          break // 该关键词已确认可见即可
        }
      }
    } catch {
      continue
    }
  }
  return seen
}

/**
 * 返回 [是否已登录, 现场描述]。只看可见元素，不点击。
 *
 * （适配点：原版用全局 CUR 标记当前平台——不可测；改为显式 name 参数，逻辑不变。）
 */
export async function probe(page: base.AnyPage, name: string): Promise<[boolean, string]> {
  const url = page.url || ''
  const vis = await visibleTexts(page)
  if (!vis.length) return [false, '页面尚未渲染出可判定特征']

  const site = SITES[name]!
  const wall = site['wall'].filter((w) => vis.includes(w))
  const inside = site['in'].filter((w) => vis.includes(w))

  // 登录墙可见 → 未登录（可见性优先，浮层不会再骗人）
  if (wall.length) return [false, `登录弹窗可见（${wall[0]}）`]
  if (inside.length) return [true, `内容区可见（${inside[0]}）`]
  const inUrl = site['in_url'].filter((u) => url.includes(u))
  if (inUrl.length && !wall.length) return [true, `落在内容页 URL（${inUrl[0]}）`]
  return [false, `未见登录入口也未见内容区（可见：${base.pyReprList(vis.slice(0, 3))}）`]
}

/**
 * 轮询等待登录完成。二维码过期的话页面会自己刷新出新码。
 *
 * （与 base.waitLogin 不同：这里用 probe() 的可见文本 + URL 双通道判据，
 * 是 login_helper 原版逻辑；ctx 是持久 profile context，登录即落盘。）
 */
export async function waitLogin(ctx: base.AnyCtx, name: string, minutes = 6): Promise<boolean> {
  const site = SITES[name]!
  // 轮询前取好页面并复用——ctx.pages 为空时在循环里反复 newPage()
  // 会一直开新标签（每轮一个），既慢又把浏览器开成一排窗口。
  const page = ctx.pages && ctx.pages.length ? ctx.pages[0] : await ctx.newPage()
  const limit = clock.now() + minutes * 60
  let tick = 0
  while (clock.now() < limit) {
    const [ok, desc] = await probe(page, name)
    if (ok) {
      console.log(`   ✅ ${site['label']} 登录成功 · ${desc}`)
      return true
    }
    if (tick % 5 === 0) {
      console.log(`   ⏳ 等待扫码…（${desc}）已等 ${Math.floor((limit - clock.now()) / 60) + 1} 分钟内`)
    }
    tick++
    await clock.sleep(3)
  }
  console.log(`   ❌ ${site['label']} 超时未登录`)
  return false
}

/** 打开一个平台的后台，判定登录态；未登录则（可选）等用户扫码，存盘退出。 */
export async function doOne(
  name: string,
  wait = true,
  opts: { shotDir?: string | null } = {},
): Promise<boolean> {
  const site = SITES[name]!
  const profile = base.profileDir(name)
  console.log(`\n=== ${site['label']} ===`)
  let ok = false
  await base.launch(profile, { viewport: { width: 1440, height: 900 } }, async (ctx, page) => {
    await page.goto(site['url'], { waitUntil: 'domcontentloaded', timeout: 60000 })
    await clock.sleep(5)

    const [st, desc] = await probe(page, name)
    ok = st
    console.log(`   当前状态：${desc}`)
    if (opts.shotDir != null) {
      try {
        mkdirSync(opts.shotDir, { recursive: true })
        await page.screenshot({ path: join(opts.shotDir, `login-${name}.png`) })
      } catch (e) {
        // 截图只是留证，不该让它中断登录流程（部分站点会开新页导致原页关闭）
        console.log(`   （截图跳过：${base.errName(e)}）`)
      }
    }

    if (ok) {
      console.log('   ✅ 已是登录态，无需扫码')
    } else if (!wait) {
      console.log('   ⚠️  未登录。需你本人在弹出的 Chrome 窗口扫码/登录。')
    } else {
      console.log('   👉 请在弹出的 Chrome 窗口中扫码登录（脚本会等，登录后自动继续）')
      ok = await waitLogin(ctx, name)
      if (ok && opts.shotDir != null) {
        try {
          await page.screenshot({ path: join(opts.shotDir, `login-${name}-ok.png`) })
        } catch {
          // 截图只是留证
        }
      }
    }
  })
  // launch 回调退出即 ctx.close() —— 关闭才把 cookie 写进 profile
  console.log(`   💾 会话已存盘到 ${profile}`)
  return ok
}

/**
 * 按给定顺序逐个登录（不并行——二维码 1–3 分钟过期，一次全开会有人过期）。
 *
 * names=null 按默认顺序全走一遍；wait=False 只查状态不等待。返回退出码。
 */
export async function login(
  names: readonly string[] | null = null,
  opts: { wait?: boolean; shotDir?: string | null } = {},
): Promise<number> {
  const wait = opts.wait ?? true
  const list = names && names.length ? [...names] : [...ORDER]
  const bad = list.filter((n) => !(n in SITES))
  if (bad.length) {
    console.log('未知平台:', bad, '可选:', Object.keys(SITES))
    return 2
  }

  const results: Record<string, boolean> = {}
  for (const n of list) {
    try {
      results[n] = await doOne(n, wait, { shotDir: opts.shotDir ?? null })
    } catch (e) {
      console.log(`=== ${n} 异常: ${base.errStr(e)}`)
      results[n] = false
    }
  }

  console.log('\n===== 登录结果汇总 =====')
  for (const n of Object.keys(results)) {
    console.log(`  ${SITES[n]!['label'].padEnd(20)} ${results[n] ? '✅ 已登录' : '❌ 未登录'}`)
  }
  return Object.values(results).every(Boolean) ? 0 : 1
}
