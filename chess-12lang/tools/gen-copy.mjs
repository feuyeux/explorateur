// tools/gen-copy.mjs —— 生成每支的三平台发布词 + 事实表（facts.json）
//
// 用法：node tools/gen-copy.mjs
// 体例：publish/xiaohongshu.md / douyin.md / bilibili.md（文件名是 publishing 端的硬约定）
// 纪律：读者面文字只写思想与发现，不写工艺（逐词高亮/双色/分辨率/时长一律不进文案）；
//       事实表只抄实测数（ffprobe 时长、画幅尺寸、语种数），数字溯源门靠它。
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const DATA = JSON.parse(readFileSync(join(ROOT, 'data', 'series.json'), 'utf8'))
const COPY = JSON.parse(readFileSync(join(ROOT, 'data', 'copy.json'), 'utf8'))

const TAGS_XHS = ['#国际象棋', '#多语言', '#冷知识', '#棋类', '#语言学习']
const TAGS_DY = ['#国际象棋', '#冷知识', '#多语言', '#棋类']
const TAGS_BILI = ['国际象棋', '多语言', '冷知识', '涨知识', '棋类']

function ffprobeDuration(mp4) {
  if (!existsSync(mp4)) return null
  const r = spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', mp4],
    { encoding: 'utf8' })
  const v = Number((r.stdout || '').trim())
  return Number.isFinite(v) ? v : null
}

// 手写源的必填字段：缺一个就当场炸。
// （为什么必须炸：`alt` 缺了会拼出字面量 "undefined" 写进成稿，而机检的
//  读者面只扫「标题+正文」，扫不到「备选文案」段——这道缺口只能靠生成器自己堵。）
const REQUIRED = [
  ['xhs', 'title'], ['xhs', 'body'],
  ['douyin', 'title'], ['douyin', 'body'], ['douyin', 'alt'],
  ['bili', 'title'], ['bili', 'desc'],
]

/** 成稿里不允许出现的占位/异常值。 */
const BAD_LITERAL = /(^|[\s"'（(【\[、，,：:])undefined($|[\s"'）)】\]、，,。.!！?？\n])/m

for (const ep of DATA.episodes) {
  const c = COPY.episodes[ep.id]
  if (!c) throw new Error(`缺文案：${ep.id}`)
  for (const [plat, field] of REQUIRED) {
    const v = c[plat]?.[field]
    if (typeof v !== 'string' || v.trim() === '') {
      throw new Error(`${ep.id} 的 ${plat}.${field} 缺失或为空——`
        + '发布词是手写源，缺字段必须当场炸，不能让占位值流进成稿')
    }
  }
  const dir = join(ROOT, 'episodes', ep.id)
  const pub = join(dir, 'publish')
  mkdirSync(pub, { recursive: true })
  const pinned = COPY.pinned[ep.id] ?? '我先来：你那边的棋子叫什么？'
  const durP = ffprobeDuration(join(dir, 'out', `${ep.id}_portrait.mp4`))
  const durL = ffprobeDuration(join(dir, 'out', `${ep.id}_landscape.mp4`))

  // 小红书：标题 ≤20 字，末个话题带尾随空格
  const xhs = `# 小红书发布词（竖屏 ${ep.id}_portrait.mp4）

## 标题（20 字内）

${c.xhs.title}

## 正文

${c.xhs.body}

## 话题标签

${TAGS_XHS.join(' ')} 

## 发布贴士

- 封面用视频首帧（全屏「${ep.title_zh}」版式），另备 3:4 版给信息流首图；
- 发布后自己置顶一条引路评论（话术："${pinned}"），把报数率拉起来；
- 话题末标留一个空格，别让编辑器的联想面板吃掉最后一个话题。
`

  // 抖音：标题 = 文案段第一行，与正文之间空一行；末个话题带尾随空格
  const dy = `# 抖音发布词（竖屏 ${ep.id}_portrait.mp4）

## 文案

${c.douyin.title}

${c.douyin.body}

## 备选文案（投流版）

${c.douyin.alt}

## 话题

${TAGS_DY.join(' ')} 

## 发布贴士

- 竖屏全屏发布，首帧即封面；
- 发布后置顶评论引路（话术："${pinned}"），把互动带起来。
`

  // B站：标题 ≤80 字，标签空格分隔不带 #
  const bili = `# B站发布词（横屏 ${ep.id}_landscape.mp4）

## 标题

${c.bili.title}

## 简介

${c.bili.desc}

## 标签

${TAGS_BILI.join(' ')}

## 发布贴士

- 横屏发布，封面用视频首帧；
- 分区建议：知识区 · 语言，发布后置顶一条引路评论（话术："${pinned}"）。
`

  writeFileSync(join(pub, 'xiaohongshu.md'), xhs, 'utf8')
  writeFileSync(join(pub, 'douyin.md'), dy, 'utf8')
  writeFileSync(join(pub, 'bilibili.md'), bili, 'utf8')

  // 成稿自检：占位值（undefined / null / NaN）一律不许进成稿
  for (const [name, text] of [['xiaohongshu', xhs], ['douyin', dy], ['bilibili', bili]]) {
    if (BAD_LITERAL.test(text)) {
      throw new Error(`${ep.id}/${name}.md 里出现占位值（undefined/null/NaN）——`
        + '多半是 data/copy.json 缺字段')
    }
  }

  const facts = {
    episode: ep.no,
    languages: DATA.locales.length,
    pieces: DATA.episodes.length,
    portraitWidth: 1080,
    portraitHeight: 1920,
    landscapeWidth: 1920,
    landscapeHeight: 1080,
    portraitDurationSeconds: durP,
    landscapeDurationSeconds: durL,
    coverWidth: 1080,
    coverHeight: 1440,
  }
  writeFileSync(join(pub, 'facts.json'), JSON.stringify(facts, null, 1), 'utf8')
  console.log(`${ep.id}  ${ep.title_zh}  标题 ${[...c.xhs.title].length}/${[...c.douyin.title].length}/${[...c.bili.title].length} 字  时长 ${durP ?? '-'}`)
}
