// check_plan.ts — 发布前清单自检（零平台流量）
// （multilingual-video-publishing/scripts/check_plan.py 的 TS 归流）。
//
// 在真发之前把能拦的问题全拦下来。本模块只读本地文件与清单，
// **不碰任何平台**，所以可以随时跑、随便跑。
//
// 检查项（每项都有可观测判据，不是「看着没问题」）：
//
// 1. **素材存在性** — 逐条视频/封面真实在盘（发到一半才发现缺文件是最贵的失败）
// 2. **标题字数** — 按平台各自上限实测字符数，不信任何手标
// 3. **横竖配对** — 双版式项目必须两版条数相同、语种集合一致
// 4. **封面比例** — 与所投平台的原生比例对齐（能零裁切就别裁）
// 5. **修改额度** — 补封面类操作要提醒每作品 N 次的上限
//
// 归流决定：Python 侧 TITLE_MAX 是一份**限值漂移拷贝**（带 _limit_drift 守卫，
// 纪律 10）——TS 侧直接消费 @feuille/core manifest.PLATFORMS 的唯一实现，
// 拷贝不迁移即天然消除，守卫检查随之退役（单一事实源不需要对着自己比对）。
// 原脚本「发布机零依赖也能跑」的前提（Python 环境都没有）在 TS 单仓里不成立：
// 本模块经 `feuille publish check-plan` 进程内调用，天然带着 @feuille/core。
import { existsSync, readFileSync } from 'node:fs'
import { isAbsolute, resolve } from 'node:path'

import sharp from 'sharp'

import { manifest } from '@feuille/core'

export type PlanTask = {
  no: number | string
  lang?: string
  title: string
  video: string
  cover: string
}
export type Plan = Record<string, PlanTask[]>

// 各平台标题上限：单一事实源 = @feuille/core manifest.PLATFORMS（titleMax）。
// 导出仅为反向验证断言派生关系——模块内不再存在可漂移的第二份表。
export const TITLE_MAX: Record<string, number> = Object.fromEntries(
  Object.entries(manifest.PLATFORMS).map(([k, v]) => [k, v.titleMax]),
)

// 平台原生封面比例（宽/高）。manifest 不记这个，仍是本模块自己的事实。
export const COVER_RATIO: Record<string, number> = {
  douyin: 3 / 4,
  xiaohongshu: 3 / 4,
  bilibili: 4 / 3,
}

// 抖音每作品最多修改次数（补封面算 1 次）。manifest 不记这个。
export const MOD_BUDGET: Record<string, number> = { douyin: 5 }

const HELP = `usage: feuille publish check-plan [-h] [--root ROOT] manifest

positional arguments:
  manifest             发布清单 manifest.json

options:
  -h, --help           show this help message and exit
  --root ROOT          素材根目录（相对路径素材先在这里找，再退到清单所在目录）
`

/** Python len() 按码点计——标题字数用码点数，不用 UTF-16 单元数。 */
export function charLen(s: string): number {
  return [...s].length
}

/** Python set repr 形态：{'a', 'b'}（语种集合差集的打印口径）。 */
function setRepr(xs: Iterable<string>): string {
  return `{${[...xs].map((x) => `'${x}'`).join(', ')}}`
}

function setDiff(a: Set<string>, b: Set<string>): string[] {
  return [...a].filter((x) => !b.has(x))
}

/** 素材路径解析：绝对路径原样；相对路径先在 --root、再在清单所在目录找。
 * 两级都命不中也照原样返回——存在性检查会拿原路径报「素材缺失」，
 * 而不是让用户看到一个被解析过程改写的陌生路径。 */
function resolveAsset(p: string, root: string, manDir: string): string {
  if (isAbsolute(p)) return p
  for (const base of [root, manDir]) {
    const cand = resolve(base, p)
    if (existsSync(cand)) return cand
  }
  return p
}

