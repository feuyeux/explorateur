// layout.test.ts — 内容产物落位的结构门禁（AGENTS.md「内容产物落位」）
//
// 规矩只有一句话：**生成出来的内容项目只允许两处**——
//
//   usine/skills/<skill>/assets/   可复用资产（模板/示例/夹具），随 git 版本化
//   usine/examples/<项目名>/        内容项目产物（成片/封面/文案），不入库
//
// **没有第三处。** 仓库根与 usine/ 顶层不许再长出项目目录。
//
// 为什么这道闸必须存在：2026-10-20 发现 `chess-12lang/` 直接长在仓库根并被
// 入库——222 个文件、99 个 LFS 对象共 129.5 MB。它的内容和产物都没毛病，
// **位置错了**。位置错误不会自己报错：它只在下一次 clone 时变成体积，
// 而且被追踪之后 .gitignore 也拦不住（已入库的文件忽略规则管不着）。
// 所以这条得由门禁说出来，不能靠「记得」。
//
// 全部是磁盘静态检查，不起浏览器、不跑产线（纪律 12）。
import { describe, expect, test } from 'vitest'
import { existsSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

/** packages/gate/test → usine 根（pnpm-workspace.yaml 所在层）。 */
const USINE = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
/** 仓库根——内容产物最容易被随手堆在这里的地方。 */
const REPO = join(USINE, '..')

/**
 * 允许出现在**仓库根**的目录。每一个都是「工具/引擎/适配层」，不是内容项目。
 *
 * 这张表要人手工改，是**故意的**：新增一个根目录时，必须停下来回答
 * 「这是不是又一处放内容的地方」。答「是」就该改成 skill 资产或进 examples/；
 * 答「不是」才往这里加一行。白名单比黑名单可靠——黑名单只拦已经犯过的错。
 */
const ALLOWED_ROOT_DIRS = new Set([
  'usine',        // feuille：TS 产线 + skills
  'garage',       // RSIAgent 适配层（改记忆）
  'garage-ii',    // harness2 适配层（改 harness 本身）
  'theatre-ii',   // harness2 引擎（vendor）
  'théâtre',      // RSIAgent 引擎（vendored fork）
  'config',       // 环境样例与本地配置（.env 由 .gitignore 兜底）
  // 工作区级**入门读物**（`self-evolution.md`：两条 RSI 线路怎么实现、怎么读读数）。
  // 它放仓库根是有理由的：读者是**第一次进这个仓库的人**，那时他还不知道该去
  // `garage-ii/` 还是 `théâtre/` 翻——放在子项目里等于要求先知道答案再去找问题。
  // 注意这条判的是「它是不是一处放内容产物的新地方」，答案是不是：它装的是
  // 文档，进 git，跟 `usine/docs/` 同类。**放行一个不是内容项目的地方，不等于
  // 放宽落位口径**——同一次断言里必须证明别的目录照抓（见下面那条凿洞用例）。
  'docs',
])

/**
 * 允许出现在 **`usine/` 顶层**的目录。
 *
 * 上面那张表只扫仓库根，而 `usine/` 顶层是同一个错误更容易复发的地方——
 * 2026-10-21 就在这里抓到 `usine/prompts/`：19 个入库文件、147.6 KB 的
 * 词汇图鉴提示词草稿。它们**全部是内容产物**（每一份都是某一轮某个词的
 * 提示词），按落位口径该进 `examples/`，而且其中草莓那份与
 * `skills/vocab-infographic/assets/example/strawberry/prompt.md` **逐字节相同**
 * ——同一份东西存了两遍，一遍入库一遍在 skill 里。
 *
 * 处置（同日完成）：草莓那份因逐字节重复直接删；另外 18 份（九大艺术 × 横竖两版）
 * 是**已过审的系列样例**、会被反复对账，按落位口径属资产 ⇒ 移进
 * `skills/vocab-infographic/assets/example/<词>/`，随 git 版本化，内容一字未改。
 * 所以现在这个用例抓的是一个**已清掉的**位置：它留着是为了在下次又有人
 * 「随手在项目根旁边建个 prompts/」时立刻响。
 *
 * 它之所以能长出来，正是因为本文件当时**只看仓库根**。只看一层等于只看
 * 一条边界，而「随手在项目根旁边建个文件夹」这件事不认层级。
 */
const ALLOWED_USINE_DIRS = new Set([
  'packages',     // 代码：十二包
  'skills',       // SKILL 资产（含 assets/ 可复用资产，入库）
  'examples',     // 内容项目产物（不入库）
  'docs',         // 文档
  'languages',    // 语种注册表（14 manifest）
  'personas',     // 人设目录与 schema
  'themes',       // 主题 token
  'lessons',      // 课件数据
  'tools',        // 开发期工具脚本
  'node_modules', // 依赖（由 .gitignore 兜底；点目录规则管不着它）
  // **例外，且只有这一个**：`packages/publish/test/publish.test.ts` 的证据目录
  // （`build/publish-verify/`，两个 json）。它是**测试跑出来的**、被 .gitignore
  // 兜住的运行证据，不是内容项目——放行它有据，放行一个「随手建的项目目录」
  // 没据。这条判的是「它属于哪一类」，不是「名字好不好看」。
  'build',
])

/**
 * 从目录名里挑出**该报错**的那些。
 *
 * 点目录（`.git` / `.venv` / `.pytest_cache`）一律跳过：它们是本机工具产物，
 * 既不是内容项目、也不该进索引，报出来只会训练人忽略这条门禁。
 */
export function strayRootDirs(names: string[]): string[] {
  return names
    .filter((n) => !n.startsWith('.'))
    .filter((n) => !ALLOWED_ROOT_DIRS.has(n))
    .sort()
}

/** 同一条判断，用在 `usine/` 顶层。 */
export function strayUsineDirs(names: string[]): string[] {
  return names
    .filter((n) => !n.startsWith('.'))
    .filter((n) => !ALLOWED_USINE_DIRS.has(n))
    .sort()
}

function dirNames(parent: string): string[] {
  return readdirSync(parent, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
}

function rootDirNames(): string[] {
  return dirNames(REPO)
}

describe('内容产物落位（仓库根白名单）', () => {
  test('仓库根没有第三处放内容的地方', () => {
    const stray = strayRootDirs(rootDirNames())
    expect(
      stray,
      `仓库根多了 ${JSON.stringify(stray)}——内容项目只允许两处：`
      + 'usine/skills/<skill>/assets/（可复用资产，入库）或 '
      + 'usine/examples/<项目名>/（内容产物，不入库）。见 AGENTS.md「内容产物落位」。',
    ).toEqual([])
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
    const stray = strayUsineDirs(dirNames(USINE))
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
    // `build/` 是 publish.test.ts 的运行证据（.gitignore 兜住）；它被放行是
    // 因为它**属于测试证据这一类**，不是因为闸放宽了。同一次断言里必须证明
    // 「放行 build 不等于放行一切」——否则这条白名单就成了补丁清单。
    expect(strayUsineDirs(['build'])).toEqual([])
    expect(strayUsineDirs(['build', 'prompts'])).toEqual(['prompts'])
  })
})

// ── vendored 引擎目录不得自带 .git ─────────────────────────────────────────
//
// 两条 RSI 线路的引擎（`théâtre/`、`theatre-ii/`）是**普通目录**：版本一律由
// 外层 explorateur 仓库统一管理，不维护第二份历史。
//
// 为什么这条要进机械门禁：2026-10-21 之前 `théâtre/` 带着一份 32.6 MB 的内嵌
// `.git`（HEAD 是 fork 后的上游快照），而同一轮的 `theatre-ii/` 没有——两条本该
// 平行的引擎线在磁盘上并不对称，文档里的说法（`theatre-ii/PROVENANCE.md` 说
// 「与 théâtre 的现状一致，它的 .git 也已被清掉」）与磁盘事实相反。
// 这种偏差**不会自己报错**：内嵌 `.git` 只要存在，在它下面跑 git 命令就会
// 静默读错历史（`git -C théâtre log` 读到的是上游那份，不是本仓库的改动），
// 而 wrapper 一律看起来成功。所以得由门禁说出来。
const ENGINE_DIRS = ['théâtre', 'theatre-ii'] as const

/** 从引擎目录名里挑出**自带 .git** 的那些（纯函数，便于反向验证）。 */
export function strayEngineRepos(names: string[], hasGit: (name: string) => boolean): string[] {
  return names.filter(hasGit).sort()
}

describe('两线引擎的版本统一由外层仓库管理', () => {
  test('引擎目录下没有自己的 .git', () => {
    const stray = strayEngineRepos([...ENGINE_DIRS], (n) => existsSync(join(REPO, n, '.git')))
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
