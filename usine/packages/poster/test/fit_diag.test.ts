// fit_diag.test.ts — `poster fit-diag` 的**参数与 stdin 纪律**
//
// 为什么要有这条测试
// ------------------
// 2026-10-22 实测的事故：`fit-diag` 原来是「不给文件参数就读 stdin」。在**工具面**
// （dsh 的 `usine_poster`）里，叶子是**同进程**跑的（dsh-plugin 的 runMain 直接
// `await fn(argv)`），stdin 是**宿主自己那根永远不关的管道**——于是
// `readFileSync(0)` **永久阻塞**，把整条 rollout 的时间预算烧光：
//
//   B 线 4 条 rollout 的最后一个事件都是一条 `usine_poster fit-diag` 的 tool/call，
//   没有 tool/result，最后被 1800s / 3600s 的上限掐死。量到的全是「工具面挂死」，
//   不是「智能体搭场景搭得好不好」。
//
// 所以：**工具面里缺参数必须立刻报错退出（2），不许去读一块可能永远不会来的数据。**
// CLI 那条路不变：`| feuille poster fit-diag` 的管道用法照旧能读 stdin。
import { describe, expect, test } from 'vitest'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fit_diag } from '../src/index.js'

const DIAG = 'DIAG {"fonts":"Food SC:loaded","cells":[{"lang":"zh-CN","fs":48,"word":"寿司","overflowX":false,"overflowY":false}]} <html>'

describe('poster fit-diag：缺参数要立刻失败，不许挂在 stdin 上', () => {
  test('工具面口径（FEUILLE_STDIN=off）：空参返回 2，且不读 stdin', () => {
    const prev = process.env['FEUILLE_STDIN']
    process.env['FEUILLE_STDIN'] = 'off'
    try {
      // 旧实现在这里会**永久阻塞**（读 fd 0 = 宿主那根不关的管道）→ vitest 超时红。
      expect(fit_diag.main([])).toBe(2)
    } finally {
      if (prev === undefined) delete process.env['FEUILLE_STDIN']
      else process.env['FEUILLE_STDIN'] = prev
    }
  })

  test('文件不存在：返回 2（不是 stack trace）', () => {
    expect(fit_diag.main([join(tmpdir(), 'no-such-diag-file.txt')])).toBe(2)
  })

  test('给了文件：正常读（产线走的就是这条）', () => {
    const dir = mkdtempSync(join(tmpdir(), 'feuille-fitdiag-'))
    const f = join(dir, 'diag.txt')
    writeFileSync(f, DIAG, 'utf8')
    expect(fit_diag.main([f])).toBe(0)
  })
})
