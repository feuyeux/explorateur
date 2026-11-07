// run_episode.mjs — 「水果名称」系列：一期从数据跑到成片
//
// 生成源文件 → 字体子集 → 韩语补丁实测注入（融合音节自动检出）→ 海报
// → 三版封面 → 门禁（字符 / 版式自检 / 逐格颜色 / 叠印对齐）→ 配音 →
// 旁白实测 → 双画幅成片 → 同步/白帧验收。任一步红就非零退出。
//
// ⚠️ BGM 床：当前无床成片（examples/_beds 不存在）；--bgm/--bgm-json 与
// foodnames 同参，给了就按「旁白实测 − 16dB − 床实测」反推 gain。
//
// 跑法：node --import tsx tools/fruitnames/run_episode.mjs --episode 1 --out examples/fruitnames-ep01
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { platform } from '../../packages/core/src/index.ts'

const here = dirname(fileURLToPath(import.meta.url))
const USINE = resolve(here, '..', '..')

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}
const EPISODE = Number(arg('episode'))
const OUT = resolve(arg('out'))
const BGM = arg('bgm') ? resolve(arg('bgm')) : null
const BGM_JSON = arg('bgm-json') ? resolve(arg('bgm-json')) : null
const SKIP_BUILD = process.argv.includes('--skip-build')
const TARGET_UNDER_DB = Number(arg('target-under-db', '16'))
if (!EPISODE) { console.error('usage: run_episode.mjs --episode <N> --out <dir>'); process.exit(2) }

mkdirSync(OUT, { recursive: true })

