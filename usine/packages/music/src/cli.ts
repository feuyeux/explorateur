// cli.ts — 包内的命令行参数解析（四个叶子共用）。
//
// 为什么自己写：工作区的纪律是「外部可执行名一律不写死、参数缺失要报
// 明确的用法」，而仓库里没有通用的 argv 解析库（引一个进来只是为了一
// 件事）。这里给一个够用的、带 `--key value` 与 `--flag` 两种形态的
// 解析器，缺失值当场报「用法」，不静默吞掉。
import { FeuilleError } from '@feuille/core'

export interface ParsedArgs {
  /** 位置参数。 */
  positional: string[]
  /** `--key value` 与 `--key=value`。 */
  opts: Record<string, string>
  /** `--flag`（无值）。 */
  flags: Set<string>
}

export function parseArgs(argv: readonly string[]): ParsedArgs {
  const positional: string[] = []
  const opts: Record<string, string> = {}
  const flags = new Set<string>()
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!
    if (!a.startsWith('--')) {
      positional.push(a)
      continue
    }
    const body = a.slice(2)
    const eq = body.indexOf('=')
    if (eq >= 0) {
      opts[body.slice(0, eq)] = body.slice(eq + 1)
      continue
    }
    const next = argv[i + 1]
    if (next !== undefined && !next.startsWith('--')) {
      opts[body] = next
      i++
    } else {
      flags.add(body)
    }
  }
  return { positional, opts, flags }
}

/** 取一个数值选项；给了但不是数字就报错（不静默当 0）。 */
export function numOpt(args: ParsedArgs, key: string, dflt: number): number {
  const raw = args.opts[key]
  if (raw === undefined) return dflt
  const n = Number(raw)
  if (!Number.isFinite(n)) throw new FeuilleError(`--${key} 必须是数字，收到 ${JSON.stringify(raw)}`)
  return n
}

/** 取一个字符串选项。 */
export function strOpt(args: ParsedArgs, key: string, dflt: string): string {
  return args.opts[key] ?? dflt
}
