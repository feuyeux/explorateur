// publish.test.ts — 发布系统（M13：⑨ 发布 / ⑩ 合集 / ⑪ 核对）的反向验证
// （scripts/verify_publish.py 的 vitest 对应移植）。
//
// **全部离线 / 本地**：只驱动 tempfile 里的 mock HTML（file://），绝不访问任何
// 平台域名、绝不登录、绝不点任何真实页面（使用契约第 7 条）。
//
// 第 0 条好数据放行：resolver 在本机真实解析到 Chrome；playwright 装了时
// 发布器用**真 Chrome** 打开本地 mock 页跑通全链（skipIf 门控，镜像 Python
// 侧「未装 playwright → SKIP」行）。
//
// 与 Python 侧的两处刻意差异（迁移 README 记录）：
// 1. run_tasks 行离线跑：stub page（screenshot 写真文件、goto 空操作）驱动，
//    不再像 Python 侧那样被 playwright 是否安装门控——骨架本身不碰浏览器
//    内部，这是改进不是放松（断言逐条不变）。
// 2. 缺陷①的事件序列断言走 clock.ts seam：vi.mock 整模块记录 ['sleep', d]
//    事件（d < 0.5 委托真睡，其余只记录）——不动业务签名。
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { describe, expect, it, vi } from 'vitest'

import { FeuilleError, platform as pt } from '@feuille/core'

import * as base from '../src/base.js'
import * as bilibili from '../src/bilibili.js'
// 导入冒烟：这两个模块本套件不直接驱动，import 成功本身就是断言
// （Python 侧同款：collections / veriflive 只进 import 名单）
import * as collections from '../src/collections.js'
import * as douyin from '../src/douyin.js'
import * as login from '../src/login.js'
import * as veriflive from '../src/veriflive.js'
import * as xhs from '../src/xhs.js'

// 证据目录（build/ 不入库）：packages/publish/test → 上三级 = usine/
const ROOT = fileURLToPath(new URL('../../..', import.meta.url))
const EV = join(ROOT, 'build', 'publish-verify')

// 缺陷①断言的 seam：clock 整模块 mock（vi.hoisted 保证 events 先于 mock 工厂可用）
const events = vi.hoisted(() => [] as Array<[string, number]>)
vi.mock('../src/clock.js', async (importOriginal) => {
  const real = await importOriginal<typeof import('../src/clock.js')>()
  return {
    // Python 侧 rec_sleep 的同款口径：记录全部 ['sleep', d]；d < 0.5 委托真睡
    sleep: async (d: number) => {
      events.push(['sleep', d])
      if (d < 0.5) await real.sleep(d)
    },
    now: real.now,
  }
})

// playwright 装没装（镜像 Python 侧 try: import playwright except ImportError → SKIP）
let hasPw = false
try {
  await import('playwright')
  hasPw = true
} catch {
  hasPw = false
}

