// themes.test.ts — match_theme 升包后的门禁（对应 skills/match_theme.py 的行为契约）：
// 匹配优先级（显式 > 语言强约束 > 关键词评分 > 兜底）、清单完整性与
// CLI 口径（--list / 话题匹配 / argparse 同款退出码）。
import { afterEach, describe, expect, it, vi } from 'vitest'

import { themes } from '../src/index.js'
import { main } from '../src/themes.js'

const { THEMES, describeThemes, matchTheme } = themes

describe('matchTheme：匹配优先级与评分', () => {
  it('显式指定合法主题 → 直接收下，不做评分', () => {
    expect(matchTheme('阿拉伯语', { explicit: 'dark-ink' })['theme']).toBe('dark-ink')
  })

  it('显式指定**不存在的**主题 → 忽略，落回评分', () => {
    expect(matchTheme('阿拉伯语', { explicit: 'no-such-theme' })['theme']).toBe('desert-sand')
  })

  it('语言强约束：ar/he/fa/ur 前缀一律沙漠主题（在评分之前）', () => {
    expect(matchTheme('论语', { lang: 'ar' })['theme']).toBe('desert-sand')
    expect(matchTheme('论语', { lang: 'ar-SA' })['theme']).toBe('desert-sand')
    expect(matchTheme('随便什么', { lang: 'he' })['theme']).toBe('desert-sand')
    expect(matchTheme('随便什么', { lang: 'fa' })['theme']).toBe('desert-sand')
    expect(matchTheme('随便什么', { lang: 'ur' })['theme']).toBe('desert-sand')
    // zh 不在强约束表里
    expect(matchTheme('随便什么', { lang: 'zh' })['theme']).not.toBe('desert-sand')
  })

  it('关键词评分：茶→botanical-tea、论语→warm-paper、哲学→dark-ink、语法→clean-paper', () => {
    expect(matchTheme('一杯茶的十二种语言', { lang: 'ja' })['theme']).toBe('botanical-tea')
    expect(matchTheme('论语八则讲解')['theme']).toBe('warm-paper')
    expect(matchTheme('康德哲学入门')['theme']).toBe('dark-ink')
    expect(matchTheme('英语语法精讲')['theme']).toBe('clean-paper')
  })

  it('话题与语种一并进评分（query = topic + " " + lang 全小写）', () => {
    // 话题本身不含关键词，语种名携带关键词
    expect(matchTheme('十二种语言', { lang: 'English' })['theme']).toBe('clean-paper')
  })

  it('同分时先列者胜（score > max_score 才换，严格大于才换人）', () => {
    // 「康德」只命中 dark-ink 一词——评分唯一高分者直接赢
    expect(matchTheme('康德')['theme']).toBe('dark-ink')
  })

  it('零命中的外语话题 → 退化到 clean-paper', () => {
    expect(matchTheme('bonjour tout le monde', { lang: 'fr' })['theme']).toBe('clean-paper')
  })

  it('零命中且中文话题 → warm-paper 基线；带「课/讲/学」字样 → clean-paper', () => {
    expect(matchTheme('随便聊聊')['theme']).toBe('warm-paper')
    expect(matchTheme('上课随记')['theme']).toBe('clean-paper')
    // lang 以 zh 开头 → 不走外语兜底，但「讲」字命中教学兜底
    expect(matchTheme('演讲', { lang: 'zh-CN' })['theme']).toBe('clean-paper')
  })

  it('空参默认 → warm-paper（中文古典基线）', () => {
    expect(matchTheme()['theme']).toBe('warm-paper')
  })
})

describe('describeThemes：清单完整性', () => {
  it('5 套主题齐全，键值自洽', () => {
    const all = describeThemes()
    expect(all.map((t) => t['theme'])).toEqual(
      ['warm-paper', 'clean-paper', 'dark-ink', 'desert-sand', 'botanical-tea'])
    for (const t of all) {
      expect(THEMES[t['theme']] === t).toBe(true)
      expect(t['accent_color']).toMatch(/^#[0-9a-f]{6}$/)
      expect(t['paper_color']).toMatch(/^#[0-9a-f]{6}$/)
      expect(t['name'].length).toBeGreaterThan(0)
    }
  })
})

describe('main：CLI 口径（argparse 同款）', () => {
  afterEach(() => vi.restoreAllMocks())

  it('--list / 无 topic → 列全部 5 套主题（标题行 + 每套 3 行 + 空行）', () => {
    for (const argv of [[], ['--list'], ['--list', '论讲课']]) {
      const log = vi.spyOn(console, 'log').mockImplementation(() => {})
      expect(main([...argv])).toBe(0)
      const lines = log.mock.calls.map((c) => c[0] as string)
      expect(lines[0]).toBe('【5 套教学视频垂域专属主题】')
      // 每套主题 3 次调用：bullet + 立意 + 标志色；标志色串带尾随 \n
      // （Python print 的 `\n` 结尾 → 视觉空行分隔，这里按调用串形态断言）
      expect(lines.length).toBe(1 + 5 * 3)
      expect(lines[1]).toContain('- warm-paper')
      expect(lines[1]).toContain('古卷暖纸 (Warm Paper)')
      expect(lines[1]).toContain('适用: 人文国学')
      expect(lines[2]).toContain('设计立意:')
      expect(lines[3]).toBe('  标志色: 纸色 #f7f2e6 · 焦点色 #b8860b\n')
      expect(lines[4]).toContain('- clean-paper')
      vi.restoreAllMocks()
    }
  })

  it('话题匹配输出四行（输入/匹配/垂域/立意）', () => {
    const log = vi.spyOn(console, 'log').mockImplementation(() => {})
    expect(main(['一杯茶的十二种语言', '--lang', 'ja'])).toBe(0)
    const lines = log.mock.calls.map((c) => c[0] as string)
    expect(lines).toEqual([
      `输入话题: '一杯茶的十二种语言' (语言: 'ja')`,
      '-> 匹配主题: [botanical-tea] 青竹茗香 (Botanical Tea)',
      '   适用垂域: 茶道雅趣 · 节气博物 · 东方美学 · 自然生活',
      `   立意依据: ${THEMES['botanical-tea']!['rationale']}`,
    ])
  })

  it('-h → usage 到 stdout + 0；未知旗标/--lang 缺值/第二位置参数 → usage 到 stderr + 2', () => {
    const log = vi.spyOn(console, 'log').mockImplementation(() => {})
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(main(['-h'])).toBe(0)
    expect(log).toHaveBeenCalled()
    for (const bad of [['--nope'], ['--lang'], ['论语', '孟子'], ['--lang=ar', 'x', 'y']]) {
      expect(main([...bad])).toBe(2)
    }
    expect(err).toHaveBeenCalledTimes(4)
    expect(main(['--lang=ar', 'x'])).toBe(0) // --lang= 带值形态合法
  })

  it('--list 覆盖话题（argparse 布尔旗标优先于位置参数判空）', () => {
    const log = vi.spyOn(console, 'log').mockImplementation(() => {})
    expect(main(['论语', '--list'])).toBe(0)
    expect(log.mock.calls[0]![0]).toBe('【5 套教学视频垂域专属主题】')
  })
})
