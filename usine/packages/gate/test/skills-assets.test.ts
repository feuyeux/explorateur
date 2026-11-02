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
