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
import { readdirSync } from 'node:fs'
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
  'plan',         // 规划文档
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

function rootDirNames(): string[] {
  return readdirSync(REPO, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
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
