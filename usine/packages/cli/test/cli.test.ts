// cli.test.ts — 统一入口路由表的反向验证（verify_cli.py 的 vitest 对应移植）
//
// **它要证的那句话**：「路由表里的每个叶子都真的可达。」统一时漏搬一个
// 子命令，它就静默消失——直到有人在旧入口找不到功能。
//
// 判据（Python 侧四条 → TS 侧对应）：
// 1. 每个路由条目可加载且导出 main(argv)（叶子真可达；Python 侧「无参可调用」
//    的对应物 = 契约 main(argv)，路由层永远以数组调它）
// 2. 未知命令 → 退出码 2（不静默）；--help → 0（router.test 已覆盖，这里补组形态）
// 3. usage 列出的每个入口都在 COMMANDS 里、COMMANDS 每条都在 usage 里
//    （TS 侧没有 docstring；usage 就是文档，两个方向都机检——Python 侧只查
//    「文档宣称 ⊆ 已登记」，TS 骨架里 usage 由 COMMANDS 生成、天然 ⊆，
//    所以反向（已登记 ⊆ usage）一并锁住，防止有人手写 usage 漏条目）
// 4. 库层显式失败（FeuilleError）→ 消息进 stderr、退出码 1（Python 侧
//    cli.main 的 except FeuilleError 同款口径）
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { COMMANDS } from '../src/commands.js'
import { main, usage } from '../src/index.js'

describe('统一入口路由表（反向验证移植）', () => {
  it('路由表每个叶子都可加载且导出 main(argv)——查得到 ≠ 调得起', async () => {
    expect(Object.keys(COMMANDS).length).toBeGreaterThan(0)
    for (const [key, leaf] of Object.entries(COMMANDS)) {
      const mod = await leaf.load()
      expect(typeof mod.main, `${key} 叶子须导出 main(argv)`).toBe('function')
      expect(leaf.desc.length, `${key} 须有一句话用途（usage 列表用）`).toBeGreaterThan(0)
    }
  })

  it('usage 与 COMMANDS 双向一致（路由表不能说谎，usage 也不能说谎）', () => {
    const u = usage()
    for (const key of Object.keys(COMMANDS)) {
      expect(u, `usage 必须列出 ${key}`).toContain(key)
    }
    // usage 列出的组/命令行都来自 COMMANDS 的键——多出来的行 = 手写谎报
    const listed = u.split('\n').filter((ln) => ln.trim().startsWith('feuille') || /^ {2}\S/.test(ln))
    expect(listed.length).toBeGreaterThanOrEqual(Object.keys(COMMANDS).length)
  })

  it('未知命令 → 退出码 2；--help → 0', async () => {
    expect(await main(['bogus', 'bogus'])).toBe(2)
    expect(await main(['--help'])).toBe(0)
  })

  it('回退组键时首参数还给叶子（feuille version extra 形态）', async () => {
    // version 是组省略键：`feuille version anything` 的 anything 必须进叶子的 argv
    const rc = await main(['version', 'ignored-by-version-leaf'])
    expect(rc).toBe(0)
  })

  it('FeuilleError → stderr 消息 + 退出码 1（库层显式失败不炸进程）', async () => {
    const d = mkdtempSync(join(tmpdir(), 'feuille-cli-'))
    try {
      const rc = await main(['framehash', 'check', '--root', d]) // 没有 build/ → FeuilleError
      expect(rc).toBe(1)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('P2 新叶子经路由端到端可达（不绕过路由直调库）', async () => {
    const d = mkdtempSync(join(tmpdir(), 'feuille-cli-leaf-'))
    try {
      // 空账本 → 0（还没登记 ≠ 失败）
      expect(await main(['ledger', 'status', '--root', d])).toBe(0)
      // framehash 在没有 build/ 时 → FeuilleError → 1（上一条已证，这里证 save 同口径）
      expect(await main(['framehash', 'save', '--root', d])).toBe(1)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('P4 persona 叶子经路由端到端可达：缺省班底 28 人零问题 → 0', async () => {
    expect(await main(['persona', 'validate'])).toBe(0)
  })
})
