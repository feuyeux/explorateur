// layout.test.ts — 内容产物落位的结构门禁（AGENTS.md「内容产物落位」）
//
// 规矩只有一句话：**生成出来的内容项目只允许两处**——
//
//   usine/skills/<skill>/assets/   可复用资产（模板/示例/夹具），随 git 版本化
//   usine/examples/<项目名>/        内容项目产物（成片/封面/文案），不入库
//
// **没有第三处。** 仓库根与 usine/ 顶层不许再长出项目目录。
//
// 为什么这道闸必须存在：2026-10-20 发现 `chess-12lang/` 直接长在仓库根并被入库
// ——222 个文件、99 个 LFS 对象共 129.5 MB。它的内容和产物都没毛病，**位置错了**。
// 位置错误不会自己报错：它只在下一次 clone 时变成体积，而且被追踪之后 .gitignore
// 也拦不住（已入库的文件忽略规则管不着）。所以得由门禁说出来，不能靠「记得」。
//
// ── 2026-10-22 根定位修复（本文件与 ../src/index.ts 两个文件）──────────────
// **旧定位**（原来就在这几行里）：
//     const USINE = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
//     const REPO  = join(USINE, '..')        // ← 假定「上一层就是仓库根」
// **新定位**：`discoverRoot()` 从起点向上逐级走，第一个**同时含**
// pnpm-workspace.yaml 与 ownership.json 的目录就是工作区根；走完整条链都没有，
// 门禁照样 FAIL，但报文点名「找的是哪些标记、从哪起走、走过哪些层」。
//
// 为什么必须换：仓库签出在 home 下一层时（home 里还有 AppData/、bin/、另一份
// 工作树），旧 `..` 让 REPO 指到 home 本身，于是 home 的无关目录被当成本仓库的
// 违规内容——**候选代码完全正确的机器上红闸**，合并时拒绝一切。判断没错，错的是
// 定位：把「包目录之上固定几层就是仓库根」这个**位置假设**写死了。
//
// 口径一个字也没放宽：下面既钉了真根下的白名单全文，也用合成树钉了正向对照
// （真长出 chess-12lang / prompts ⇒ 当场 FAIL）与负向对照（标记缺失 ⇒ 清晰报文，
// 绝不冒充第三处违规）。合成树一律建在 os.tmpdir() 的 mkdtemp 目录里，
// afterAll 删干净——**不碰真 HOME 的任何内容**。
//
// 全部是磁盘静态检查，不起浏览器、不跑产线（纪律 12）。
import { afterAll, describe, expect, test } from 'vitest'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  ALLOWED_ROOT_DIRS,
  ALLOWED_USINE_DIRS,
  ROOT_MARKERS,
  dirNames,
  discoverRoot,
  enclosingRepoRoot,
  layoutReport,
  strayEngineRepos,
  strayRootDirs,
  strayUsineDirs,
} from '../src/index.js'

/** 本测试文件所在目录——真实磁盘用例的起点（只用来发起向上走，不假定层数）。 */
const TEST_DIR = dirname(fileURLToPath(import.meta.url))

/** 真根：靠标记定位，找不到就让用例响亮地失败（而不是拿一个猜的路径继续）。 */
function realRoot(): string {
  const found = discoverRoot(TEST_DIR)
  if (!found.ok) throw new Error(found.message)
  return found.root
}

// ── 合成树工具：一律建在 os.tmpdir() 下的 mkdtemp 目录，afterAll 删干净 ──────
const MADE: string[] = []

function tmpTree(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix))
  MADE.push(dir)
  return dir
}

function mkDirs(base: string, names: readonly string[]): void {
  for (const n of names) mkdirSync(join(base, n), { recursive: true })
}

/** 在 `dir` 放上全部仓库根标记（**两个都要**，缺一不算仓库根）。 */
function markersAt(dir: string): void {
  mkdirSync(dir, { recursive: true })
  for (const m of ROOT_MARKERS) writeFileSync(join(dir, m), '# synthetic marker (test fixture)\n')
}

/** 报告 → 便于断言的紧凑字符串（层级 + 违规目录名）。 */
function findingsOf(report: { findings: readonly { level: string; stray: readonly string[] }[] }): string[] {
  return report.findings.map((f) => `${f.level}:${JSON.stringify(f.stray)}`)
}

afterAll(() => {
  for (const dir of MADE) rmSync(dir, { recursive: true, force: true })
})

