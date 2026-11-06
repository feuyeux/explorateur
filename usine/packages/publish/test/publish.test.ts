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
import * as draft from '../src/draft.js'
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

// D：存草稿页——真草稿键 + 三个诱饵（「草稿箱」导航 / 「保存并发布」/ 真·发布键）
const MOCK_D = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>mock-D 存草稿页</title></head><body>
<nav><button id="nav-drafts" onclick="clickLog('nav-草稿箱')">草稿箱</button></nav>
<p>（诱饵 1：导航「草稿箱」——含「草稿」子串，但不是存草稿动作）</p>
<button id="save-and-publish" onclick="clickLog('trap-保存并发布')">保存并发布</button>
<p>（诱饵 2：「保存并发布」——是另一个动作，点了就发布了）</p>
<button id="real-publish" class="semi-button primary" onclick="clickLog('real-发布')">发布</button>
<p>（诱饵 3：真·发布键——存草稿模式下**绝不能**点它）</p>
<div style="height:400px"></div>
<button id="save-draft" onclick="clickLog('draft-保存草稿');document.getElementById('tip').textContent='草稿保存成功'">保存草稿</button>
<div id="tip"></div>
<div id="clicklog">[]</div>
<script>
window.__CLICKS = [];
function clickLog(w){ window.__CLICKS.push(w); document.getElementById('clicklog').textContent = JSON.stringify(window.__CLICKS); }
</script>
</body></html>`

// E：没有草稿键的投稿页（只有发布键）——存草稿模式必须 fail-closed，一个键都不许点
const MOCK_E = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>mock-E 无草稿键</title></head><body>
<button id="real-publish" class="semi-button primary" onclick="clickLog('real-发布')">发布</button>
<div id="clicklog">[]</div>
<script>
window.__CLICKS = [];
function clickLog(w){ window.__CLICKS.push(w); document.getElementById('clicklog').textContent = JSON.stringify(window.__CLICKS); }
</script>
</body></html>`

