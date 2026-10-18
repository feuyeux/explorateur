// check_publish_copy.test.ts — 发布词自检的反向验证 + 判据单测。
// verify_skill_scripts.py §1（publish-copy 指纹/溯源）的三行判据 verbatim 移植：
// 校准锚（归档验收稿零误伤）→ 指纹凿洞逐条命中 → 溯源对账三态 + 银行家舍入。
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterAll, afterEach, describe, expect, it, vi } from 'vitest'

import { FeuilleError } from '@feuille/core'

import * as cpc from '../src/check_publish_copy.js'

const ROOT = join(import.meta.dirname, '..', '..', '..')
const EXAMPLE = join(ROOT, 'skills', 'publish-copy', 'assets', 'example')

const dirs: string[] = []
afterAll(() => {
  for (const d of dirs) rmSync(d, { recursive: true, force: true })
})

function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), 'copy-'))
  dirs.push(d)
  return d
}

function captureLog(): { log: string[] } {
  const log: string[] = []
  vi.spyOn(console, 'log').mockImplementation((...a: unknown[]) => {
    log.push(a.map(String).join(' '))
  })
  return { log }
}

afterEach(() => {
  vi.restoreAllMocks()
})

/** 合成一份只够目标检查吃的小红书稿（目标检查只读读者面文字）。 */
function xhsFile(dir: string, body: string, title = '十二种语言说落叶'): string {
  const text = `## 标题（20 字内）\n${title}\n\n## 正文\n${body}\n\n`
    + '## 话题标签\n#落叶 #秋天 \n\n'
    + '## 发布贴士\n发布后自己置顶一条（"评论区报数：你最想说哪种语言的秋天"）\n'
  const p = join(dir, 'xiaohongshu.md')
  writeFileSync(p, text, 'utf8')
  return p
}

// ============ 校准锚：归档验收稿全部门零违规 ============

describe('好数据放行：归档验收稿《落叶》', () => {
  it('三平台全部机检门零违规（新门在已验收成果上不误伤）', () => {
    for (const [plat, spec] of Object.entries(cpc.PLATFORM)) {
      const p = join(EXAMPLE, spec.filename)
      for (const [label, fn] of cpc.CHECKS) {
        expect(fn(p, plat), `${plat}/${label}`).toEqual([])
      }
    }
  })

  it('checkPublishDir 全绿（README.md 是额外文件 → WARN 不 FAIL）', () => {
    const { log } = captureLog()
    expect(cpc.checkPublishDir(EXAMPLE)).toBe(0)
    const out = log.join('\n')
    expect(out).toContain('✅ 全部通过')
    expect(out).toContain('⏭️  数字溯源：SKIP（未给 --facts——没验，不是 PASS）')
    expect(out).toContain('⚠️  README.md') // 其它 .md → WARN 口子
    expect(out).not.toContain('❌')
    // Python 侧每平台 7 门 + 标题实测副信息都在
    expect(out).toContain('ℹ️  标题实测 14/20 字')
  })
})

// ============ AI 指纹凿洞（verify_skill_scripts §1 三行） ============

describe('AI 指纹门', () => {
  function fpHits(body: string): string[] {
    const d = tmp()
    return cpc.checkAiFingerprint(xhsFile(d, body), 'xiaohongshu')
  }

  it('凿洞：7 类签名逐条命中', () => {
    const holes: Array<[string, string]> = [
      ['这视频真的绝绝子。', '绝绝子'],
      ['看到最后我只想说 yyds。', 'yyds'],
      ['这是藏了心机的作品！！', '藏了心机'],
      ['！!连续感叹号刷屏！！', '连续感叹号'],
      ['原来雪花也有自己的名字。', '句首「原来…」'],
      ['这份心意像家一样的温暖。', '模板句'],
      ['🍂✨🪶👇 一行四个 emoji。', 'emoji'],
    ]
    for (const [body, w] of holes) {
      expect(fpHits(body).some((m) => m.includes(w)), body).toBe(true)
    }
  })

  it('反向的反向：句中「原来」不误伤（只判句首揭秘形态）', () => {
    expect(fpHits('我看见原来的颜色，还是那片林子。')).toEqual([])
  })

  it('指纹词在发布贴士里合法（贴士不在读者面扫描内）', () => {
    const d = tmp()
    const text = '## 标题（20 字内）\n好标题\n\n## 正文\n一支可以跟读的落叶。\n\n'
      + '## 话题标签\n#落叶 \n\n'
      + '## 发布贴士\n别用绝绝子，标题 20 字内——规则本身在贴士里合法\n'
    const p = join(d, 'xiaohongshu.md')
    writeFileSync(p, text, 'utf8')
    expect(cpc.checkAiFingerprint(p, 'xiaohongshu')).toEqual([])
  })

  it('emojiCount：emoji 平面 + 2600–27BF 杂项（✨ 在后者）；汉字不计', () => {
    expect(cpc.emojiCount('🍂✨🪶👇')).toBe(4)
    expect(cpc.emojiCount('落叶 🍂')).toBe(1)
    expect(cpc.emojiCount('落叶归根')).toBe(0)
  })
})

