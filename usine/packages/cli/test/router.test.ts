import { describe, expect, it } from 'vitest'
import { main, resolveCommand, usage } from '../src/index.js'

describe('cli 路由表（数据，不是 if/elif）', () => {
  it('version 叶子可查到且可加载', async () => {
    const leaf = resolveCommand('version', '')
    expect(leaf).toBeDefined()
    const mod = await leaf!.load()
    expect(typeof mod.main).toBe('function')
  })

  it('未知命令退出码 2（与 Python 侧口径一致）', async () => {
    const rc = await main(['nope', 'nada'])
    expect(rc).toBe(2)
  })

  it('无参数 / --help → usage + 退出码 0（与 Python 侧口径一致）', async () => {
    for (const args of [[], ['-h'], ['--help'], ['help']] as const) {
      const rc = await main([...args])
      expect(rc).toBe(0)
    }
    expect(usage()).toContain('version')
  })

  it('version 叶子执行返回 0', async () => {
    const rc = await main(['version'])
    expect(rc).toBe(0)
  })
})