// ── 真实仓库：靠标记定位，不靠固定层数 ────────────────────────────────────

describe('内容产物落位（仓库根白名单）', () => {
  test('仓库根靠标记定位：不假定包目录之上几层', () => {
    const found = discoverRoot(TEST_DIR)
    if (!found.ok) throw new Error(found.message)
    // 证据：命中的那一层，磁盘上真的同时有两个标记（不是「定位结果自证」）。
    for (const m of ROOT_MARKERS) expect(existsSync(join(found.root, m)), m).toBe(true)
    // 且它是向上走时**第一个**命中的：走过的最后一层就是它。
    expect(found.searched.at(-1)).toBe(found.root)
    expect(found.root).toBe(resolve(TEST_DIR, '..', '..', '..'))
    expect(dirNames(found.root)).toContain('packages')
  })

  test('仓库根没有第三处放内容的地方', () => {
    const report = layoutReport(TEST_DIR)
    expect(findingsOf(report), report.message).toEqual([])
  })

  test('外层仓库根只在它**真是**仓库根（含 .git）时才检查', () => {
    const ws = realRoot()
    const report = layoutReport(TEST_DIR)
    expect(report.workspaceRoot).toBe(ws)
    expect(report.enclosingRoot).toBe(enclosingRepoRoot(ws))
    // 结构判据的两侧都要钉住：没有 .git ⇒ 没有外层 ⇒ 那一层一个字都不看。
    if (enclosingRepoRoot(ws) === null) {
      expect(existsSync(join(dirname(ws), '.git'))).toBe(false)
      expect(report.findings.filter((f) => f.level === 'enclosing')).toEqual([])
      expect(report.message).not.toContain('外层仓库根')
    }
  })

  test('凿洞必被抓：chess-12lang 这种根目录项目当场 FAIL', () => {
    // 反向验证（纪律 2）：喂给断言的就是真实事故里的那个名字。
    // 没有这条，上面那条绿灯只能证明「今天没违规」，证明不了「违规会被抓」。
    expect(strayRootDirs(['usine', 'garage-ii', 'chess-12lang'])).toEqual(['chess-12lang'])
    expect(strayRootDirs(['chess-12lang', 'some-new-series'])).toEqual(['chess-12lang', 'some-new-series'])
  })

  test('点目录与白名单目录不误伤', () => {
    // 误伤比漏抓更坏：一条会误报的门禁，人第二次就学会无视它。
    expect(strayRootDirs(['.git', '.venv', '.pytest_cache', '.DS_Store'])).toEqual([])
    expect(strayRootDirs([...ALLOWED_ROOT_DIRS])).toEqual([])
  })
})

describe('内容产物落位（usine/ 顶层白名单）', () => {
  test('usine/ 顶层没有第三处放内容的地方', () => {
    const root = realRoot()
    const stray = strayUsineDirs(dirNames(root))
    expect(
      stray,
      `usine/ 顶层多了 ${JSON.stringify(stray)}——内容项目只允许两处：`
      + 'usine/skills/<skill>/assets/（可复用资产，入库）或 '
      + 'usine/examples/<项目名>/（内容产物，不入库）。见 AGENTS.md「内容产物落位」。',
    ).toEqual([])
  })

  test('凿洞必被抓：usine/prompts 这种顶层项目当场 FAIL', () => {
    // 反向验证（纪律 2）：喂的就是 2026-10-21 真实抓到的那个名字。
    expect(strayUsineDirs(['packages', 'skills', 'prompts'])).toEqual(['prompts'])
    expect(strayUsineDirs(['packages', 'prompts', 'chess-12lang']))
      .toEqual(['chess-12lang', 'prompts'])
  })

  test('点目录与依赖目录不误伤', () => {
    expect(strayUsineDirs(['.venv', '.pytest_cache', 'node_modules'])).toEqual([])
    expect(strayUsineDirs([...ALLOWED_USINE_DIRS])).toEqual([])
  })

  test('跑测试长出来的 build/ 证据目录不误伤，但别的项目目录照抓', () => {
    // `build/` 是 publish.test.ts 的运行证据（.gitignore 兜住）；放行它是因为它
    // **属于测试证据这一类**，不是因为闸放宽了——同一次断言里必须证明别的照抓。
    expect(strayUsineDirs(['build'])).toEqual([])
    expect(strayUsineDirs(['build', 'prompts'])).toEqual(['prompts'])
  })

  test('口径没放宽：两张白名单与修复前逐条相同（定位修复 ≠ 放松）', () => {
    expect([...ALLOWED_USINE_DIRS].sort()).toEqual([
      'build', 'docs', 'examples', 'languages', 'lessons',
      'node_modules', 'packages', 'personas', 'skills', 'themes', 'tools',
    ])
    expect([...ALLOWED_ROOT_DIRS].sort()).toEqual([
      'config', 'docs', 'garage', 'garage-ii', 'theatre-ii', 'théâtre', 'usine',
    ])
  })
})