// ============ 数字溯源（verify_skill_scripts §1 溯源三行 + 银行家舍入） ============

describe('数字溯源门', () => {
  const facts = { duration_s: 52.4, languages: 12 }

  it('对上=过：52 对实测 52.4、12 对语种数（四舍五入是写作不是编造）', () => {
    const d = tmp()
    expect(cpc.checkFactProvenance(xhsFile(d, '52 秒看完十二种语言——不对，是 12 种语言。'), 'xiaohongshu', facts)).toEqual([])
  })

  it('凿洞：对不上 → 拦', () => {
    const d = tmp()
    const fails = cpc.checkFactProvenance(xhsFile(d, '61 秒看完。'), 'xiaohongshu', facts)
    expect(fails.length).toBe(1)
    expect(fails[0]).toContain("['61']")
    expect(fails[0]).toContain('编造规格是本 skill 最严重的失败模式')
  })

  it('中文数字不是数字载体，无数字化稿直通', () => {
    const d = tmp()
    expect(cpc.checkFactProvenance(xhsFile(d, '十二种语言说落叶，评论区报数。'), 'xiaohongshu', facts)).toEqual([])
  })

  it('字符串形式的事实值（边车里的 "0.1012"）也算出处', () => {
    const d = tmp()
    expect(cpc.checkFactProvenance(xhsFile(d, '增益 0.1012。'), 'xiaohongshu', { gain: '0.1012' })).toEqual([])
  })

  it('银行家舍入镜像：52.5 的 round() 是 52 不是 53', () => {
    const d = tmp()
    expect(cpc.checkFactProvenance(xhsFile(d, '52 秒看完。'), 'xiaohongshu', { duration_s: 52.5 })).toEqual([])
    expect(cpc.checkFactProvenance(xhsFile(d, '53 秒看完。'), 'xiaohongshu', { duration_s: 52.5 }).length).toBe(1)
  })

  it('话题标签先剥掉——#12 里的数字不是声称', () => {
    const d = tmp()
    expect(cpc.checkFactProvenance(xhsFile(d, '念完 #12 语种（标签里的数字不算声称）。'), 'xiaohongshu', {})).toEqual([])
  })

  it('factNumbers：数值与可 parse 字符串收进、布尔/文本/十六进制不收', () => {
    const nums = cpc.factNumbers({ a: 12, b: '52.4', c: '不是数字', d: true, e: '0x10', f: ' 7 ' })
    expect([...nums].sort((a, b) => a - b)).toEqual([7, 12, 52.4])
    expect(cpc.factNumbers(null)).toEqual(new Set())
  })
})

// ============ 判据单测（各 check 的正反例） ============

describe('段落切分与必需段落', () => {
  it('H2 切段：H1 不算段；段内容按行收', () => {
    const s = cpc.splitH2Sections('# 大标题\n\n## 甲\n第一行\n\n## 乙\nb1\nb2\n')
    expect(s).toEqual([['甲', ['第一行', '']], ['乙', ['b1', 'b2']]])
    expect(cpc.sectionText('乙', s)).toBe('b1\nb2')
    expect(cpc.sectionBodyLines('甲', s)).toEqual(['第一行'])
    expect(cpc.sectionText('没有', s)).toBeNull()
  })

  it('必需段落缺失按名报', () => {
    const d = tmp()
    const p = join(d, 'xiaohongshu.md')
    writeFileSync(p, '## 正文\n只有一段\n', 'utf8')
    const fails = cpc.checkRequiredSections(p, 'xiaohongshu')
    expect(fails).toContain('缺必需 H2 段落「标题（20 字内）」')
    expect(fails).toContain('缺必需 H2 段落「话题标签」')
    expect(fails).toContain('缺必需 H2 段落「发布贴士」')
  })
})