// ---------------------------------------------------------------- mock 页面
// A：发布页诱饵——「作品发布」导航（子串坑的原型）+ 无 primary 的同文本按钮 +
//    display:none 的假按钮 + div 假按钮 + 真·主按钮（class 含 primary）。
const MOCK_A = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>mock-A 抖音投稿页（诱饵版）</title>
<style>body{font:16px/1.6 sans-serif;margin:24px;background:#fff}
nav{border-bottom:1px solid #ddd;padding:8px}
button{font-size:16px;padding:8px 20px;margin:4px}
#real-publish{background:#fe2c55;color:#fff}
#decoy-div{display:inline-block;padding:8px 20px;margin:4px}
</style></head><body>
<nav>创作者中心 <button id="nav-publish" onclick="clickLog('nav-作品发布')">作品发布</button></nav>
<p>（诱饵 1：导航按钮文本含「发布」子串——has-text 会命中，text-is 不会）</p>
<button id="ghost-btn" class="btn-plain" onclick="clickLog('ghost-无primary')">发布</button>
<p>（诱饵 2：文本精确等于「发布」但 class 不含 primary）</p>
<button id="hidden-btn" class="semi-button primary" style="display:none"
        onclick="clickLog('hidden')">发布</button>
<p>（诱饵 3：class 含 primary 且文本精确，但不可见）</p>
<div id="decoy-div" class="semi-button primary" onclick="clickLog('div-假按钮')">发布</div>
<p>（诱饵 4：div 元素，class 含 primary、文本精确——但不是 button）</p>
<hr>
<button id="real-publish" class="semi-button primary" onclick="clickLog('real-发布')">发布</button>
<div style="height:600px"></div>
<div id="clicklog">[]</div>
<script>
window.__CLICKS = [];
function clickLog(w){ window.__CLICKS.push(w);
  document.getElementById('clicklog').textContent = JSON.stringify(window.__CLICKS);
  if (w === 'real-发布') document.title = 'PUBLISHED'; }
</script>
</body></html>`

// B：登录墙页——可见「扫码登录」面板 + 藏在 DOM 里的「作品管理」（浮层陷阱）
const MOCK_B = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>mock-B 登录墙</title></head><body>
<div id="wall" style="border:2px solid #fe2c55;padding:16px">
  <h2>扫码登录</h2><p>验证码登录 · 手机号登录</p>
</div>
<div id="content" style="display:none"><h1>作品管理</h1><p>数据概览</p></div>
</body></html>`

// C：成功页 + 风控页（B 站「稿件投递成功」全词 + xhs 风控文案）
const MOCK_C = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>mock-C 成功与风控</title></head><body>
<h1>稿件投递成功</h1>
<p> Scan to verify —— 请稍后再试 </p>
</body></html>`

// verify_platform 的 ALLOWED 之外不许出现写死可执行路径（缺陷③）
const WIN_EXE = /[A-Za-z]:\\?[A-Za-z0-9_ .\\-]+\.(?:exe|cmd|bat)\b/i
const MAC_APP = /\/Applications\/[\w .]+\.app\//
// lazy 契约的源码面断言：playwright 只许动态 import，静态依赖一处都不许有
const STATIC_PW_IMPORT = [
  /import\s+[^('"]*\bfrom\s+['"]playwright['"]/,
  /^import\s+['"]playwright['"]/m,
  /require\(\s*['"]playwright['"]\s*\)/,
]

// ---------------------------------------------------------------- 离线行
describe('发布系统反向验证（离线行，零平台流量）', () => {
  // 「解析到真浏览器」契约需要真 Chromium 在场：无浏览器主机（RSI macOS
  // guest 的 FEUILLE_BROWSER 哨兵）上 skipIf 跳过——SKIP 不是 PASS，
  // 浏览器真机覆盖归 Windows wave host（DPAPI，无钥匙串弹窗）。
  it.skipIf(pt.browserPath() === null)('resolveChrome() 解析到真实存在的 Chrome', () => {
    const got = base.resolveChrome()
    expect(got.length).toBeGreaterThan(0)
    expect(statSync(got).isFile(), `resolveChrome() 解析到真实存在的 Chrome：${got}`).toBe(true)
  })

  it.skipIf(pt.browserPath() === null)('resolveChrome 与 platform.browser(only=chrome) 同源（无第二事实源）', () => {
    const got = base.resolveChrome()
    const b = pt.browser('chrome')
    expect(b).not.toBeNull()
    expect(b![1]).toBe(got)
  })

  it('FEUILLE_BROWSER 坏路径 → 显式报缺不静默换人', () => {
    const old = process.env['FEUILLE_BROWSER']
    process.env['FEUILLE_BROWSER'] = '/definitely/not/a/chrome'
    try {
      expect(() => base.resolveChrome()).toThrow(FeuilleError)
    } finally {
      // singleFork worker 里所有 edge 文件共用本进程：恢复必须还原原值，
      // 无条件 delete 会抹掉调用方注入的 FEUILLE_BROWSER（RSI guest 的
      // 无浏览器哨兵），毒化之后跑的每个浏览器门控用例。
      if (old === undefined) delete process.env['FEUILLE_BROWSER']
      else process.env['FEUILLE_BROWSER'] = old
    }
  })

  it('playwright 缺席：import + 八个子模块 + 纯函数全不炸（lazy 契约）', async () => {
    // TS 侧无 sys.modules 注入手段，改由「in-process import 全通」+
    // 「源码面零静态 playwright 依赖」两行合证同一契约
    const mod = await import('../src/index.js')
    expect(Object.keys(mod).sort()).toEqual(
      ['base', 'bilibili', 'check_plan', 'collections', 'douyin', 'login', 'veriflive', 'xhs'],
    )
    expect(base.filterTasks([{ no: 1, lang: 'x' }])).toEqual([{ no: 1, lang: 'x' }])
  })

  it('publish 包源码零写死可执行路径 + 零静态 playwright 依赖', () => {
    const srcDir = join(ROOT, 'packages', 'publish', 'src')
    const hits: string[] = []
    const staticHits: string[] = []
    for (const f of readdirSync(srcDir).filter((n) => n.endsWith('.ts'))) {
      const text = readFileSync(join(srcDir, f), 'utf-8')
      if (WIN_EXE.test(text) || MAC_APP.test(text)) hits.push(f)
      if (STATIC_PW_IMPORT.some((re) => re.test(text))) staticHits.push(f)
    }
    expect(hits, `publish 包源码零写死可执行路径（.app/.exe 正则零命中）命中：${hits}`).toEqual([])
    expect(staticHits, `playwright 静态依赖（只许函数内动态 import）命中：${staticHits}`).toEqual([])
  })

  it('反向复现：v1 词表（缺「投递」二字）对「稿件投递成功」全不命中', () => {
    const body = '稿件投递成功'
    const v1Words = ['投稿成功', '稿件提交成功', '发布成功', '提交成功', '已进入审核', '审核中']
    expect(v1Words.some((k) => body.includes(k))).toBe(false)
    expect(bilibili.BILI_SUCCESS_WORDS.some((k) => body.includes(k)),
      '修复后 BILI_SUCCESS_WORDS 含全词「稿件投递成功」').toBe(true)
  })

  it("filterTasks：only='2,4' → [2, 4]；frm=3 → [3, 4, 5]；不过滤 → 原样全量", () => {
    const tasks = [1, 2, 3, 4, 5].map((i) => ({
      no: i, lang: `语${i}`, title: `标${i}`, body: 'b', tags: ['#x'], video: 'v', cover: 'c',
    }))
    expect(base.filterTasks(tasks, '2,4').map((t) => t['no'])).toEqual([2, 4])
    expect(base.filterTasks(tasks, null, 3).map((t) => t['no'])).toEqual([3, 4, 5])
    expect(base.filterTasks(tasks).map((t) => t['no'])).toEqual([1, 2, 3, 4, 5])
  })

  it("only='9' 筛空 → FeuilleError 当场报错（纪律 12：不静默跑 0 条）", () => {
    const tasks = [1].map((i) => ({
      no: i, lang: `语${i}`, title: `标${i}`, body: 'b', tags: ['#x'], video: 'v', cover: 'c',
    }))
    expect(() => base.filterTasks(tasks, '9')).toThrow(FeuilleError)
    expect(() => base.filterTasks(tasks, '9')).toThrow(/筛选后任务为空/)
  })

  it('缺陷①：run_tasks 节流在循环内 + 单条异常隔离 + result JSON 落盘', async () => {
    const td = mkdtempSync(join(tmpdir(), 'feuille-publish-run-'))
    events.length = 0
    try {
      const stubPage = {
        url: 'file:///mock/upload',
        // stub page：screenshot 写真文件（pre/post/crash 截图存在性是断言），
        // goto 空操作（回投稿页只是恢复动作，不碰浏览器内部）
        goto: async () => {},
        screenshot: async (opts: { path: string }) => {
          writeFileSync(opts.path, 'png')
        },
      }
      const mockOne = async (
        _pg: unknown,
        t: base.Task,
        _auto: boolean,
        _opts: { logDir: string },
      ): Promise<base.PubResult> => {
        events.push(['pub', t['no']])
        if (t['no'] === 2) {
          // 门禁口径：errName(e) 取 e.name —— 模拟 Python RuntimeError
          const e = new Error('模拟第 2 条挂掉')
          e.name = 'RuntimeError'
          throw e
        }
        return { no: t['no'], lang: t['lang'], ok: true, stage: 'mock-已发布' }
      }
      const mtasks = [1, 2, 3, 4].map((i) => ({
        no: i, lang: `语${i}`, title: `标${i}`, body: 'b', tags: ['#x'], video: 'v', cover: 'c',
      }))
      const logd = join(td, 'runlog')
      const results = await base.runTasks(stubPage as base.AnyPage, mtasks, mockOne, {
        uploadUrl: 'file:///mock/upload',
        logDir: logd,
        betweenS: 0.15,
        resultJson: 'mock-result.json',
      })

      const seq = events.filter((e) => e[0] === 'pub' || e[1] === 0.15)
      const wantSeq: Array<[string, number]> = [
        ['pub', 1], ['sleep', 0.15],
        ['pub', 2], ['sleep', 0.15],
        ['pub', 3], ['sleep', 0.15],
        ['pub', 4],
      ]
      expect(seq,
        '缺陷①修复：事件序列逐条断言 = 发布→睡0.15s→发布→睡→发布→睡→发布'
        + '（每条之间都睡，n-1=3 次节流全在循环内）').toEqual(wantSeq)

      expect(results.map((r) => r['no'])).toEqual([1, 2, 3, 4])
      expect(results.map((r) => r['ok'])).toEqual([true, false, true, true])
      expect(results[1]!['stage'],
        '单条异常隔离：第 2 条炸掉只记「异常 RuntimeError」，1/3/4 照常完成')
        .toBe('异常 RuntimeError')

      const back = JSON.parse(readFileSync(join(logd, 'mock-result.json'), 'utf-8'))
      expect(back.length).toBe(4)
      expect(back[1]['stage']).toBe('异常 RuntimeError')

      // 证据副本（build/publish-verify 不入库）
      mkdirSync(EV, { recursive: true })
      writeFileSync(join(EV, 'mock-result.json'), readFileSync(join(logd, 'mock-result.json'), 'utf-8'))
      writeFileSync(
        join(EV, 'mock-events.json'),
        `${JSON.stringify({ events, filtered_sequence: seq }, null, 1)}\n`,
      )

      expect(statSync(join(logd, 'crash-02.png')).isFile(),
        'crash-02 异常现场截图存在').toBe(true)
      for (const n of [1, 2, 3, 4]) {
        for (const p of ['pre', 'post']) {
          const f = join(logd, `${p}-${String(n).padStart(2, '0')}.png`)
          expect(statSync(f).isFile(), `${f} 存在`).toBe(true)
        }
      }
    } finally {
      rmSync(td, { recursive: true, force: true })
    }
  })
})

// ---------------------------------------------------------------- playwright 门控行
// 真 Chrome + file:// 本地页，零平台流量。本机未装 playwright 时整块 SKIP
// （镜像 Python 侧的 SKIP 行为），装上后自动补齐 mock 断言。
// 单个 it 单次 launch——镜像 Python 侧单个 with 块的形态。
describe.skipIf(!hasPw)('playwright 驱动本地 mock（真 Chrome + file://）', () => {
  it('mock-A/B/C 全链：精确按钮 / 可见性判据 / 全词成功 / 风控', async () => {
    const td = mkdtempSync(join(tmpdir(), 'feuille-publish-mock-'))
    mkdirSync(EV, { recursive: true })
    for (const [name, html] of [['mock-a', MOCK_A], ['mock-b', MOCK_B], ['mock-c', MOCK_C]] as const) {
      writeFileSync(join(td, `${name}.html`), html)
      writeFileSync(join(EV, `${name}.html`), html) // 证据副本
    }
    try {
      await base.launch(
        join(td, 'profile'),
        { headless: true, viewport: { width: 1280, height: 800 } },
        async (_ctx, page) => {
          // ---- A. find_publish_button：精确匹配，绝不点中诱饵 ----
          await page.goto(pathToFileURL(join(td, 'mock-a.html')).href)
          await page.waitForLoadState('load')
          await page.screenshot({ path: join(EV, 'mock-a-before.png') })
          const found = await base.findPublishButton(page)
          expect(found).not.toBeNull()
          expect(await found.getAttribute('id'),
            'find_publish_button 选中真·主按钮 #real-publish'
            + '（text-is 精确 + class 含 primary；四个诱饵全躲开）').toBe('real-publish')
          await found.click()
          const clicks = await page.evaluate('window.__CLICKS')
          expect(clicks, '点击后仅真按钮入账（诱饵零点击）').toEqual(['real-发布'])
          expect(await page.title()).toBe('PUBLISHED')
          await page.screenshot({ path: join(EV, 'mock-a-clicked.png') })
          // 反向：真按钮藏起来 → 必须返回 null，不退回任何诱饵
          await page.evaluate("document.getElementById('real-publish').style.display='none'")
          expect(await base.findPublishButton(page),
            '真按钮隐藏后 find_publish_button 返回 None——拒绝退回子串/无 primary 诱饵')
            .toBeNull()
          await page.screenshot({ path: join(EV, 'mock-a-hidden.png') })

          // ---- B. login_wall 只认可见文本 + login.probe 三通道 ----
          await page.goto(pathToFileURL(join(td, 'mock-b.html')).href)
          await page.waitForLoadState('load')
          const wallVis = await base.loginWall(page, douyin.DOUYIN_WALL)
          await page.screenshot({ path: join(EV, 'mock-b-wall-visible.png') })
          const [st1, desc1] = await login.probe(page, 'douyin')
          await page.evaluate(
            "document.getElementById('wall').style.display='none';"
            + "document.getElementById('content').style.display='';",
          )
          const wallHidden = await base.loginWall(page, login.SITES['douyin']!.wall)
          const [st2, desc2] = await login.probe(page, 'douyin')
          await page.screenshot({ path: join(EV, 'mock-b-wall-hidden.png') })
          expect(wallVis, 'login_wall：可见「扫码登录」面板 → True').toBe(true)
          expect(wallHidden, 'login_wall：墙藏进 DOM（display:none）→ False——只信可见文本').toBe(false)
          expect(st1, `login.probe：墙可见 → 未登录（${desc1}）`).toBe(false)
          expect(desc1).toContain('登录弹窗可见')
          expect(st2, `login.probe：墙隐藏+「作品管理」可见 → 已登录（${desc2}）——`
            + "inner_text('body') 式判法会在这里误判").toBe(true)
          expect(desc2).toContain('作品管理')

          // ---- C. wait_success 全词 + risk_hit ----
          await page.goto(pathToFileURL(join(td, 'mock-c.html')).href)
          await page.waitForLoadState('load')
          expect(await base.waitSuccess(page, bilibili.BILI_SUCCESS_WORDS, 6, 0.3),
            'wait_success：页面文案「稿件投递成功」→ B 站词表命中').toBe(true)
          expect(await base.waitSuccess(page, xhs.XHS_SUCCESS_WORDS, 0.6, 0.2),
            'wait_success 反向：无小红书成功词 → 超时返回 False').toBe(false)
          expect(await base.riskHit(page), "risk_hit：'Scan to verify' 风控文案 → True").toBe(true)
          await page.goto(pathToFileURL(join(td, 'mock-a.html')).href)
          expect(await base.riskHit(page)).toBe(false)
          expect(await base.loginWall(page), '干净页：risk_hit / login_wall 均 False').toBe(false)
        },
      )
    } finally {
      rmSync(td, { recursive: true, force: true })
    }
  })
})

// 导入冒烟兜底（collections / veriflive 不直接驱动，import 成功即断言）
describe('导入冒烟：两个不直接驱动的子模块 import 成功即断言', () => {
  it('collections / veriflive 均可导入且导出齐全', () => {
    expect(typeof collections.fixCollection).toBe('function')
    expect(typeof collections.createCollection).toBe('function')
    expect(typeof veriflive.verify).toBe('function')
    expect(typeof veriflive.verifyCollection).toBe('function')
    expect(typeof veriflive.run).toBe('function')
  })
})