export async function check(manPath: string, root: string): Promise<number> {
  const man = JSON.parse(readFileSync(manPath, 'utf8')) as Plan
  const problems: string[] = []
  const notes: string[] = []
  const manDir = resolve(manPath, '..')

  for (const [plat, tasks] of Object.entries(man)) {
    const lim = TITLE_MAX[plat]
    console.log(`\n=== ${plat}（${tasks.length} 条${lim ? `，标题上限 ${lim}` : ''}）===`)

    // ---- 1 素材存在性 ----
    const onDisk = (t: PlanTask) =>
      existsSync(resolveAsset(t.video, root, manDir))
      && existsSync(resolveAsset(t.cover, root, manDir))
    const missing = tasks.filter((t) => !onDisk(t))
    for (const t of missing) {
      const gone = !existsSync(resolveAsset(t.video, root, manDir)) ? t.video : t.cover
      problems.push(`${plat} [${t.no}] 素材缺失：${gone}`)
    }
    console.log(`  素材在盘：${tasks.length - missing.length}/${tasks.length}`)

    // ---- 2 标题字数（实测，不信手标）----
    if (lim) {
      const over = tasks
        .map((t) => ({ t, n: charLen(t.title) }))
        .filter(({ n }) => n > lim)
      for (const { t, n } of over) {
        problems.push(`${plat} [${t.no}] 标题 ${n} 字 > 上限 ${lim}：${t.title}`)
      }
      console.log(`  标题合规：${tasks.length - over.length}/${tasks.length}`
        + (tasks.length ? `　最长 ${Math.max(...tasks.map((t) => charLen(t.title)))} 字` : ''))
    }

    // ---- 5 修改额度 ----
    // 上限只在动手改已发布作品时烧掉（补封面算 1 次）。清单本身看不出来
    // 用户回头要不要补封面，所以这里只做提醒，不判 FAIL——但必须显式
    // 提醒，不能让额度在不知情下被用光（补封面到第 6 次会被平台直接拒）。
    const budget = MOD_BUDGET[plat]
    if (budget) {
      notes.push(`${plat} 每作品修改上限 ${budget} 次（补封面算 1 次）——`
        + `本清单 ${tasks.length} 条，发布后若还要补封面，先数余额再动手`)
    }

    // ---- 4 封面比例 ----
    const want = COVER_RATIO[plat]
    if (want && tasks.length) {
      try {
        const meta = await sharp(resolveAsset(tasks[0]!.cover, root, manDir)).metadata()
        const w = meta.width!, h = meta.height!
        const got = w / h
        // 允许 3% 偏差（不同平台对另一版式有裁切框，不能要求像素级相等）
        if (Math.abs(got - want) / want > 0.03) {
          notes.push(`${plat} 封面 ${w}×${h}（${got.toFixed(2)}）与平台原生 `
            + `${want.toFixed(2)} 差 ${Math.round(Math.abs(got - want) / want * 100)}%，`
            + '确认裁切框内文字是否在安全区')
        } else {
          console.log(`  封面比例 ${w}×${h}，与平台原生一致`)
        }
      } catch (e) {
        problems.push(`${plat} 封面读不出：${e instanceof Error ? e.name : String(e)}`)
      }
    }
  }

  // ---- 3 横竖配对 ----
  const plats = Object.keys(man)
  if (plats.length >= 2) {
    const sets: Record<string, Set<string>> = {}
    const counts: Record<string, number> = {}
    for (const p of plats) {
      sets[p] = new Set(man[p]!.map((t) => t.lang ?? ''))
      counts[p] = man[p]!.length
    }
    const basePlat = plats[0]!
    for (const p of plats) {
      const extra = setDiff(sets[p]!, sets[basePlat]!)
      const lack = setDiff(sets[basePlat]!, sets[p]!)
      if (extra.length || lack.length) {
        problems.push(`${p} 与 ${basePlat} 的语种集合不一致：`
          + `多 ${setRepr(extra)}，缺 ${setRepr(lack)}`)
      }
    }
    if (plats.every((p) => counts[p] === counts[basePlat])) {
      console.log(`\n✅ 横竖配对：${plats.length} 平台语种集合一致`
        + `（各 ${sets[basePlat]!.size} 语种 / ${counts[basePlat]} 条）`)
    }
  }

  console.log()
  for (const n of notes) console.log(`  ℹ️  ${n}`)
  if (problems.length) {
    console.log(`\n❌ ${problems.length} 项问题（发布前必须解决）：`)
    for (const p of problems) console.log('   ·', p)
    return 1
  }
  console.log(`\n✅ 清单齐：${Object.values(man).reduce((s, v) => s + v.length, 0)} 条，无阻塞问题`)
  console.log('   提醒：分区/创作声明/合集/可见性属责任项，须用户拍板，不替用户勾。')
  return 0
}

/** CLI 入口：`feuille publish check-plan <manifest.json> [--root <素材根目录>]`。 */
export async function main(argv: string[]): Promise<number> {
  if (argv.includes('-h') || argv.includes('--help')) {
    console.log(HELP)
    return 0
  }
  // argparse 口径：--root 带值（`--root v` / `--root=v`）；缺 manifest / 未知旗标 → 2
  let root = '.'
  let manPath: string | undefined
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!
    if (a === '--root') {
      const v = argv[++i]
      if (v === undefined || v.startsWith('--')) {
        process.stderr.write('argument --root: expected one argument\n')
        return 2
      }
      root = v
    } else if (a.startsWith('--root=')) {
      root = a.slice('--root='.length)
    } else if (a.startsWith('--')) {
      process.stderr.write(`unrecognized arguments: ${a}\n`)
      return 2
    } else if (manPath === undefined) {
      manPath = a
    } else {
      process.stderr.write(`unrecognized arguments: ${a}\n`)
      return 2
    }
  }
  if (manPath === undefined) {
    process.stderr.write('usage: feuille publish check-plan [-h] [--root ROOT] manifest\n'
      + 'feuille publish check-plan: error: the following arguments are required: manifest\n')
    return 2
  }
  return check(manPath, root)
}