describe('标题字数（按码点，emoji 算 1 字）', () => {
  it('小红书超 20 字 → 报，含 Python repr 形态的标题回显', () => {
    const d = tmp()
    const p = join(d, 'xiaohongshu.md')
    writeFileSync(p, '## 标题（20 字内）\n这是一条特别特别特别长的标题呀真的非常非常长\n\n## 正文\n\n## 话题标签\n\n## 发布贴士\n', 'utf8')
    const fails = cpc.checkTitleLen(p, 'xiaohongshu')
    expect(fails.length).toBe(1)
    expect(fails[0]).toContain('标题 22 字 > 上限 20')
    expect(fails[0]).toContain("'这是一条特别特别特别长的标题呀真的非常非常长'")
  })

  it('emoji 按 1 字计：19 汉字 + 1 emoji = 20 码点（UTF-16 单元是 21）', () => {
    const d = tmp()
    const p = join(d, 'xiaohongshu.md')
    writeFileSync(p, '## 标题（20 字内）\n落叶归根落叶归根落叶归根落叶归根落叶归🍂\n\n## 正文\n\n## 话题标签\n\n## 发布贴士\n', 'utf8')
    expect(cpc.checkTitleLen(p, 'xiaohongshu')).toEqual([])
  })

  it('抖音取文案段第一行为标题；文案段空 → 专门报错', () => {
    const d = tmp()
    const p = join(d, 'douyin.md')
    writeFileSync(p, '## 文案\n这条标题不长也不短\n正文第二行\n\n## 话题\n#落叶 \n\n## 发布贴士\n', 'utf8')
    expect(cpc.checkTitleLen(p, 'douyin')).toEqual([])
    writeFileSync(p, '## 文案\n\n## 话题\n#落叶 \n\n## 发布贴士\n', 'utf8')
    expect(cpc.checkTitleLen(p, 'douyin')).toEqual(['「文案」段为空——抖音的标题与正文都在这一段'])
  })
})

describe('尾随空格 / 互动钩 / 置顶话术', () => {
  it('hash 风格末行缺尾随空格 → 报（publish-playbook 坑 ①）', () => {
    const d = tmp()
    const p = join(d, 'xiaohongshu.md')
    writeFileSync(p, '## 话题标签\n#落叶 #秋天\n', 'utf8')
    const fails = cpc.checkTrailingSpace(p, 'xiaohongshu')
    expect(fails.length).toBe(1)
    expect(fails[0]).toContain('publish-playbook 坑 ①：Slate 联想面板会吃掉末段话题')
    expect(fails[0]).toContain("'#落叶 #秋天'")
  })

  it('B 站 space 风格免检（空结尾不算违规）', () => {
    const d = tmp()
    const p = join(d, 'bilibili.md')
    writeFileSync(p, '## 标签\n落叶 多语言\n', 'utf8')
    expect(cpc.checkTrailingSpace(p, 'bilibili')).toEqual([])
  })

  it('互动钩：缺 → 报文带 Python list 形态的短语表', () => {
    const d = tmp()
    const p = join(d, 'xiaohongshu.md')
    writeFileSync(p, '## 正文\n没有钩子的正文\n', 'utf8')
    const fails = cpc.checkHookPhrase(p, 'xiaohongshu')
    expect(fails.length).toBe(1)
    expect(fails[0]).toContain("['报数', '点单', '跟读', '催更', '评论区', '弹幕', '敢不敢'] 至少一个）——评论区会冷场")
  })

  it('单字「敢」不算钩（敢不敢才算）', () => {
    const d = tmp()
    const p = join(d, 'xiaohongshu.md')
    writeFileSync(p, '## 正文\n你敢说出你的秋天吗\n', 'utf8')
    expect(cpc.checkHookPhrase(p, 'xiaohongshu')).toEqual(['「正文」缺互动钩短语（[\'报数\', \'点单\', \'跟读\', \'催更\', \'评论区\', \'弹幕\', \'敢不敢\'] 至少一个）——评论区会冷场'])
  })

  it('置顶话术：缺「置顶」/ 有「置顶」缺引号示例 / 齐全 → 三态', () => {
    const d = tmp()
    const p = join(d, 'xiaohongshu.md')
    writeFileSync(p, '## 发布贴士\n先发再说\n', 'utf8')
    expect(cpc.checkPinnedQuote(p, 'xiaohongshu')).toEqual(['「发布贴士」缺「置顶」——发布后自己置顶是拉新的硬动作'])
    writeFileSync(p, '## 发布贴士\n发布后自己置顶一条\n', 'utf8')
    expect(cpc.checkPinnedQuote(p, 'xiaohongshu')).toEqual([
      '「发布贴士」含「置顶」但缺引号示例（"…" 或 「…」）——话术必须落到具体字面，临时编的钩子弱',
    ])
    writeFileSync(p, '## 发布贴士\n发布后自己置顶（"我先来"）\n', 'utf8')
    expect(cpc.checkPinnedQuote(p, 'xiaohongshu')).toEqual([])
  })
})

