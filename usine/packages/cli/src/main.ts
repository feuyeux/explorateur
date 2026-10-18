// main.ts —— 路由器：弹组与命令、查表、懒加载、残余 argv 原样交给叶子。
// 未知命令 → usage + 退出码 2（与 Python 侧口径一致）。

import { pathToFileURL } from 'node:url'

import { COMMANDS, resolveCommand } from './commands.js'

export function usage(): string {
  const rows = Object.entries(COMMANDS)
    .map(([k, v]) => `  ${k.padEnd(24)} ${v.desc}`)
    .join('\n')
  return `用法：feuille <组> <命令> [参数…]\n${rows}\n`
}

export async function main(argv: string[] = process.argv.slice(2)): Promise<number> {
  const [grp, cmd, ...rest] = argv
  if (!grp) {
    process.stdout.write(usage())
    return 2
  }
  const leaf = resolveCommand(grp, cmd ?? '')
  if (!leaf) {
    process.stderr.write(`未知命令：${grp} ${cmd ?? ''}\n\n${usage()}`)
    return 2
  }
  // 路由层消化掉的首参数必须还给 argv（Python 侧同款契约）
  const leafArgv = cmd === undefined ? [] : rest
  const mod = await leaf.load()
  return await mod.main(leafArgv)
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
