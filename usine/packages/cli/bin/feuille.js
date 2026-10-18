#!/usr/bin/env node
// feuille CLI bin 包装：node --import tsx 直跑 src/main.ts（TS 源码直跑，无构建步骤）。
// `pnpm install` 后经 workspace bin 链接，`pnpm exec feuille <组> <命令>` 即达。
// tsx 从本包装位置解析（createRequire），不依赖调用方 cwd；退出码原样透传。
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'

const require = createRequire(import.meta.url)
const tsx = pathToFileURL(require.resolve('tsx')).href
const mainTs = fileURLToPath(new URL('../src/main.ts', import.meta.url))

const r = spawnSync(process.execPath, ['--import', tsx, mainTs, ...process.argv.slice(2)], {
  stdio: 'inherit',
})
if (r.error) throw r.error
process.exit(r.status ?? 1)
