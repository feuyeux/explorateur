// make_publish.mjs — 「各国美食名称」系列：**发布侧产物生成**（facts.json + manifest.json）
//
// 一次调用把一期的发布侧三件套算出来：
//   publish/facts.json        事实表（读者面数字的出处；数字全部由数据/实测推导，不抄文案）
//   publish/copy-*.md         core 体例的文案块（只抽取 publish/*.md，不改写一个字）
//   publish/manifest.json     三平台发布清单（素材在盘才算齐）
//
// 跑法（仓库根目录）：
//   node --import tsx tools/foodnames/make_publish.mjs \
//     --data tools/foodnames/data/ep02-coffee.json \
//     --out  examples/foodnames-ep02-coffee
//
// ⚠️ 数据文件须带 `origin_locale`（词源语的 locale）——manifest 的 locale 字段
//    记的是「这个词从哪来」，不是视频的配音语种。缺了就当场报错，不猜。
// ⚠️ 本文件是 .mjs（纯 JS 语义，tsx 不做转译）：里面不能出现 TS 专有语法
//    （类型注解、`!` 非空断言）。core 的入口是 src/index.ts，靠 tsx 转译那个 .ts。
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { manifest } from '../../packages/core/src/index.ts'

const buildManifest = manifest.buildManifest

const here = dirname(fileURLToPath(import.meta.url))

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}
const DATA = resolve(arg('data'))
const OUT = resolve(arg('out'))
const PUBLISH = join(OUT, 'publish')

if (!existsSync(DATA)) { console.error(`✖ 数据文件不存在：${DATA}`); process.exit(1) }
if (!existsSync(PUBLISH)) { console.error(`✖ 发布词目录不存在：${PUBLISH}`); process.exit(1) }

const data = JSON.parse(readFileSync(DATA, 'utf8'))
const SLUG = data.slug
const EP = data.episode

// 清单里的素材路径是相对期目录的（out/…、cover_t34.png），存在性校验按 cwd
// 解析 —— 必须切到期目录，否则 buildManifest 会把「相对路径」当相对进程 cwd
// 去找，报出一堆「素材缺失」的假问题。
process.chdir(OUT)

// ---------------------------------------------------------------- 词源语
// manifest 的 locale = 「这个词从哪来」（词源语）；不是配音语种。
// 优先取数据里显式给的 origin_locale；没给就按「唯一一格不是借来的」推导
// （tag 不以「借自」开头 = 那一格是本族词）。两处都定不下来 → 当场报错，不猜。
function resolveOrigin() {
  if (data.origin_locale) return data.origin_locale
  const native = data.words.filter((w) => !/^借自/.test(w.tag || ''))
  if (native.length === 1) return native[0].locale
  console.error(
    '✖ 定不出词源语（origin_locale）：'
    + `数据没给 origin_locale，且「非借词」格有 ${native.length} 个`
    + `（${native.map((w) => w.locale).join(', ') || '一个都没有'}）`,
  )
  process.exit(1)
}
const origin = resolveOrigin()

// ---------------------------------------------------------------- 实测量
function probe(file) {
  const out = execFileSync('ffprobe', [
    '-v', 'error', '-show_entries', 'stream=width,height,r_frame_rate,nb_frames',
    '-show_entries', 'format=duration', '-of', 'json', file,
  ], { encoding: 'utf8' })
  const j = JSON.parse(out)
  const st = (j.streams || [])[0] || {}
  const [num, den] = String(st.r_frame_rate || '0/1').split('/')
  return {
    width: st.width, height: st.height,
    fps: den && Number(den) ? Number(num) / Number(den) : Number(num),
    frames: st.nb_frames ? Number(st.nb_frames) : null,
    duration_s: j.format && j.format.duration ? +Number(j.format.duration).toFixed(2) : null,
  }
}

const landscape = join(OUT, 'out', `${SLUG}_landscape.mp4`)
const portrait = join(OUT, 'out', `${SLUG}_portrait.mp4`)
for (const v of [landscape, portrait]) {
  if (!existsSync(v)) { console.error(`✖ 成片不存在：${v}——先跑完产线再出清单`); process.exit(1) }
}
const lProbe = probe(landscape)
const pProbe = probe(portrait)

// 旁白实测（与 run_episode 同一口径：真实语音窗的功率加权 RMS）
const nar = JSON.parse(execFileSync(process.execPath, [join(here, 'measure_narration.mjs'), OUT], {
  encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
}))

