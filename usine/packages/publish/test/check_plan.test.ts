// check_plan.test.ts — 发布前清单自检的反向验证
// （multilingual-video-publishing/scripts/check_plan.py 的 TS 归流；坏数据必 FAIL）。
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import sharp from 'sharp'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { manifest } from '@feuille/core'

import * as check_plan from '../src/check_plan.js'

afterEach(() => {
  vi.restoreAllMocks()
})

function makeTmp(): string {
  return mkdtempSync(join(tmpdir(), 'check-plan-test-'))
}

function captureLog(): { log: string[]; spy: ReturnType<typeof vi.spyOn> } {
  const log: string[] = []
  const spy = vi.spyOn(console, 'log').mockImplementation((...a: unknown[]) => {
    log.push(a.map(String).join(' '))
  })
  return { log, spy }
}

type Task = { no: number; lang: string; title: string; video: string; cover: string }

async function makeAssets(d: string, langs: string[], coverW = 300, coverH = 400): Promise<void> {
  for (const lang of langs) {
    writeFileSync(join(d, `${lang}.mp4`), 'x') // 存在性只查在盘，不解码
    await sharp({ create: { width: coverW, height: coverH, channels: 3, background: '#884433' } })
      .png().toFile(join(d, `${lang}.png`))
  }
}

function planFor(d: string, plat: string, langs: string[], title: (l: string) => string): Record<string, Task[]> {
  return {
    [plat]: langs.map((l, i) => ({
      no: i + 1, lang: l, title: title(l),
      video: join(d, `${l}.mp4`), cover: join(d, `${l}.png`),
    })),
  }
}

describe('check_plan：限值单一事实源（Python 侧漂移拷贝 + _limit_drift 守卫随归流退役）', () => {
  it('TITLE_MAX 派生自 manifest.PLATFORMS.titleMax，逐平台逐项一致', () => {
    // 不再存在可漂移的第二份表——这里断的是派生关系与取值本身
    expect(Object.keys(check_plan.TITLE_MAX)).toEqual(Object.keys(manifest.PLATFORMS))
    for (const [plat, meta] of Object.entries(manifest.PLATFORMS)) {
      expect(check_plan.TITLE_MAX[plat]).toBe(meta.titleMax)
    }
    expect(check_plan.TITLE_MAX).toEqual({ douyin: 30, xiaohongshu: 20, bilibili: 80, zhihu: 100 })
  })

  it('charLen：码点计数（Python len 口径），emoji 算 1 不算 2', () => {
    expect(check_plan.charLen('abc')).toBe(3)
    expect(check_plan.charLen('落叶')).toBe(2)
    expect(check_plan.charLen('🍁')).toBe(1)
  })
})