// ── 根定位：合成树（离线、不碰真 HOME）────────────────────────────────────

describe('仓库根定位（向上找标记，不假定层数）', () => {
  test('深度签出：真根之上还有无关目录，仍解析到真根并放行', () => {
    const home = tmpTree('feuille-layout-deep-')
    // 真实事故里的 home 形状：无关兄弟目录（AppData/、bin/、另一份工作树）
    mkDirs(home, ['AppData', 'bin', 'another-evolution_project'])
    const repo = join(home, 'explorateur')
    markersAt(repo)
    mkDirs(repo, ['packages', 'skills', 'examples', 'docs'])
    const pkgTest = join(repo, 'packages', 'gate', 'test')
    mkdirSync(pkgTest, { recursive: true })

    const found = discoverRoot(pkgTest)
    if (!found.ok) throw new Error(found.message)
    expect(found.root).toBe(resolve(repo)) // 不是 home

    const report = layoutReport(pkgTest)
    expect(report.ok, report.message).toBe(true)
    expect(report.workspaceRoot).toBe(resolve(repo))
    expect(report.findings).toEqual([])
    // home 没有 .git ⇒ 不是仓库根 ⇒ 它的无关目录一概不进判断。
    expect(report.enclosingRoot).toBe(null)
    expect(report.message).not.toContain('AppData')
    expect(report.message).not.toContain('another-evolution_project')
    expect(report.message).not.toContain('bin')
  })

  test('负向对照：一层标记都没有 ⇒ FAIL，报文点名标记与走过的层，不当第三处违规', () => {
    const orphan = tmpTree('feuille-layout-nomark-')
    mkDirs(orphan, ['home-like', 'packages'])
    const start = join(orphan, 'home-like', 'packages', 'gate', 'test')
    mkdirSync(start, { recursive: true })

    expect(discoverRoot(start).ok).toBe(false)
    const report = layoutReport(start)
    expect(report.ok).toBe(false)
    expect(report.workspaceRoot).toBe(null)
    expect(report.enclosingRoot).toBe(null)
    // 关键：没有把任何一层的目录当成本仓库的违规内容。
    expect(report.findings).toEqual([])
    expect(report.message).toContain('找不到仓库根')
    for (const m of ROOT_MARKERS) expect(report.message).toContain(m)
    expect(report.message).toContain(resolve(start)) // 说清从哪起走
    expect(report.message).not.toContain('第三处')    // 不是笼统的落位违规
  })

  test('正向对照：干净的合成根放行，塞进项目目录后当场 FAIL', () => {
    const outer = tmpTree('feuille-layout-dirty-')
    const repo = join(outer, 'usine')
    markersAt(repo)
    mkDirs(repo, ['packages', 'skills', 'examples'])
    const start = join(repo, 'packages', 'gate')
    mkdirSync(start, { recursive: true })
    const clean = layoutReport(start)
    expect(clean.ok, clean.message).toBe(true)

    mkDirs(repo, ['chess-12lang', 'prompts'])
    const report = layoutReport(start)
    expect(report.ok).toBe(false) // 根定位对了之后，判断照旧抓得住
    expect(report.workspaceRoot).toBe(resolve(repo))
    expect(findingsOf(report)).toEqual(['workspace:["chess-12lang","prompts"]'])
    expect(report.message).toContain('chess-12lang')
  })

  test('真有外层仓库根（父目录含 .git）时那一层照查；没有外层时那一层不查', () => {
    const outer = tmpTree('feuille-layout-outer-')
    const ws = join(outer, 'usine')
    markersAt(ws)
    mkDirs(ws, ['packages', 'skills'])
    const start = join(ws, 'packages')
    mkdirSync(start, { recursive: true })
    mkDirs(outer, ['AppData', 'bin'])

    // 没有 .git ⇒ 父目录不是仓库根 ⇒ 那一层一个字都不看（旧实现在这里红闸：
    // 它把 home 形状的 AppData/、bin/ 当成仓库根的违规内容）。
    expect(enclosingRepoRoot(ws)).toBe(null)
    const noOuter = layoutReport(start)
    expect(noOuter.enclosingRoot).toBe(null)
    expect(noOuter.ok, noOuter.message).toBe(true)
    expect(noOuter.message).not.toContain('AppData')

    // 真出现外层仓库根之后，同一批目录**才**进入判断——这正是口径该有的样子：
    // 它们是不是违规，取决于这一层是不是仓库根，而不是取决于父目录长得像 home。
    mkdirSync(join(outer, '.git'), { recursive: true })
    const nowOuter = layoutReport(start)
    expect(nowOuter.enclosingRoot).toBe(resolve(outer))
    expect(findingsOf(nowOuter)).toEqual([`enclosing:${JSON.stringify(['AppData', 'bin'])}`])
    expect(nowOuter.ok).toBe(false)
    // 清掉它们，回到干净的外层根继续钉「白名单放行」与「真违规照抓」。
    rmSync(join(outer, 'AppData'), { recursive: true, force: true })
    rmSync(join(outer, 'bin'), { recursive: true, force: true })
    expect(enclosingRepoRoot(ws)).toBe(resolve(outer))
    // 外层白名单里的目录照常放行
    mkDirs(outer, ['docs', 'config', 'usine'])
    const clean = layoutReport(start)
    expect(clean.enclosingRoot).toBe(resolve(outer))
    expect(clean.ok, clean.message).toBe(true)

    // 外层真长出项目目录 ⇒ FAIL，且只报外层那一层
    mkdirSync(join(outer, 'chess-12lang'), { recursive: true })
    const dirty = layoutReport(start)
    expect(dirty.ok).toBe(false)
    expect(findingsOf(dirty)).toEqual(['enclosing:["chess-12lang"]'])
  })
})