// 床（bgm）边车：电平与时长的事实源
const videoCfg = JSON.parse(readFileSync(join(OUT, 'video.json'), 'utf8'))
const bedFile = videoCfg.bgm && videoCfg.bgm.file
if (!bedFile) { console.error('✖ video.json 里没有 bgm——这一期没床，发布前必须补'); process.exit(1) }
const bedSide = JSON.parse(readFileSync(join(OUT, `${bedFile}.json`), 'utf8'))
const bedRms = bedSide.measured.rms_dbfs
const bedDur = bedSide.measured.duration_s

// ---------------------------------------------------------------- 事实表
// 规则：读者面出现的每个数字都要能在本表里找到出处。表里的数**全部由
// 数据/实测推导**——不把文案里的数字抄进来（抄进来等于自我批准，纪律 12）。
const words = data.words
const LOCALE_COUNT = words.length

/** 各「借自 X」来源语言的格数（来源是 tag 的直接借词方向，不是终极源头）。 */
function sourceCounts() {
  const m = new Map()
  for (const w of words) {
    const mt = /借自(.+?)(?:\s*·.*)?$/.exec(w.tag || '')
    if (!mt) continue
    const src = mt[1].trim()
    m.set(src, (m.get(src) || 0) + 1)
  }
  return m
}
const srcCounts = sourceCounts()
const distinctSources = srcCounts.size
/** 终极词源（非借词）那一格有几格 —— 1 = 只有一种语言是「原话」。 */
const nativeCells = words.filter((w) => !/^借自/.test(w.tag || '')).length

const facts = {
  // ---- 结构量（可数）----
  locales: LOCALE_COUNT,
  words_compared: LOCALE_COUNT,
  tts_voices: LOCALE_COUNT,
  episode: EP,
  /** 来路总数 = 借词方向数 + 词源本身（1）。文案说「7 条来路」指的就是这个。 */
  distinct_loan_paths: distinctSources + nativeCells,
  /** 其中「借来的」方向有几种（= distinct_loan_paths − 1）。 */
  distinct_borrow_sources: distinctSources,
  native_words: nativeCells,
  borrowed_words: LOCALE_COUNT - nativeCells,
  // 各来源语言的格数（「12 个里 3 个借自英语」这类表述的出处）
  ...Object.fromEntries([...srcCounts.entries()].map(([k, v]) => [`borrowed_from_${k}`, v])),
  // 各语种在 12 格里的位次（「第 8 个是印地语」这类表述的出处）
  ...Object.fromEntries(words.map((w, i) => [`position_${w.locale}`, i + 1])),
  // ---- 实测量（可核对）----
  duration_sec: lProbe.duration_s,
  frames: lProbe.frames,
  fps: lProbe.fps,
  width_landscape: lProbe.width,
  height_landscape: lProbe.height,
  width_portrait: pProbe.width,
  height_portrait: pProbe.height,
  sync_checks: LOCALE_COUNT * 3, // 每语种 pre/word0/done 三探
  narration_rms_dbfs: nar.narration_rms_dbfs,
  narration_loudest_dbfs: nar.loudest.rms_dbfs,
  narration_quietest_dbfs: nar.quietest.rms_dbfs,
  bed_rms_dbfs: bedRms,
  bed_duration_sec: bedDur,
  bgm_gain: videoCfg.bgm.gain,
}

// 内容型事实（年份、条目数这类「不是量出来的、但是可核对的数」）由数据文件
// 带进来——脚本不写死任何具体年份，避免每期改脚本。
if (data.extra_facts && typeof data.extra_facts === 'object') {
  for (const [k, v] of Object.entries(data.extra_facts)) {
    if (typeof v === 'number' || typeof v === 'string') facts[k] = v
  }
}
writeFileSync(join(PUBLISH, 'facts.json'), JSON.stringify(facts, null, 1) + '\n', 'utf8')

// ---------------------------------------------------------------- 文案抽取
/** 取 `## 标题` 之后的正文（到下一个 H2）。
 *
 * ⚠️ 结束位置不能用 `$`：正则带 `m` 修饰符时 `$` 匹配**行尾**，
 * 紧跟在标题行后面的空行就满足「到下一个 H2 或到文末」→ 正文抽成空串。
 * 用 `(?![\\s\\S])`（输入结束）才是真的「文末」。
 *
 * ⚠️ 只裁首尾**换行**，不裁空格：抖音/小红书的末行话题后面那个尾随空格
 * 是 publish-playbook 坑 ①的保险（Slate 在 blur 时把未闭合的 #tag 当话题
 * 候选弹联想面板并改写内容）。`.trim()` 会把它吃掉——机检读的是 .md 原稿
 * （空格还在），发布端贴的是清单里的 body（空格没了）→ 门禁绿、线上出事。 */