describe('check_plan.check：六项判据逐条（坏数据必 FAIL）', () => {
  it('清单齐 → 0：素材在盘、标题合规、横竖配对一致、封面比例对齐', async () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      await makeAssets(d, ['en-US', 'ru-RU'])
      const man = {
        douyin: planFor(d, 'douyin', ['en-US', 'ru-RU'], (l) => `${l} 秋叶`).douyin,
        xiaohongshu: planFor(d, 'xiaohongshu', ['en-US', 'ru-RU'], (l) => `${l} 落叶`).xiaohongshu,
      }
      const manPath = join(d, 'manifest.json')
      writeFileSync(manPath, JSON.stringify(man))
      expect(await check_plan.check(manPath, d)).toBe(0)
      expect(log.some((l) => l.includes('✅ 横竖配对：2 平台语种集合一致'))).toBe(true)
      expect(log.some((l) => l.includes('✅ 清单齐：4 条，无阻塞问题'))).toBe(true)
      expect(log.some((l) => l.includes('封面比例 300×400，与平台原生一致'))).toBe(true)
      // 抖音修改额度提醒（只提醒不判 FAIL）
      expect(log.some((l) => l.includes('douyin 每作品修改上限 5 次'))).toBe(true)
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('素材缺失 → 1，报缺的是原路径不是被解析改写的路径', async () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      const man = planFor(d, 'douyin', ['en-US'], (l) => `${l} 秋`)
      const manPath = join(d, 'manifest.json')
      writeFileSync(manPath, JSON.stringify(man))
      expect(await check_plan.check(manPath, d)).toBe(1)
      // 视频与封面都不在盘 → 两项问题（素材缺失 + 封面读不出），Python 同口径
      expect(log.some((l) => l.includes('❌ 2 项问题'))).toBe(true)
      expect(log.some((l) => l.includes('素材缺失：') && l.includes('en-US.mp4'))).toBe(true)
      expect(log.some((l) => l.includes('douyin 封面读不出'))).toBe(true)
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('标题超限 → 1（抖音 30 / 小红书 20，逐平台上限实测）', async () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      await makeAssets(d, ['en-US'])
      const long30 = 'a'.repeat(31)
      const long20 = 'b'.repeat(21)
      const man = {
        douyin: planFor(d, 'douyin', ['en-US'], () => long30).douyin,
        xiaohongshu: planFor(d, 'xiaohongshu', ['en-US'], () => long20).xiaohongshu,
      }
      const manPath = join(d, 'manifest.json')
      writeFileSync(manPath, JSON.stringify(man))
      expect(await check_plan.check(manPath, d)).toBe(1)
      expect(log.some((l) => l.includes('douyin [1] 标题 31 字 > 上限 30'))).toBe(true)
      expect(log.some((l) => l.includes('xiaohongshu [1] 标题 21 字 > 上限 20'))).toBe(true)
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('语种集合不一致 → 1，多/缺两侧都报；条数不齐则不发配对通过行', async () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      await makeAssets(d, ['en-US', 'ru-RU', 'ja-JP'])
      const man = {
        douyin: planFor(d, 'douyin', ['en-US', 'ru-RU'], (l) => `${l} 秋`).douyin,
        // 3 条（en 重复出现）：语种集合仍是 {en-US, ja-JP}，但条数 3 ≠ 2
        xiaohongshu: planFor(d, 'xiaohongshu', ['en-US', 'ja-JP', 'en-US'], (l) => `${l} 秋`).xiaohongshu,
      }
      const manPath = join(d, 'manifest.json')
      writeFileSync(manPath, JSON.stringify(man))
      expect(await check_plan.check(manPath, d)).toBe(1)
      const line = log.find((l) => l.includes('的语种集合不一致'))!
      expect(line).toContain("多 {'ja-JP'}")
      expect(line).toContain("缺 {'ru-RU'}")
      expect(log.some((l) => l.includes('✅ 横竖配对'))).toBe(false)
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('条数相等而集合不一致 → ✅ 配对行照发（Python 原版口径只看条数，镜像原样）', async () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      await makeAssets(d, ['en-US', 'ru-RU', 'ja-JP'])
      const man = {
        douyin: planFor(d, 'douyin', ['en-US', 'ru-RU'], (l) => `${l} 秋`).douyin,
        xiaohongshu: planFor(d, 'xiaohongshu', ['en-US', 'ja-JP'], (l) => `${l} 秋`).xiaohongshu,
      }
      const manPath = join(d, 'manifest.json')
      writeFileSync(manPath, JSON.stringify(man))
      expect(await check_plan.check(manPath, d)).toBe(1)
      expect(log.some((l) => l.includes('语种集合不一致'))).toBe(true)
      // 原版：配对通过行只判条数相等，集合不一致由 problems 拦——✅ 照发不算 bug
      expect(log.some((l) => l.includes('✅ 横竖配对'))).toBe(true)
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('封面比例离平台原生超 3% → ℹ️ 提醒（不判 FAIL，退出码仍 0）', async () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      await makeAssets(d, ['en-US'], 400, 300) // 4:3，投抖音要 3:4
      const man = planFor(d, 'douyin', ['en-US'], (l) => `${l} 秋`)
      const manPath = join(d, 'manifest.json')
      writeFileSync(manPath, JSON.stringify(man))
      expect(await check_plan.check(manPath, d)).toBe(0)
      const note = log.find((l) => l.includes('ℹ️') && l.includes('封面 400×300'))!
      expect(note).toContain('与平台原生 0.75 差 78%')
      expect(note).toContain('确认裁切框内文字是否在安全区')
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('封面读不出 → problems（素材在盘但不 是图）', async () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      writeFileSync(join(d, 'en-US.mp4'), 'x')
      writeFileSync(join(d, 'en-US.png'), 'not a png') // 在盘但解码必炸
      const man = planFor(d, 'douyin', ['en-US'], (l) => `${l} 秋`)
      const manPath = join(d, 'manifest.json')
      writeFileSync(manPath, JSON.stringify(man))
      expect(await check_plan.check(manPath, d)).toBe(1)
      expect(log.some((l) => l.includes('douyin 封面读不出'))).toBe(true)
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('相对素材路径：--root 与清单所在目录两级解析', async () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      await makeAssets(d, ['en-US'])
      // 清单里只写文件名，root=d 能找到
      const man = { douyin: [{ no: 1, lang: 'en-US', title: 'en-US 秋',
        video: 'en-US.mp4', cover: 'en-US.png' }] }
      const manPath = join(d, 'manifest.json')
      writeFileSync(manPath, JSON.stringify(man))
      expect(await check_plan.check(manPath, d)).toBe(0)
      expect(log.some((l) => l.includes('素材在盘：1/1'))).toBe(true)
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })
})

describe('check_plan.main：argparse 口径', () => {
  it('缺 manifest → 2；-h → 0；未知旗标 → 2；--root 带值合法', async () => {
    const { spy } = captureLog()
    const errSpy = vi.spyOn(process.stderr, 'write').mockImplementation(() => true)
    try {
      expect(await check_plan.main([])).toBe(2)
      expect(await check_plan.main(['-h'])).toBe(0)
      expect(await check_plan.main(['--nope', 'x.json'])).toBe(2)
      expect(await check_plan.main(['--root'])).toBe(2)
      expect(await check_plan.main(['x.json', 'extra.json'])).toBe(2)
    } finally {
      spy.mockRestore()
      errSpy.mockRestore()
    }
  })
})
