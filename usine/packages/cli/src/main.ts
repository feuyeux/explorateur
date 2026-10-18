// main.ts —— 路由器：弹组与命令、查表、懒加载、残余 argv 原样交给叶子。
// 未知命令 → usage + 退出码 2（与 Python 侧口径一致）。
// FeuilleError（库层显式失败的唯一通道）→ 消息到 stderr、退出码 1——
// 与 Python 侧 cli.main 的 except FeuilleError 同一口径。

import { pathToFileURL } from 'node:url'

import { FeuilleError } from '@feuille/core'

import { COMMANDS, resolveCommand } from './commands.js'

export function usage(): string {
  const rows = Object.entries(COMMANDS)
    .map(([k, v]) => `  ${k.padEnd(24)} ${v.desc}`)
    .join('\n')
  return `用法：feuille <组> <命令> [参数…]\n${rows}\n`
}

export async function main(argv: string[] = process.argv.slice(2)): Promise<number> {
  const [grp, cmd, ...rest] = argv
  if (!grp || ['-h', '--help', 'help'].includes(grp)) {
    process.stdout.write(usage())
    return 0
  }
  const leaf = resolveCommand(grp, cmd ?? '')
  if (!leaf) {
    process.stderr.write(`未知命令：${grp} ${cmd ?? ''}\n\n${usage()}`)
    return 2
  }
  // 精确命中：cmd 已被路由层消化，叶子拿 rest。
  // 回退到组省略键：cmd 不是本组真子命令，而是叶子的**第一个参数**
  // （`feuille verify --only tts` 的 cmd="--only"）——必须还回 argv，
  // 叶子拿到的才是真实残余参数（Python 侧 argv.insert(0, cmd) 同款契约）。
  const exact = cmd !== undefined && COMMANDS[`${grp}/${cmd}`] !== undefined
  const leafArgv = exact ? rest : cmd === undefined ? [] : [cmd, ...rest]
  try {
    const mod = await leaf.load()
    return await mod.main(leafArgv)
  } catch (e) {
    if (e instanceof FeuilleError) {
      process.stderr.write(`${e.message}\n`)
      return 1
    }
    throw e
  }
}

// ESM 入口判定：作为脚本直跑时执行；被 import（测试/叶子）时不执行。
const invokedAs = process.argv[1] ? pathToFileURL(process.argv[1]).href : ''
if (invokedAs === import.meta.url) {
  main().then(
    (rc) => process.exit(rc),
    (err) => {
      process.stderr.write(`${err}\n`)
      process.exit(1)
    },
  )
}