function section(md, h2) {
  const re = new RegExp(`^## ${h2.replace(/[（(].*?[)）]/g, '').trim()}[^\\n]*\\n([\\s\\S]*?)(?=\\n## |(?![\\s\\S]))`, 'm')
  const m = re.exec(md)
  return m ? m[1].replace(/^\n+/, '').replace(/\n+$/, '') : ''
}

/** 段内去掉标题行（小红书/B 站：标题是独立 H2；抖音：标题是「文案」段第一行）。 */
function bodyOf(md, h2, dropFirstLine) {
  const raw = section(md, h2)
  const lines = raw.split('\n').map((l) => l.trim()).filter((l) => l !== '')
  return dropFirstLine ? lines.slice(1).join('\n') : lines.join('\n')
}

const xhsMd = readFileSync(join(PUBLISH, 'xiaohongshu.md'), 'utf8')
const dyMd = readFileSync(join(PUBLISH, 'douyin.md'), 'utf8')
const biliMd = readFileSync(join(PUBLISH, 'bilibili.md'), 'utf8')

const xhsTitle = section(xhsMd, '标题（20 字内）').split('\n')[0].trim()
const xhsBody = [bodyOf(xhsMd, '正文', false), section(xhsMd, '话题标签')].filter(Boolean).join('\n')
const xhsTopics = section(xhsMd, '话题标签').trim()

const dyTitle = section(dyMd, '文案').split('\n')[0].trim()
const dyBody = [bodyOf(dyMd, '文案', true), section(dyMd, '话题')].filter(Boolean).join('\n')
const dyTopics = section(dyMd, '话题').trim()

const biliTitle = section(biliMd, '标题').split('\n')[0].trim()
const biliBody = bodyOf(biliMd, '简介', false)
const biliTags = section(biliMd, '标签').trim().split(/\s+/).filter(Boolean)

/** core 体例：一条 = 一个 `###` 段 + 三个围栏块。 */
function copyMd(title, body, topics) {
  return [
    `### 01 · ${data.title_zh} \`${origin}\``,
    '',
    '**标题**',
    '```',
    title,
    '```',
    '',
    '**正文**',
    '```',
    body,
    '```',
    '',
    '**话题**',
    '```',
    topics,
    '```',
    '',
  ].join('\n')
}

writeFileSync(join(PUBLISH, 'copy-xiaohongshu.md'), copyMd(xhsTitle, xhsBody, xhsTopics), 'utf8')
writeFileSync(join(PUBLISH, 'copy-douyin.md'), copyMd(dyTitle, dyBody, dyTopics), 'utf8')
writeFileSync(join(PUBLISH, 'copy-bilibili.md'), copyMd(biliTitle, biliBody, biliTags.join(' ')), 'utf8')

// ---------------------------------------------------------------- 清单
const [man, problems] = buildManifest(
  {
    // 竖版吃小红书 + 抖音（3:4 信息流封面），横版吃 B 站（16:9）。
    xiaohongshu: {
      copy: join(PUBLISH, 'copy-xiaohongshu.md'),
      video: () => `out/${SLUG}_portrait.mp4`,
      // 竖版平台的信息流封面是 3:4 原生比例；9:16 版会被居中裁掉上下各 12.5%
      //（标题在顶部 → 被切）。视频本体仍是 9:16 全屏。
      cover: () => 'cover_t34.png',
    },
    douyin: {
      copy: join(PUBLISH, 'copy-douyin.md'),
      video: () => `out/${SLUG}_portrait.mp4`,
      cover: () => 'cover_t34.png',
    },
    bilibili: {
      copy: join(PUBLISH, 'copy-bilibili.md'),
      video: () => `out/${SLUG}_landscape.mp4`,
      cover: () => 'cover_lc.png',
      // B 站 tag 区是 language tag 风格（空格分隔、无 #），core 的 parseCopy
      // 只认 # 形式 → 话题得显式给，否则清单报「话题为空」。
      tags: () => biliTags,
    },
  },
  join(PUBLISH, 'manifest.json'),
)

console.log(
  `entries: ` + Object.entries(man).map(([k, v]) => `${k}=${v.length}`).join(' '),
)
console.log(
  `facts: 时长 ${facts.duration_sec}s / ${facts.frames} 帧 / ${facts.fps}fps `
  + `· 旁白 ${facts.narration_rms_dbfs} dBFS · 床 ${facts.bed_rms_dbfs} dBFS / ${facts.bed_duration_sec}s `
  + `· gain ${facts.bgm_gain} · 来路 ${facts.distinct_loan_paths} 条`,
)
if (problems.length > 0) {
  for (const p of problems) console.error(`PROBLEM ${p}`)
  process.exit(1)
}
console.log(`wrote ${join(PUBLISH, 'manifest.json')}`)