let stepNo = 0
function run(cmd, args, { capture = false, cwd = USINE, quiet = false, allowFail = false } = {}) {
  stepNo += 1
  const label = `${String(stepNo).padStart(2, '0')} ${cmd} ${args.slice(0, 3).join(' ')}`
  if (!quiet) console.log(`\n▶ ${label}`)
  const r = spawnSync(cmd, args, { cwd, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  if (r.error || (r.status !== 0 && !allowFail)) {
    console.error(`✖ ${label}`)
    const err = (r.stderr || '').trim()
    const outp = (r.stdout || '').trim()
    if (err) console.error(err.slice(-3000))
    else if (outp) console.error(outp.slice(-3000))
    process.exit(1)
  }
  if (capture) return (r.stdout || '') + (r.stderr || '')
  return ''
}
function feuille(args, opts = {}) {
  return run('node', ['--import', 'tsx', join(USINE, 'packages', 'cli', 'src', 'main.ts'), ...args], opts)
}

// ---------------------------------------------------------------- 1 生成源文件（两遍：韩语融合音节要等实测）
const buildArgs = () => ['--import', 'tsx', join(here, 'build_episode.mjs'), '--episode', String(EPISODE), '--out', OUT]
run('node', [...buildArgs()])

// ---------------------------------------------------------------- 2 字体子集
// fetch-fonts 走 Google Fonts（网络步）：瞬时抖动会放倒整批（2026-11-07
// 实测一次网络抖动 9 集全挂在第 02 步）——重试 3 次，间隔 20s。
{
  let ok = false
  for (let a = 1; a <= 3 && !ok; a++) {
    const r = spawnSync('node', ['--import', 'tsx', join(USINE, 'packages', 'cli', 'src', 'main.ts'), 'poster', 'fetch-fonts', join(OUT, 'fonts.json')], { cwd: USINE, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
    ok = r.status === 0
    if (!ok) {
      console.error(((r.stderr || '') + (r.stdout || '')).slice(-400))
      if (a < 3) { console.log(`  fetch-fonts 第 ${a} 次失败，20s 后重试`); await new Promise((res) => setTimeout(res, 20_000)) }
    }
  }
  if (!ok) { console.error('✖ fetch-fonts 3 次都失败（网络？）'); process.exit(1) }
}

// ---------------------------------------------------------------- 3 韩语补丁（实测全部音节 → 检出融合 → 重建 → 复测注入）
const epData = JSON.parse(readFileSync(join(OUT, 'episode.json'), 'utf8'))
const koWord = (JSON.parse(readFileSync(join(OUT, 'voices.json'), 'utf8')).langs.find((l) => l.locale === 'ko-KR') ?? {})
const koSyllablesAll = [...new Set([...koWord.tokens.join('')])]
const chrome = platform.browserPath()
if (!chrome) { console.error('✖ 找不到 Chromium 系浏览器（设 CHROME_BIN）'); process.exit(1) }

function measureKorean(syllables) {
  const out = spawnSync('node', ['--import', 'tsx', join(USINE, 'packages', 'cli', 'src', 'main.ts'),
    'poster', 'measure-korean', ...syllables, '--family', 'Food KR', '--css', join(OUT, 'fonts.css'), '--out', join(OUT, 'k_measure')],
  { cwd: USINE, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  const text = (out.stdout || '') + (out.stderr || '')
  const blocks = [...text.matchAll(/\.k[0-9A-Fa-f]{4,6} \{[^}]*\}/g)].map((m) => m[0])
  return { blocks, text, status: out.status }
}

let fused = new Set()
let measured = measureKorean(koSyllablesAll)
if (measured.blocks.length !== koSyllablesAll.length) {
  const got = new Set(measured.blocks.map((b) => {
    const m = b.match(/\.k([0-9A-Fa-f]{4,6})/)
    return String.fromCodePoint(parseInt(m[1], 16))
  }))
  fused = new Set(koSyllablesAll.filter((s) => !got.has(s)))
  console.log(`  韩语融合音节（实测 measure-korean 出不了补丁，走 .cv 渐变）：${[...fused].join('/') || '无'}`)
  // 重建（fused 集合进了 HTML）→ 重取字体 → 复测非融合音节
  run('node', [...buildArgs(), '--fused', [...fused].join(',')])
  feuille(['poster', 'fetch-fonts', join(OUT, 'fonts.json')])
  const rest = koSyllablesAll.filter((s) => !fused.has(s))
  measured = rest.length ? measureKorean(rest) : { blocks: [] }
  if (rest.length && measured.blocks.length !== rest.length) {
    console.error(`✖ 复测后补丁块数 ${measured.blocks.length} ≠ 非融合音节数 ${rest.length}`)
    process.exit(1)
  }
}
{
  const blocks = measured.blocks
  const css = blocks.join('\n')
  for (const f of ['poster_src.html', 'video_src.html']) {
    const p = join(OUT, f)
    writeFileSync(p, readFileSync(p, 'utf8').replace('/*__KO_CSS__*/', css), 'utf8')
  }
  mkdirSync(join(OUT, 'k_measure'), { recursive: true })
  writeFileSync(join(OUT, 'k_measure', 'ko.css'), css, 'utf8')
  console.log(`  韩语补丁：${blocks.length} 块注入${fused.size ? `（融合 ${fused.size} 个走 .cv）` : ''}`)
}

// ---------------------------------------------------------------- 4 海报 + 三版封面
// 封面是 build_episode 自包含生成的（cover_src.html，?fmt=P/T 切换变体）——
// 不走 make-covers：它的变体注入靠文本锚，与水果版追加 CSS 打架（ep01 实测
// 规则进文件不进样式表）。
feuille(['poster', 'assemble', join(OUT, 'poster_src.html'), join(OUT, 'index.html')])
feuille(['poster', 'render', join(OUT, 'index.html'), join(OUT, 'poster.png'), '1240', '1754', '2'])
feuille(['poster', 'assemble', join(OUT, 'cover_src.html'), join(OUT, 'cover.html')])
feuille(['poster', 'render', join(OUT, 'cover.html'), join(OUT, 'cover_lc.png'), '1920', '1080', '1'])
feuille(['poster', 'render', `${join(OUT, 'cover.html')}?fmt=P`, join(OUT, 'cover_pt.png'), '1080', '1920', '1'])
feuille(['poster', 'render', `${join(OUT, 'cover.html')}?fmt=T`, join(OUT, 'cover_t34.png'), '1080', '1440', '1'])

// ---------------------------------------------------------------- 5 门禁：字符 + 版式自检
feuille(['poster', 'audit-charset', join(OUT, 'poster_src.html'), join(OUT, 'fonts.json')])
feuille(['poster', 'audit-charset', join(OUT, 'video_src.html'), join(OUT, 'fonts.json')])

{
  const dumpUrl = 'file:///' + join(OUT, 'index.html').replace(/\\/g, '/') + '?verify=1'
  const dump = spawnSync(chrome, [
    '--headless=new', '--disable-gpu', '--no-sandbox', '--virtual-time-budget=15000',
    '--window-size=1240,1754', '--force-device-scale-factor=1', '--hide-scrollbars', '--dump-dom', dumpUrl,
  ], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  writeFileSync(join(OUT, 'diag.txt'), dump.stdout ?? '', 'utf8')
  const dm = /<title>DIAG (\{.*?\})<\/title>/s.exec(dump.stdout ?? '')
  if (!dm) { console.error('✖ diag 里没有 DIAG 诊断'); process.exit(1) }
  const cells = JSON.parse(dm[1]).cells
  const badX = cells.filter((c) => c.overflowX)
  const badY = cells.filter((c) => c.overflowY)
  if (badX.length) { console.error(`✖ 词行横向溢出：${badX.map((c) => c.lang).join(',')}`); process.exit(1) }
  if (badY.length) { console.error(`✖ 词区纵向溢出（4 行总高超格）：${badY.map((c) => c.lang).join(',')}`); process.exit(1) }
  const rowRects = {}
  for (const c of cells) rowRects[c.lang] = c.rows
  writeFileSync(join(OUT, 'rows.json'), JSON.stringify(rowRects, null, 1), 'utf8')
  console.log(`  版式自检：${cells.length} 格 × 4 行全部在格内`)
}

const vcOut = feuille(
  ['poster', 'verify-colors', join(OUT, 'poster.png'), '--cols', '3', '--rows', '4', '--langs', WORDS_LABELS()],
  { capture: true },
)
console.log(vcOut.split('\n').filter((l) => l.includes('lines:')).join('\n'))

function WORDS_LABELS() {
  const v = JSON.parse(readFileSync(join(OUT, 'voices.json'), 'utf8'))
  return v.langs.map((l) => ROSTER_LABEL(l.locale)).join(',')
}
function ROSTER_LABEL(locale) {
  const names = { 'zh-CN': '汉语', 'en-US': '英语', 'de-DE': '德语', 'fr-FR': '法语', 'es-ES': '西班牙语', 'ru-RU': '俄语', 'el-GR': '希腊语', 'hi-IN': '印地语', 'ar-SA': '阿拉伯语', 'he-IL': '希伯来语', 'ja-JP': '日语', 'ko-KR': '韩语' }
  return names[locale] ?? locale
}

// ---------------------------------------------------------------- 5b 叠印对齐门（ar/he/hi 的 4 行各查一次）
{
  for (const [tag, hideLayer] of [['lay', 'top'], ['top', 'lay']]) {
    const css = `\n/* overlay probe */\n.stack .${hideLayer} { visibility:hidden; }\n`
    const p = join(OUT, 'poster_src.html')
    writeFileSync(join(OUT, `overlay_${tag}_src.html`), readFileSync(p, 'utf8').replace('</style>', `${css}</style>`), 'utf8')
    feuille(['poster', 'assemble', join(OUT, `overlay_${tag}_src.html`), join(OUT, `overlay_${tag}.html`)])
    feuille(['poster', 'render', join(OUT, `overlay_${tag}.html`), join(OUT, `overlay_${tag}.png`), '1240', '1754', '2'])
  }
  const rowRects = JSON.parse(readFileSync(join(OUT, 'rows.json'), 'utf8'))
  for (const label of ['印地语', '阿拉伯语', '希伯来语']) {
    const rows = rowRects[label]
    if (!rows) { console.error(`✖ diag 里没有「${label}」的词行`); process.exit(1) }
    for (const [i, r] of rows.entries()) {
      feuille(['poster', 'check-overlay', join(OUT, 'overlay_lay.png'), join(OUT, 'overlay_top.png'),
        String(r[0]), String(r[1]), String(r[2]), String(r[3]), '--scale', '2'])
    }
    console.log(`  叠印门 ${label}：${rows.length} 行全过`)
  }
}

// ---------------------------------------------------------------- 6 配音
feuille(['karaoke', 'tts', join(OUT, 'voices.json'), join(OUT, 'tts')])

// ---------------------------------------------------------------- 7 时间线 + 旁白实测 + BGM
const cfgPath = join(OUT, 'video.json')
const cfg = {
  src: 'video.html', fonts_css: 'fonts.css', tts_dir: 'tts',
  locales: JSON.parse(readFileSync(join(OUT, 'voices.json'), 'utf8')).langs.map((l) => l.locale),
  preroll: 0.8, tail: 0.8, done: 0.5, intro: 2.2, outro: 2.8,
  intro_image: 'cover_lc.png', desk: '0xe8e2d4',
  formats: [
    { name: 'landscape', w: 1920, h: 1080, frames: 'frames', output: `out/${epData.slug}_landscape.mp4`, fmt: null, poster_filter: 'scale=1920:1080', intro_image: 'cover_lc.png' },
    { name: 'portrait', w: 1080, h: 1920, frames: 'frames_v', output: `out/${epData.slug}_portrait.mp4`, fmt: 'v', poster_filter: 'scale=1080:1920', intro_image: 'cover_pt.png' },
  ],
}
writeFileSync(cfgPath, JSON.stringify(cfg, null, 1) + '\n', 'utf8')
const nar = JSON.parse(run('node', [join(USINE, 'tools', 'foodnames', 'measure_narration.mjs'), OUT], { capture: true, quiet: true }))
console.log(`  旁白实测：${nar.narration_rms_dbfs} dBFS（最响 ${nar.loudest?.loc} / 最轻 ${nar.quietest?.loc}，跨度 ${nar.spread_db} dB）`)
console.log(`  成片时长：${nar.video_total_s}s`)

if (BGM) {
  if (!BGM_JSON) { console.error('✖ 给了 --bgm 就必须给 --bgm-json'); process.exit(1) }
  const side = JSON.parse(readFileSync(BGM_JSON, 'utf8'))
  const bedRms = side?.measured?.rms_dbfs
  if (typeof bedRms !== 'number') { console.error('✖ 床边车里没有 measured.rms_dbfs'); process.exit(1) }
  if (side.measured.duration_s < nar.bed_target_s) {
    console.error(`✖ 床只有 ${side.measured.duration_s}s < 成片 ${nar.bed_target_s}s`)
    process.exit(1)
  }
  const gain = Math.pow(10, (nar.narration_rms_dbfs - TARGET_UNDER_DB - bedRms) / 20)
  cfg.bgm = { file: BGM.split(/[\\/]/).pop(), gain: +gain.toFixed(4), fade_in: 1.5, fade_out: 3.0 }
  writeFileSync(cfgPath, JSON.stringify(cfg, null, 1) + '\n', 'utf8')
  writeFileSync(join(OUT, `${cfg.bgm.file}.json`), readFileSync(BGM_JSON), 'utf8')
  if (!existsSync(join(OUT, cfg.bgm.file))) writeFileSync(join(OUT, cfg.bgm.file), readFileSync(BGM))
  console.log(`  床：${cfg.bgm.file} → gain ${cfg.bgm.gain}`)
} else {
  console.log('  （无 BGM：无床成片——发布前补床重渲）')
}

// ---------------------------------------------------------------- 8 成片
feuille(['poster', 'assemble', join(OUT, 'video_src.html'), join(OUT, 'video.html')])
feuille(['karaoke', 'build', cfgPath])

// ---------------------------------------------------------------- 9 成片验收
const vids = cfg.formats.map((f) => join(OUT, f.output)).filter((v) => existsSync(v))
// 帧边缘溢出门（确定性，`feuille karaoke check-edges`）：场景内所有元素
// 离帧缘 ≥ 36px；状态帧 4px 边缘带出现非纸色像素 = 元素出画（竖版卡超宽
// 就是 ep01 实测过的病）。intro/outro 不进门：封面卡按平台契约自带 8px
// 彩色边框（foodnames 同款，cover check 采样它），贴边是设计不是缺陷。
{
  const FMT_FRAMES = cfg.formats.map((f) => join(OUT, f.frames)).filter((d) => existsSync(d))
  if (FMT_FRAMES.length) {
    feuille(['karaoke', 'check-edges', ...FMT_FRAMES, '--skip', 'intro.png,outro.png'])
  }
}
feuille(['karaoke', 'scan-blank', ...vids])
for (const f of cfg.formats) {
  const v = join(OUT, f.output)
  if (!existsSync(v)) continue
  feuille(['karaoke', 'verify-sync',
    '--video', v, '--frames', join(OUT, f.frames), '--tts', join(OUT, 'tts'),
    '--locales', cfg.locales.join(','),
    '--preroll', String(cfg.preroll), '--done', String(cfg.done), '--intro', String(cfg.intro)])
}

console.log(`\n✅ 第 ${String(EPISODE).padStart(2, '0')} 集（${epData.title_zh}）产线跑完：${OUT}`)