// ── vendored 引擎目录不得自带 .git ─────────────────────────────────────────
//
// 两条 RSI 线路的引擎（`théâtre/`、`theatre-ii/`）是**普通目录**：版本一律由
// 外层 explorateur 仓库统一管理，不维护第二份历史。
//
// 为什么这条要进机械门禁：2026-10-21 之前 `théâtre/` 带着一份 32.6 MB 的内嵌
// `.git`（HEAD 是 fork 后的上游快照），而同一轮的 `theatre-ii/` 没有——两条本该
// 平行的引擎线在磁盘上并不对称，文档里的说法与磁盘事实相反。这种偏差**不会自己
// 报错**：内嵌 `.git` 只要存在，在它下面跑 git 命令就会静默读错历史，而 wrapper
// 一律看起来成功。所以得由门禁说出来。
const ENGINE_DIRS = ['théâtre', 'theatre-ii'] as const

/** 引擎目录可以躺在工作区根，也可以躺在外层仓库根（真实布局），两处都看。 */
function engineBases(): string[] {
  const root = realRoot()
  const outer = enclosingRepoRoot(root)
  return outer ? [root, outer] : [root]
}

describe('两线引擎的版本统一由外层仓库管理', () => {
  test('引擎目录下没有自己的 .git', () => {
    const bases = engineBases()
    const stray = strayEngineRepos([...ENGINE_DIRS], (n) => bases.some((b) => existsSync(join(b, n, '.git'))))
    expect(
      stray,
      `引擎目录自带了 .git：${JSON.stringify(stray)}。两条引擎线都是普通目录，`
      + '版本统一由外层 explorateur 仓库管理——内嵌仓库会让该目录下的 git 命令'
      + '静默读到另一份历史。见 AGENTS.md 第一节与各 PROVENANCE.md 纪律第 1 条。',
    ).toEqual([])
  })

  test('凿洞必被抓：自带 .git 的引擎目录当场 FAIL', () => {
    // 反向验证（纪律 2）：断言必须真的能抓住违规，绿灯不能只证明「今天没违规」。
    expect(strayEngineRepos(['théâtre', 'theatre-ii'], (n) => n === 'théâtre')).toEqual(['théâtre'])
    expect(strayEngineRepos(['théâtre', 'theatre-ii'], () => false)).toEqual([])
  })
})
