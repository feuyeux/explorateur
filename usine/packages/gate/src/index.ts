// packages/gate/src/index.ts
//
// 内容产物落位的结构门禁（AGENTS.md「内容产物落位」）——这里只有**判断**与**根定位**，
// 读真实磁盘的用例在 ../test/layout.test.ts。
//
// 规矩只有一句话：**生成出来的内容项目只允许两处**——
//
//   usine/skills/<skill>/assets/   可复用资产（模板/示例/夹具），随 git 版本化
//   usine/examples/<项目名>/        内容项目产物（成片/封面/文案），不入库
//
// **没有第三处。** 仓库根与 usine/ 顶层不许再长出项目目录。
//
// 为什么这道闸必须存在：2026-10-20 发现 `chess-12lang/` 直接长在仓库根并被入库——
// 222 个文件、99 个 LFS 对象共 129.5 MB。它的内容和产物都没毛病，**位置错了**。
// 位置错误不会自己报错：它只在下一次 clone 时变成体积，而且被追踪之后 .gitignore
// 也拦不住（已入库的文件忽略规则管不着）。所以得由门禁说出来，不能靠「记得」。
//
// ── 2026-10-22 根定位修复（本次改动）────────────────────────────────────────
// 旧定位（在 layout.test.ts 里）：
//     const USINE = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
//     const REPO = join(USINE, '..')            // ← 假定「上一层就是仓库根」
// —— 这条 `..` 假定「包目录之上三层 = 工作区」且「工作区上一层 = 仓库根」。
// 当仓库被签出在用户 home 的下一层（home 里还有 AppData/、bin/、另一份 evolution_project
// 工作树）时，REPO 指到 home 本身：home 的无关目录被当成本仓库的违规内容，门禁在候选
// 代码完全正确的机器上报 '仓库根没有第三处放内容的地方'，红闸在合并时拒绝一切。
// **位置找错了，判断再对也是错的。**
//
// 新定位：从包目录（或任何起点）向上逐级走，第一个**同时含 ROOT_MARKERS**
// （pnpm-workspace.yaml 与 ownership.json）的目录就是工作区根。整条链走完都没找到，
// 门禁照样 FAIL，但报文说清「找的是什么标记、从哪起走、走过哪些层」——
// 绝不把某一层的无关目录冒充违规内容。
//
// 口径一个字都没放宽：strayUsineDirs / strayRootDirs 用的还是原来那两张白名单表
// （这是 locator fix，不是 relaxation）。外层 explorateur 仓库根只在它**确实是**
// 一个仓库根（含 .git）时才检查——没有外层时，那一层没有「第三处」可言。
//
// 文件名是 index.ts 而不是 layout.ts：ownership.json 的模块宇宙（packages/*/src 下每个
// 源文件必须且只能被声明一次）把桶文件 index.ts 与 *.d.ts 排除在外，所以落在这里
// **不需要**动 ownership.json（本项目只许改两个文件）。若要按语义改名为 layout.ts，
// 必须同时在 ownership.json 里声明 `gate.layout`——那是第三个文件，记为 follow-up。
import { existsSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'

/** 认「工作区根」用的标记：必须**同时**出现在同一层，缺一不算。 */
export const ROOT_MARKERS = ['pnpm-workspace.yaml', 'ownership.json'] as const

export type RootDiscovery =
  | { readonly ok: true; readonly root: string; readonly searched: readonly string[] }
  | { readonly ok: false; readonly searched: readonly string[]; readonly message: string }

/**
 * 从 `start` 向上逐级走，返回第一个同时含 `markers` 的目录。
 *
 * 为什么不是 `join(start, '..')`：那把一个**位置假设**（包目录的上一层/上三层就是
 * 仓库根）写死进了判断里。同一份代码在别的签出位置上会把完全无关的目录当仓库根，
 * 于是报出一堆「违规」——错的不是被报的目录，是定位。
 * 走到文件系统根（`dirname(dir) === dir`）就停，绝不越界去看别人的 home。
 */
export function discoverRoot(
  start: string,
  markers: readonly string[] = ROOT_MARKERS,
): RootDiscovery {
  let dir = resolve(start)
  const searched: string[] = []
  for (;;) {
    searched.push(dir)
    if (markers.every((m) => existsSync(join(dir, m)))) return { ok: true, root: dir, searched }
    const parent = dirname(dir)
    if (parent === dir) break // 到盘符 / 文件系统根，再往上没有了
    dir = parent
  }
  const names = markers.map((m) => `「${m}」`).join(' + ')
  return {
    ok: false,
    searched,
    message:
      `找不到仓库根：从 ${resolve(start)} 起向上逐层查找同时含 ${names} 的那一层，`
      + `走完 ${searched.length} 层（${searched.join(' → ')}），没有任何一层同时含这些标记。`
      + '本检查靠标记定位仓库根，不假定「包目录的上一层就是仓库根」——所以这里报的是'
      + '「标记没找到」，而不是把某一层的无关目录当成违规内容。'
      + '排查：确认当前目录在仓库内，且 pnpm-workspace.yaml 与 ownership.json 都在仓库根。',
  }
}

/**
 * 外层 explorateur 仓库根：只有当工作区根**被签出在另一个仓库里**时才存在。
 *
 * 判据是结构性的（父目录是版本库根，含 `.git`），不是「父目录就是仓库根」这个假设。
 * 没有外层就返回 null：一个陌生 home 里的 AppData/、bin/ 不是本仓库的落位问题，
 * 把它们报成违规只会训练人忽略这条门禁。
 */
export function enclosingRepoRoot(workspaceRoot: string): string | null {
  const ws = resolve(workspaceRoot)
  const parent = dirname(ws)
  if (parent === ws) return null
  if (!existsSync(join(parent, '.git'))) return null
  return parent
}

/**
 * 允许出现在**仓库根**（外层 explorateur 仓库根）的目录。每一个都是「工具/引擎/适配层」，
 * 不是内容项目。这张表要人手工改，是**故意的**：新增一个根目录时，必须停下来回答
 * 「这是不是又一处放内容的地方」。白名单比黑名单可靠——黑名单只拦已经犯过的错。
 */
export const ALLOWED_ROOT_DIRS: ReadonlySet<string> = new Set([
  'usine',        // feuille：TS 产线 + skills
  'garage',       // RSIAgent 适配层（改记忆）
  'garage-ii',    // harness2 适配层（改 harness 本身）
  'theatre-ii',   // harness2 引擎（vendor）
  'théâtre',      // RSIAgent 引擎（vendored fork）
  'config',       // 环境样例与本地配置（.env 由 .gitignore 兜底）
  // 工作区级**入门读物**：读者是第一次进这个仓库的人，放在仓库根是有理由的。
  // 它装的是文档、进 git，跟 usine/docs/ 同类：判它不是内容产物，不是放宽口径。
  'docs',
])

/**
 * 允许出现在 **`usine/` 顶层**（= 本工作区根）的目录。
 *
 * 上面那张表只扫外层仓库根，而工作区顶层是同一个错误更容易复发的地方——
 * 2026-10-21 就在这里抓到 `usine/prompts/`：19 个入库文件、147.6 KB 的提示词草稿，
 * 全部是内容产物，该进 examples/。只看一层等于只看一条边界，而「随手在项目根旁边
 * 建个文件夹」这件事不认层级。
 */
export const ALLOWED_USINE_DIRS: ReadonlySet<string> = new Set([
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
  // （`build/publish-verify/`，两个 json）。它是**测试跑出来的**、被 .gitignore 兜住的
  // 运行证据，不是内容项目——放行它有据，放行一个「随手建的项目目录」没据。
  'build',
])

/**
 * 从目录名里挑出**该报错**的那些。
 *
 * 点目录（`.git` / `.venv` / `.pytest_cache`）一律跳过：它们是本机工具产物，
 * 既不是内容项目、也不该进索引，报出来只会训练人忽略这条门禁。
 */
export function strayRootDirs(names: readonly string[]): string[] {
  return names
    .filter((n) => !n.startsWith('.'))
    .filter((n) => !ALLOWED_ROOT_DIRS.has(n))
    .sort()
}

/** 同一条判断，用在 `usine/` 顶层（＝工作区根）。 */
export function strayUsineDirs(names: readonly string[]): string[] {
  return names
    .filter((n) => !n.startsWith('.'))
    .filter((n) => !ALLOWED_USINE_DIRS.has(n))
    .sort()
}

/** 目录名（只取目录，点目录也在内，过滤交给 stray*）。 */
export function dirNames(parent: string): string[] {
  return readdirSync(parent, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
}

export interface LevelFinding {
  /** workspace ＝ usine 工作区根；enclosing ＝ 外层 explorateur 仓库根。 */
  readonly level: 'workspace' | 'enclosing'
  readonly dir: string
  readonly stray: readonly string[]
}

export interface LayoutReport {
  readonly ok: boolean
  readonly workspaceRoot: string | null
  readonly enclosingRoot: string | null
  readonly searched: readonly string[]
  readonly findings: readonly LevelFinding[]
  /** 给操作者看的一句话：合规路径，或标记缺失 / 具体违规（都点名目录与原因）。 */
  readonly message: string
}

function describeFinding(f: LevelFinding): string {
  const where = f.level === 'workspace' ? `工作区根 ${f.dir}` : `外层仓库根 ${f.dir}`
  return `${where} 多了 ${JSON.stringify(f.stray)}——内容项目只允许两处：`
    + 'usine/skills/<skill>/assets/（可复用资产，入库）或 '
    + 'usine/examples/<项目名>/（内容产物，不入库）。见 AGENTS.md「内容产物落位」。'
}

/**
 * 完整落位报告：先结构化定位仓库根，再逐层用**原样**的白名单判。
 *
 * 违规（ok:false）只有三种来源：①标记找不到（报文点名标记与走过的层）；
 * ②工作区根多了目录；③真有外层仓库根时它多了目录。②③之外的目录一概不看。
 */
export function layoutReport(start: string): LayoutReport {
  const found = discoverRoot(start)
  if (!found.ok) {
    return {
      ok: false,
      workspaceRoot: null,
      enclosingRoot: null,
      searched: found.searched,
      findings: [],
      message: found.message,
    }
  }
  const ws = found.root
  const outer = enclosingRepoRoot(ws)
  const findings: LevelFinding[] = []
  const strayWs = strayUsineDirs(dirNames(ws))
  if (strayWs.length) findings.push({ level: 'workspace', dir: ws, stray: strayWs })
  if (outer) {
    const strayOuter = strayRootDirs(dirNames(outer))
    if (strayOuter.length) findings.push({ level: 'enclosing', dir: outer, stray: strayOuter })
  }
  const ok = findings.length === 0
  const message = ok
    ? `落位合规：仓库根 ${ws}（靠 ${ROOT_MARKERS.join(' + ')} 定位，走过 ${found.searched.length} 层）`
      + (outer ? `；外层仓库根 ${outer}` : '；无外层 explorateur 仓库根（父目录不是仓库根），跳过那一层')
    : findings.map(describeFinding).join('；')
  return { ok, workspaceRoot: ws, enclosingRoot: outer, searched: found.searched, findings, message }
}

/**
 * 从引擎目录名里挑出**自带 `.git`** 的那些（纯函数，便于反向验证）。
 *
 * 两条 RSI 线路的引擎（`théâtre/`、`theatre-ii/`）是**普通目录**：版本一律由外层仓库
 * 统一管理，不维护第二份历史。内嵌 `.git` 只要存在，在它下面跑 git 命令就会静默读错
 * 历史（`git -C théâtre log` 读到上游那份），而 wrapper 一律看起来成功。
 */
export function strayEngineRepos(
  names: readonly string[],
  hasGit: (name: string) => boolean,
): string[] {
  return names.filter((n) => hasGit(n)).sort()
}
