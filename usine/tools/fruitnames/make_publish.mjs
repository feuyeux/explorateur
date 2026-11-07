// make_publish.mjs — 「水果名称」系列：发布侧产物生成（facts.json + copy-*.md + manifest.json）
//
// 与 foodnames 版的差异：
// - 没有逐词「借自 X」tag → 词源来路统计不存在；结构量 = 集 / 4 果 / 12 语。
// - 数据直接读 examples/fruitnames/data/fruitlist.json（单事实源），不另发一期 JSON。
// - 旁白实测复用 tools/foodnames/measure_narration.mjs（video.json + tts 同布局）。
//
// 跑法（usine/ 下）：
//   node --import tsx tools/fruitnames/make_publish.mjs --episode 1 --out examples/fruitnames-ep01
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { manifest } from '../../packages/core/src/index.ts'

const buildManifest = manifest.buildManifest
const here = dirname(fileURLToPath(import.meta.url))
const USINE = resolve(here, '..', '..')

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}
const EPISODE = Number(arg('episode'))
const OUT = resolve(arg('out'))
const PUBLISH = join(OUT, 'publish')
if (!EPISODE) { console.error('usage: make_publish.mjs --episode <N> --out <dir>'); process.exit(1) }
if (!existsSync(PUBLISH)) { console.error(`✖ 发布词目录不存在：${PUBLISH}——先写 publish/*.md`); process.exit(1) }

process.chdir(OUT) // manifest 的素材相对路径按期目录解析

const list = JSON.parse(readFileSync(join(USINE, 'examples', 'fruitnames', 'data', 'fruitlist.json'), 'utf8'))
const ep = list.episodes.find((e) => e.episode === EPISODE)
if (!ep) { console.error(`✖ fruitlist.json 里没有第 ${EPISODE} 集`); process.exit(1) }
const SLUG = ep.slug

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

const nar = JSON.parse(execFileSync(process.execPath, [join(USINE, 'tools', 'foodnames', 'measure_narration.mjs'), OUT], {
  encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
}))

const videoCfg = JSON.parse(readFileSync(join(OUT, 'video.json'), 'utf8'))
const bedFile = videoCfg.bgm && videoCfg.bgm.file
if (!bedFile) { console.error('✖ video.json 里没有 bgm——这一期没床，发布前必须补'); process.exit(1) }
const bedSide = JSON.parse(readFileSync(join(OUT, `${bedFile}.json`), 'utf8'))

// ---------------------------------------------------------------- 事实表
// 规则同 foodnames：读者面出现的每个数字都要能在本表找到出处；表里的数
// 全部由数据/实测推导，不抄文案。
const facts = {
  episode: EPISODE,
  fruits_compared: 4,
  locales: 12,
  tts_voices: 12,
  videos: 2,
  duration_sec: lProbe.duration_s,
  duration_portrait_sec: pProbe.duration_s,
  frames: lProbe.frames,
  fps: lProbe.fps,
  width_landscape: lProbe.width,
  height_landscape: lProbe.height,
  width_portrait: pProbe.width,
  height_portrait: pProbe.height,
  sync_checks: 12 * 3,
  narration_rms_dbfs: nar.narration_rms_dbfs,
  bed_rms_dbfs: bedSide.measured.rms_dbfs,
  bed_duration_sec: bedSide.measured.duration_s,
  bgm_gain: videoCfg.bgm.gain,
}
writeFileSync(join(PUBLISH, 'facts.json'), JSON.stringify(facts, null, 1) + '\n', 'utf8')

// ---------------------------------------------------------------- 文案抽取（体例同 foodnames）
function section(md, h2) {
  const re = new RegExp(`^## ${h2.replace(/[（(].*?[)）]/g, '').trim()}[^\\n]*\\n([\\s\\S]*?)(?=\\n## |(?![\\s\\S]))`, 'm')
  const m = re.exec(md)
  return m ? m[1].replace(/^\n+/, '').replace(/\n+$/, '') : ''
}
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

function copyMd(title, body, topics) {
  // core parseCopy 的 SEC 头硬约定：`### <order> · <lang无空格> \`<locale>\``——
  // 水果系列一期一条，locale 位放集号（ep01…），别放带空格的标题。
  return [
    `### 01 · 水果系列 \`ep${String(EPISODE).padStart(2, '0')}\``,
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
    xiaohongshu: {
      copy: join(PUBLISH, 'copy-xiaohongshu.md'),
      video: () => `out/${SLUG}_portrait.mp4`,
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
      tags: () => biliTags,
    },
  },
  join(PUBLISH, 'manifest.json'),
)

console.log(`entries: ` + Object.entries(man).map(([k, v]) => `${k}=${v.length}`).join(' '))
console.log(`facts: 时长 ${facts.duration_sec}s / ${facts.frames} 帧 / ${facts.fps}fps · 旁白 ${facts.narration_rms_dbfs} dBFS · 床 ${facts.bed_rms_dbfs} dBFS · gain ${facts.bgm_gain}`)
if (problems.length > 0) {
  for (const p of problems) console.error(`PROBLEM ${p}`)
  process.exit(1)
}
console.log(`wrote ${join(PUBLISH, 'manifest.json')}`)
