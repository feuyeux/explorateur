// skills-assets.test.ts — skill 资产里的可执行判据也要进全量门禁。
//
// 这不是重复测：`validate-facts.mjs` 的 `--self-test` 自身就是反向验证
// （好账本必过 + 占位符/未知来源/缺 source 必抓）。把它挂进 vitest，改坏
// 判据时 `pnpm verify` 当场红，而不是等交付前才有人跑。
//
// 含墨扫描（ink-scan.mjs）依赖 ffmpeg，跨平台 CI 不保证有；它的
// `--self-test` 保留为产线前置检查（两条命令都写在 assets/template/README.md）。
import { describe, expect, test } from 'vitest'
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

/** 找一个能跑的 Python：本 skill 的判据是 Python 脚本，Windows 上是 python，POSIX 上是 python3。 */
function findPython(): string | null {
  for (const exe of ['python', 'python3', 'py']) {
    const r = spawnSync(exe, ['--version'], { encoding: 'utf8' })
    if (r.status === 0) return exe
  }
  return null
}

describe('music-annotate-video 资产判据', () => {
  test('validate-facts 反向自测：好账本过、三类坏账必抓', () => {
    const script = join(ROOT, 'skills', 'music-annotate-video', 'assets', 'template', 'validate-facts.mjs')
    const r = spawnSync(process.execPath, [script, '--self-test'], { encoding: 'utf8' })
    const out = `${r.stdout ?? ''}${r.stderr ?? ''}`
    expect(r.status, out).toBe(0)
    expect(out).toContain('good=pass')
    expect(out).toContain('placeholder=caught')
    expect(out).toContain('unknown-source=caught')
    expect(out).toContain('missing-number-source=caught')
  })
})

// match-recap-video 的 19 环 selftest 聚合器。挂进来是因为它的纪律本来就是
// 「判据脚本自己带反向验证」——但反向验证只有被跑才算数：改坏 check_windows.py
// 的坏例判定时，光靠「文档写了会抓」不成立，得让 `pnpm verify` 当场红。
//
// cwd 固定在 skill 目录：那一环用 `node --import tsx`，node 按 cwd 解析 tsx
// （tsx 装在 usine/node_modules），从仓库根跑会 ERR_MODULE_NOT_FOUND——
// 那是环境错，不是判据错，不该让门禁红成别的意思。
describe('match-recap-video 判据 selftest', () => {
  test('全验收 19 环全过（任一环非零 = 门禁红）', () => {
    const py = findPython()
    expect(py, 'PATH 上找不到 Python（≥3.10）——本 skill 的判据是 Python 脚本，'
      + '门禁不能因为「跑不了」就当过').not.toBeNull()
    const skillDir = join(ROOT, 'skills', 'match-recap-video')
    const r = spawnSync(py!, ['scripts/verify_all.py'], {
      cwd: skillDir,
      encoding: 'utf8',
    })
    const out = `${r.stdout ?? ''}${r.stderr ?? ''}`
    expect(r.status, out).toBe(0)
    expect(out).toContain('19/19 环通过')
  }, 600_000)
})