// F：草稿键**不是 <button>**（抖音/B 站的「存草稿」多半是 div/span）——
// 只有 looksClickable 真跑起来才找得到；evaluate 传字符串时它恒 undefined ⇒ 找不到
const MOCK_F = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>mock-F div 版草稿键</title></head><body>
<div style="height:300px"></div>
<div id="save-draft" class="semi-button secondary" onclick="clickLog('draft-保存草稿');document.getElementById('tip').textContent='草稿保存成功'">保存草稿</div>
<div id="tip"></div>
<div id="clicklog">[]</div>
<script>
window.__CLICKS = [];
function clickLog(w){ window.__CLICKS.push(w); document.getElementById('clicklog').textContent = JSON.stringify(window.__CLICKS); }
</script>
</body></html>`

// G：B站投稿页的**真实**草稿键结构（2026-11-03 DOM 探针实测）。
// 真键 = `<span class="submit-draft">存草稿</span>`：tag 是 span、role 空、
// class 是 `submit-draft`（既不含 `button` 也不含 `btn`）⇒ 旧版 looksClickable
// 的结构路全不命中 ⇒ 候选被跳过 ⇒ 每一条都「找不到存草稿键」fail-closed 放弃
// （2026-11-03 10:37 那轮就是这么全灭的）。
// 唯一能用的信号是浏览器算出来的 `cursor: pointer`（实测该节点上没有 React props
// ⇒ 也不是靠 React 事件委托挂的）。
const MOCK_G = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>mock-G B站真实草稿键</title></head><body>
<div style="height:300px"></div>
<div class="submit-container">
  <span class="submit-draft" style="cursor:pointer" onclick="clickLog('draft-存草稿');document.getElementById('tip').textContent='草稿保存成功'">存草稿</span>
  <div class="submit-actions"><span class="submit-button-anchor"><span class="submit-add">立即投稿</span></span></div>
</div>
<div id="tip"></div>
<div id="clicklog">[]</div>
<script>
window.__CLICKS = [];
function clickLog(w){ window.__CLICKS.push(w); document.getElementById('clicklog').textContent = JSON.stringify(window.__CLICKS); }
</script>
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
      ['base', 'bilibili', 'check_plan', 'collections', 'douyin', 'draft', 'login', 'veriflive', 'xhs'],
    )
    expect(base.filterTasks([{ no: 1, lang: 'x' }])).toEqual([{ no: 1, lang: 'x' }])
  })

  it('--draft：旗标解析（给了=存草稿，没给=false），其余参数不受影响', () => {
    const a = base.manifestArgs(['--log-dir', 'D', '--draft', 'm.json'], 'feuille publish douyin')
    expect('rc' in a).toBe(false)
    if ('rc' in a) return
    expect(a.draft).toBe(true)
    expect(a.logDir).toBe('D')
    expect(a.manifest).toBe('m.json')
    const b = base.manifestArgs(['--log-dir', 'D', 'm.json'], 'feuille publish douyin')
    expect('rc' in b).toBe(false)
    if ('rc' in b) return
    expect(b.draft, '没给 --draft 就是真发布模式（默认不改变既有行为）').toBe(false)
  })

  it('存草稿键候选与发布键文本**不相交**（点下去的绝不可能是发布键）', () => {
    for (const [plat, texts] of Object.entries(draft.DRAFT_BTN_TEXTS)) {
      for (const t of texts) {
        expect(draft.PUBLISH_BTN_TEXTS.includes(t),
          `${plat} 的草稿候选「${t}」与发布键文本撞了——绝不能`).toBe(false)
      }
    }
    expect(draft.DRAFT_BTN_TEXTS['douyin']).toContain('存草稿')
    expect(draft.DRAFT_BTN_TEXTS['douyin']).toContain('暂存离开')
    expect(draft.DRAFT_BTN_TEXTS['bilibili']).toContain('保存草稿')
    // 「暂存离开」是实测文案；「暂存」不能与发布键文本相交
    expect(draft.PUBLISH_BTN_TEXTS.includes('暂存离开')).toBe(false)
  })

  it('存草稿键候选与「会删东西」的键**不相交**（「放弃」= 删上一条草稿）', () => {
    // 抖音横幅「你还有上次未发布的视频」上的「放弃」是**删除**上一条已存草稿。
    // 存草稿模式下一条一条存，每条开头点「放弃」= 把上一条删掉 ⇒ 4 条只剩 1 条，
    // 而脚本还会自报「已存草稿」。这条护栏把那个坑钉死在测试里。
    for (const [plat, texts] of Object.entries(draft.DRAFT_BTN_TEXTS)) {
      for (const t of texts) {
        expect(draft.DESTRUCTIVE_BTN_TEXTS.includes(t),
          `${plat} 的草稿候选「${t}」是会删东西的键——绝不能`).toBe(false)
      }
    }
    expect(draft.DESTRUCTIVE_BTN_TEXTS.includes('放弃')).toBe(true)
  })

  it('B站草稿键 = 「存草稿」（实测真键，不是「保存草稿」）', () => {
    // 实测（2026-11-03，DOM 探针 probe_bili_draftbtn.ts）：B站的键是
    // `<span class="submit-draft">存草稿</span>`，在页面底部的 `.submit-container` 里。
    // 原来候选表里只有「保存草稿」在前——真键在列表里但优先级靠后，
    // 匹配是按候选顺序逐个找的，所以两条都得留着（枚举不是猜测）。
    expect(draft.DRAFT_BTN_TEXTS['bilibili']).toContain('存草稿')
    expect(draft.DRAFT_BTN_TEXTS['bilibili']).toContain('保存草稿')
  })

  it('B站落库判据覆盖实测的落点 URL（upload-manager = 草稿箱）', () => {
    // 实测（2026-11-03，probe_bili_draftclick.ts）：点「存草稿」⇒
    // POST /x/vupre/web/draft/add ⇒ 页面跳到
    // `member.bilibili.com/platform/upload-manager/article?group=draft`。
    // **没有任何成功 toast**（页面上只有两行 tips）⇒ URL 落地是 B站唯一的真判据。
    expect(draft.DRAFT_LANDED_URLS['bilibili']).toContain('upload-manager')
    // 落库判据不许退化成「站投稿页也算落库」——投稿页 URL 不含这些片段。
    expect('https://member.bilibili.com/platform/upload/video/frame'.includes('upload-manager'))
      .toBe(false)
  })

  it('B站创作声明：「自制」是**同一个 select 的选项**（不是独立字段）', () => {
    // 实测（2026-11-03，probe_bili_statement.ts / probe_bili_selfmade.ts）：
    // 声明区 `div.statement-main div.bcc-select` 计数 = 1，展开后完整列表 13 项，
    // 「内容为自制：未经作者允许，禁止转载」与「内容无需标注」并列。
    // 旧版把它当「必填 + 选填」两件事办 ⇒ 同一个 input 被后写覆盖 ⇒ 4 条全被中止。
    // 「首选值」必须包含「自制」，且它**就是**首选（用户要的就是它）。
    expect(bilibili.BILI_STMT_REQUIRED[0]).toBe('内容为自制：未经作者允许，禁止转载')
    expect(bilibili.BILI_STMT_OPTIONAL).toBe('内容为自制：未经作者允许，禁止转载')
    // 它必须同时出现在必填候选里（否则选不上 → fail-closed 放弃每一条）
    expect(bilibili.BILI_STMT_REQUIRED
      .some((k) => bilibili.BILI_STMT_OPTIONAL.includes(k))).toBe(true)
    // 旧版注释断言「自制填不满必填字段」——实测推翻：它就是必填字段的一个选项。
    expect(bilibili.BILI_STMT_REQUIRED.length).toBeGreaterThan(1)
  })

  it('落库横幅判据：抖音的「你还有上次未发布的视频」是**唯一**的落库信号', async () => {
    // 实测（2026-11-03）：抖音 PC 端没有草稿列表页（内容管理只有「作品/作品合集」，
    // 「审核状态」下拉只有 全部/已发布/审核中/未通过，作品列表接口 status=2/3 返回空），
    // 点完「暂存离开」后上传页顶部出现横幅「你还有上次未发布的视频，是否继续编辑？」，
    // 且该横幅**新开浏览器后仍在** ⇒ 稿子在服务端。
    expect(douyin.DRAFT_LANDED_BANNER).toContain('你还有上次未发布的视频')
    // 判据实现：landedWords 命中 ⇒ 判成功（这一路是「点击后才算」的新证据）
    const hit = (words: string[]): any => ({
      url: () => 'https://creator.douyin.com/creator-micro/content/upload',
      getByText: (k: string) => ({
        count: async () => (words.includes(k) ? 1 : 0),
        first: () => ({ isVisible: async () => true }),
      }),
    })
    expect(await draft.waitDraftSaved(hit(['你还有上次未发布的视频']), [], [], 0,
      douyin.DRAFT_LANDED_BANNER),
    '落库横幅出现 ⇒ 判已存草稿').toBe(true)
    expect(await draft.waitDraftSaved(hit([]), [], [], 0, douyin.DRAFT_LANDED_BANNER),
    '横幅没出现 ⇒ 不得判已存草稿').toBe(false)
  })

  it('上传未完成就点存草稿 = 存进残片（判据必须挡）', async () => {
    // 实测：原判据只看「发布按钮解禁」⇒ 假绿灯——点存草稿那一刻视频才传到 23%
    //（predraft-01.png: 已上传 40.7MB/176.3MB 23%），日志却报「转码完成」。
    // 23% 的字节平台收不到完整文件，存进草稿的是残片。
    // 这里断言：上传未走完时 waitUploadComplete 返回 false。
    const partial = (txt: string): any => ({
      evaluate: async () => {
        const m = txt.match(/已上传[:：]\s*([\d.]+)\s*MB\s*\/\s*([\d.]+)\s*MB/)
        return {
          cur: m ? m[1] : null,
          total: m ? m[2] : null,
          done: /上传完成|上传成功/.test(txt),
          pct: (txt.match(/([\d.]+)\s*%/) || [])[1] ?? null,
        }
      },
    })
    expect(await douyin.waitUploadComplete(partial('已上传： 40.7MB/176.3MB 23%'),
      { timeoutS: 0, pollS: 0 }),
    '上传只到 23% ⇒ 不得判上传完成').toBe(false)
    expect(await douyin.waitUploadComplete(partial('已上传： 176.3MB/176.3MB 100%'),
      { timeoutS: 0, pollS: 0 }),
    '上传走完 ⇒ 判上传完成').toBe(true)
    expect(await douyin.waitUploadComplete(partial('上传完成'),
      { timeoutS: 0, pollS: 0 }),
    '出现「上传完成」⇒ 判上传完成').toBe(true)
  })

  it('存草稿成功判定：URL 判据是**命中式**（还在投稿页时不得判成功）', async () => {
    // ⚠️ 桩对象的契约必须与真 Playwright Page 一致：`url` 是**方法** `url()`，
    // 不是字符串属性（Python 侧才是 property）。上一版桩里写成了字符串属性，
    // 于是测的是一个虚构契约——真页面上 `page.url.includes` 直接抛 TypeError。
    const stub = (u: string): any => ({
      url: () => u,
      // 可见文本一条都没有 ⇒ 文案判据恒不命中，只剩 URL 判据在起作用
      getByText: () => ({ count: async () => 0 }),
    })
    // 真实投稿页 URL 形态（抖音 creator-micro / B 站创作中心）
    const dyUpload = 'https://creator.douyin.com/creator-micro/content/upload'
    const biliUpload = 'https://member.bilibili.com/platform/upload/video/frame'
    const dyLanded = draft.DRAFT_LANDED_URLS['douyin']!
    const biliLanded = draft.DRAFT_LANDED_URLS['bilibili']!
    // 不变式：落地片段不许出现在投稿页 URL 里——撞上了 URL 判据就退化成假绿灯
    expect(dyLanded.some((u) => dyUpload.includes(u)),
      '抖音投稿页 URL 命中了草稿列表标志片段 ⇒ URL 判据会退化成假绿灯').toBe(false)
    expect(biliLanded.some((u) => biliUpload.includes(u)),
      'B 站投稿页 URL 命中了草稿列表标志片段 ⇒ URL 判据会退化成假绿灯').toBe(false)
    // 反向复现：停在投稿页 ⇒ 不得判「已存草稿」
    // （旧实现写成「URL 里不再含落地片段」，投稿页当场返回 true ⇒ 每条都假成功）
    expect(await draft.waitDraftSaved(stub(dyUpload), ['已保存草稿'], dyLanded, 0),
      '还在投稿页、也没有成功文案 ⇒ 不得判「已存草稿」').toBe(false)
    // 正向：真的落到草稿列表 ⇒ 判成功
    expect(await draft.waitDraftSaved(stub('https://creator.douyin.com/creator-micro/content/manage'),
      ['已保存草稿'], dyLanded, 0),
      '已落到草稿列表 ⇒ 判成功').toBe(true)
  })

  it('pageUrl：Playwright 的 page.url 是**方法** url()（Python 侧才是 property）', async () => {
    // 移植坑：Python 侧 `page.url` 是 property，照抄到 TS 就成了「拿函数当字符串用」。
    expect(await base.pageUrl({ url: () => 'https://x/y' } as any),
      '方法形态（真 Playwright）：调用它').toBe('https://x/y')
    expect(await base.pageUrl({ url: 'https://x/y' } as any),
      '字符串属性形态（桩）：直接用').toBe('https://x/y')
    expect(await base.pageUrl({} as any), '读不到 → 空串（不许抛）').toBe('')
    // 反向复现：旧写法把 page.url 当字符串用 ⇒ TypeError
    expect(() => ({} as any).url.includes('x')).toThrow(TypeError)
  })

  it('发布路径上的 evaluate 一律传真函数（传字符串 ⇒ 返回 undefined ⇒ 静默失效）', () => {
    // 踩过的坑：JS 版 Playwright 的 `evaluate` 收到**字符串**时，只把它当表达式求值——
    // `'(e) => {...}'` 求值出来是函数对象 → 不可序列化 → 返回 undefined。
    // （Python 版传字符串会执行函数；移植时同一个坑栽过。）
    // 后果不是报错而是**静默失效**：jsClick 假装点过、looksClickable 恒假、
    // 诊断清单恒空。
    //
    // 边界写明：这条只管**发布路径**的四个模块（B 站 + 抖音）。
    // collections（合集）/ veriflive（直播核验）/ xhs（小红书）里还有同款字符串
    // evaluate——不在本轮发布路径上，已在交付说明里点名另开一轮修。
    const pathFiles = ['base.ts', 'bilibili.ts', 'douyin.ts', 'draft.ts']
    const srcDir = join(ROOT, 'packages', 'publish', 'src')
    const offenders: string[] = []
    for (const f of pathFiles) {
      // 只查**代码行**：纯注释行（// 开头、* 开头、/* 开头）里引用这个写法是文档，
      // 不该被当成违规——注释里常要写「传字符串会失效」这句话本身。
      readFileSync(join(srcDir, f), 'utf-8').split('\n').forEach((line, i) => {
        if (/^\s*(\/\/|\*|\/\*)/.test(line)) return
        if (/\.evaluate\(\s*['"`]/.test(line)) offenders.push(`${f}:${i + 1}`)
      })
    }
    expect(offenders,
      '发布路径上的 evaluate 传了字符串 ⇒ JS Playwright 只求值不执行 ⇒ 恒 undefined ⇒ 静默失效')
      .toEqual([])
  })

  it('读 URL 一律走 base.pageUrl（page.url 是方法，直接碰就是拿函数当字符串）', () => {
    // 同族移植坑：Python 侧 `page.url` 是 property，JS 侧是方法 `url()`。
    // 直接写 `page.url.includes(...)` ⇒ `TypeError: page.url.includes is not a function`
    // ——抖音发布路径第一行就踩着（实测整批直接崩）。
    // 收口只有一个入口：base.pageUrl(page)。这条门禁盯着别再散着写。
    const srcDir = join(ROOT, 'packages', 'publish', 'src')
    const offenders: string[] = []
    for (const f of readdirSync(srcDir).filter((n) => n.endsWith('.ts'))) {
      readFileSync(join(srcDir, f), 'utf-8').split('\n').forEach((line, i) => {
        if (/^\s*(\/\/|\*|\/\*)/.test(line)) return
        if (/\bpage\.url\b/.test(line)) offenders.push(`${f}:${i + 1}`)
      })
    }
    expect(offenders, 'publish 包源码里不许直接出现 page.url（走 base.pageUrl）').toEqual([])
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
//
// 2026-10-19: 无浏览器主机（RSI guest / wave host 的 FEUILLE_BROWSER 哨兵）
// 上还缺第二个条件。base.resolveChrome() 在 browser() 返回 null 时是**显式
// 抛错**而非返回 null（本包契约：绝不静默换浏览器），所以只判 hasPw 会在
// 无浏览器主机上把整块打成 FAIL 而不是 SKIP。与本文件上方两处
// skipIf(pt.browserPath() === null) 同一门控形状。
describe.skipIf(!hasPw || pt.browserPath() === null)(
  'playwright 驱动本地 mock（真 Chrome + file://）', () => {
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

  // 超时 120s 的理由（2026-11-06）：这一条串起**四个**浏览器场景
  // （mock-D/E/F/G），每个都真的 goto + 截图 + 等草稿键出现，其中三个还带
  // 故意的 waitS/timeoutS 预算（5s/2s/5s/5s）——那是被测行为，不是等待浪费。
  // 单独跑实测 25.2s；`pnpm verify` 全量并行时（50 个文件抢同一台机器）冲过
  // 根级 30s 默认值而超时，代码没改、断言也没错。30s 是「挂死」的兜底，不是
  // 性能断言——真挂死是整进程不返回，120s 照样抓得住。
  it('mock-D/E/F/G 存草稿：只点草稿键 / 找不到草稿键就 fail-closed / div 版草稿键也认 / B站真实 span 键也认',
    { timeout: 120_000 }, async () => {
    const td = mkdtempSync(join(tmpdir(), 'feuille-publish-draft-'))
    mkdirSync(EV, { recursive: true })
    for (const [name, html] of [
      ['mock-d', MOCK_D], ['mock-e', MOCK_E], ['mock-f', MOCK_F], ['mock-g', MOCK_G],
    ] as const) {
      writeFileSync(join(td, `${name}.html`), html)
      writeFileSync(join(EV, `${name}.html`), html) // 证据副本
    }
    try {
      await base.launch(
        join(td, 'profile'),
        { headless: true, viewport: { width: 1280, height: 800 } },
        async (_ctx, page) => {
          // ---- D. 找得到草稿键 ⇒ 只点它，诱饵与发布键零点击 ----
          await page.goto(pathToFileURL(join(td, 'mock-d.html')).href)
          await page.waitForLoadState('load')
          const found = await draft.findDraftButton(page, 'douyin')
          expect(found, 'mock-D：找得到真·保存草稿键').not.toBeNull()
          expect(await found!.el.getAttribute('id'),
            'findDraftButton 选中真·保存草稿键 #save-draft'
            + '（text-is 精确；「草稿箱」导航 / 「保存并发布」/ 真·发布键 全躲开）').toBe('save-draft')
          await page.screenshot({ path: join(EV, 'mock-d-before.png') })
          const res = { no: 1, lang: 'zh', ok: false, stage: '' } as base.PubResult
          const out = await draft.saveDraft(page, res, {
            platform: 'douyin', logDir: EV, no: 1, waitS: 5, timeoutS: 5,
          })
          const clicks = await page.evaluate('window.__CLICKS')
          expect(clicks,
            '存草稿模式只点草稿键：「草稿箱」导航 /「保存并发布」/真·发布键 全零点击')
            .toEqual(['draft-保存草稿'])
          expect(out.ok, `mock-D：点了保存草稿且出现「草稿保存成功」⇒ 判成功（stage=${out.stage}）`).toBe(true)
          expect(out.stage).toBe('已存草稿')
          await page.screenshot({ path: join(EV, 'mock-d-after.png') })

          // ---- E. 找不到草稿键 ⇒ fail-closed，一个键都不许点 ----
          await page.goto(pathToFileURL(join(td, 'mock-e.html')).href)
          await page.waitForLoadState('load')
          expect(await draft.findDraftButton(page, 'douyin'),
            'mock-E：只有发布键 ⇒ findDraftButton 返回 null（不退回发布键）').toBeNull()
          const res2 = { no: 2, lang: 'zh', ok: false, stage: '' } as base.PubResult
          const out2 = await draft.saveDraft(page, res2, {
            platform: 'douyin', logDir: EV, no: 2, waitS: 2, timeoutS: 2,
          })
          expect(out2.ok, 'mock-E：找不到草稿键 ⇒ 如实报失败，不谎报成功').toBe(false)
          expect(out2.stage, '失败原因要点名「找不到存草稿键」').toContain('找不到存草稿键')
          expect(await page.evaluate('window.__CLICKS'),
            'mock-E：发布键零点击（绝不退而求其次去点发布）').toEqual([])
          await page.screenshot({ path: join(EV, 'mock-e-after.png') })

          // ---- F. 草稿键不是 <button>（div）⇒ 只有 looksClickable 真跑起来才找得到 ----
          await page.goto(pathToFileURL(join(td, 'mock-f.html')).href)
          await page.waitForLoadState('load')
          const f = await draft.findDraftButton(page, 'douyin')
          expect(f, 'mock-F：草稿键是 div（不是 button）⇒ 照样找得到').not.toBeNull()
          expect(await f!.el.getAttribute('id'),
            'mock-F：选中的就是那个 div 草稿键 #save-draft').toBe('save-draft')
          const resF = { no: 3, lang: 'zh', ok: false, stage: '' } as base.PubResult
          const outF = await draft.saveDraft(page, resF, {
            platform: 'douyin', logDir: EV, no: 3, waitS: 5, timeoutS: 5,
          })
          expect(await page.evaluate('window.__CLICKS'),
            'mock-F：点的是 div 草稿键').toEqual(['draft-保存草稿'])
          expect(outF.ok, `mock-F：div 版草稿键也要能存成（stage=${outF.stage}）`).toBe(true)

          // ---- G. B站真实结构：<span class="submit-draft">存草稿</span> ----
          // 真键不是 button/div，是 span：结构路（tag/role/class）全不命中，
          // 只有浏览器算出来的 `cursor: pointer` 能认出它 ⇒ 少了这一路，
          // B站每一条都会「找不到存草稿键」fail-closed。
          await page.goto(pathToFileURL(join(td, 'mock-g.html')).href)
          await page.waitForLoadState('load')
          const g = await draft.findDraftButton(page, 'bilibili')
          expect(g, 'mock-G：B站真键是 span.submit-draft ⇒ 找得到').not.toBeNull()
          expect(await g!.el.evaluate((e: any) => e.tagName.toLowerCase()),
            'mock-G：选中的是那个 span 草稿键（不是外层容器，也不是「立即投稿」）').toBe('span')
          expect(await g!.el.getAttribute('class'),
            'mock-G：选中的 class 是 submit-draft').toBe('submit-draft')
          expect(((await g!.el.innerText()) ?? '').trim(),
            'mock-G：选中的文本是「存草稿」').toBe('存草稿')
          const resG = { no: 4, lang: 'zh', ok: false, stage: '' } as base.PubResult
          const outG = await draft.saveDraft(page, resG, {
            platform: 'bilibili', logDir: EV, no: 4, waitS: 5, timeoutS: 5,
          })
          expect(await page.evaluate('window.__CLICKS'),
            'mock-G：只点草稿键，「立即投稿」零点击').toEqual(['draft-存草稿'])
          expect(outG.ok, `mock-G：B站 span 版草稿键也要能存成（stage=${outG.stage}）`).toBe(true)
          expect(outG.stage).toBe('已存草稿')
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