describe('no-hard-wrap（上游 markdown-no-hard-wrap 的内联副本）', () => {
  it('段内硬换行 → 行号点名（1-based）', () => {
    const bad = cpc.noHardWrapViolations('一段话\n被硬切成两行\n')
    expect(bad).toEqual([1])
    expect(cpc.noHardWrapViolations('一行到头的段落\n\n第二段也只有一行\n')).toEqual([])
  })

  it('frontmatter 剥掉、代码栅栏内豁免、结构行（标题/列表/表格/引用）豁免', () => {
    const text = '---\ntitle: 元\ndescription: 多行\n---\n'
      + '# 标题行\n- 列表行\n| 表格 |\n> 引用\n'
      + '```\ncode\ninside\n```\n'
      + '正文一行\n'
    expect(cpc.noHardWrapViolations(text)).toEqual([])
    // frontmatter 没闭合 → 行表原样保留（Python StopIteration → pass）；
    // 保留的 '---' 不是结构行（`[-*+]\s` 要求数字/符号后带空白）——
    // 后跟文字行照样报，Python 实测 [1]，镜像之
    expect(cpc.noHardWrapViolations('---\n没闭合的 frontmatter\n')).toEqual([1])
  })
})

// ============ 顶层编排 + CLI ============

describe('checkPublishDir / main', () => {
  function goodDir(): string {
    const d = tmp()
    writeFileSync(join(d, 'xiaohongshu.md'),
      '## 标题（20 字内）\n好标题\n\n## 正文\n一支可以跟读的落叶，评论区告诉我。\n\n'
      + '## 话题标签\n#落叶 #秋天 \n\n## 发布贴士\n发布后自己置顶（"报数"）\n', 'utf8')
    writeFileSync(join(d, 'douyin.md'),
      '## 文案\n好标题\n\n一支可以跟读的落叶，评论区告诉我。\n\n## 话题\n#落叶 #秋天 \n\n## 发布贴士\n发布后自己置顶（"报数"）\n', 'utf8')
    writeFileSync(join(d, 'bilibili.md'),
      '## 标题\n好标题\n\n## 简介\n一支可以跟读的落叶，评论区告诉我。\n\n## 标签\n落叶 多语言\n\n## 发布贴士\n发布后自己置顶（"报数"）\n', 'utf8')
    return d
  }

  it('三平台齐且零违规 → 0；--facts 后数字溯源 PASS 也是 ✅（SKIP 不是 PASS）', () => {
    const d = goodDir()
    const { log } = captureLog()
    expect(cpc.checkPublishDir(d)).toBe(0)
    expect(log.join('\n')).toContain('⏭️  数字溯源：SKIP')
    const { log: log2 } = captureLog()
    expect(cpc.main([d, '--facts', writeFacts(d, { n: 1 })])).toBe(0)
    expect(log2.join('\n')).toContain('✅ 数字溯源（读者面数字全部对上事实表）')
  })

  it('一稿有 FAIL → rc 1，❌ 点名失败门', () => {
    const d = goodDir()
    writeFileSync(join(d, 'douyin.md'),
      '## 文案\n\n## 话题\n#落叶\n\n## 发布贴士\n发布后自己置顶（"报数"）\n', 'utf8')
    const { log } = captureLog()
    expect(cpc.checkPublishDir(d)).toBe(1)
    const out = log.join('\n')
    expect(out).toContain('❌ 标题字数：「文案」段为空——抖音的标题与正文都在这一段')
    expect(out).toContain('❌ 话题末尾尾随空格')
    expect(out).toContain('❌ 存在 FAIL，见上')
  })

  it('目录里没有任何已知平台文件 → rc 1', () => {
    const d = tmp()
    writeFileSync(join(d, 'note.md'), '# 随手记\n', 'utf8')
    const { log } = captureLog()
    expect(cpc.checkPublishDir(d)).toBe(1)
    expect(log.join('\n')).toContain('下没有任何已知平台文件')
  })

  it('main：缺位置参数 → usage + rc 2；未知旗标 → FeuilleError', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(cpc.main([])).toBe(2)
    expect(err.mock.calls[0]!.join(' ')).toContain('usage: feuille copy check')
    expect(() => cpc.main(['/tmp', '--nope'])).toThrow(FeuilleError)
  })

  function writeFacts(dir: string, obj: unknown): string {
    const p = join(dir, 'facts.json')
    writeFileSync(p, JSON.stringify(obj), 'utf8')
    return p
  }
})
