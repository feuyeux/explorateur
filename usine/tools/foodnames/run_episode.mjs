// run_episode.mjs — 「各国美食名称」系列：**一期从数据跑到可发布**
//
// 一条命令跑完整条产线，任一门禁红就当场停（非零退出码），不留半成品：
//   生成源文件 → 字体子集 → 韩语补丁测量注入 → 海报 → 三版封面 → 门禁
//   → 配音 → 旁白实测 → BGM 增益反推 → 双画幅成片 → 同步/白帧验收
//
// 跑法（仓库根目录）：
//   pnpm exec tsx tools/foodnames/run_episode.mjs \
//     --data tools/foodnames/data/ep02-coffee.json \
//     --out examples/foodnames-ep02-coffee \
//     --bgm examples/_beds/bed-a.wav --bgm-json examples/_beds/bed-a.wav.json
//
// ⚠️ 本脚本只做**本地**渲染与门禁，零平台流量。
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { platform } from '../../packages/core/src/index.ts'

const here = dirname(fileURLToPath(import.meta.url))
const USINE = resolve(here, '..', '..')

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}
const DATA = resolve(arg('data'))
const OUT = resolve(arg('out'))
const BGM = arg('bgm') ? resolve(arg('bgm')) : null
const BGM_JSON = arg('bgm-json') ? resolve(arg('bgm-json')) : null
const SKIP_BUILD = process.argv.includes('--skip-build')
const ONLY = arg('only') // landscape | portrait（不给 = 两版都出）
const TARGET_UNDER_DB = Number(arg('target-under-db', '16'))

mkdirSync(OUT, { recursive: true })

// ---------------------------------------------------------------- 命令执行
let stepNo = 0
function run(cmd, args, { capture = false, cwd = USINE, quiet = false } = {}) {
  stepNo += 1
  const label = `${String(stepNo).padStart(2, '0')} ${cmd} ${args.slice(0, 3).join(' ')}`
  if (!quiet) console.log(`\n▶ ${label}`)
  const r = spawnSync(cmd, args, { cwd, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  if (r.error) {
    console.error(`✖ ${label}\n  ${r.error.message}`)
    process.exit(1)
  }
  if (r.status !== 0) {
    console.error(`✖ ${label}（退出码 ${r.status}）`)
    const err = (r.stderr || '').trim()
    const outp = (r.stdout || '').trim()
    if (err) console.error(err.slice(-3000))
    else if (outp) console.error(outp.slice(-3000))
    process.exit(r.status === 0 ? 1 : r.status)
  }
  if (capture) return (r.stdout || '') + (r.stderr || '')
  return ''
}

/** 产线 CLI：直接走 tsx 入口（Windows 上 pnpm 是 .ps1，spawn 不了）。 */
function feuille(args, opts = {}) {
  return run('node', ['--import', 'tsx', join(USINE, 'packages', 'cli', 'src', 'main.ts'), ...args], opts)
}

// ---------------------------------------------------------------- 数据
const data = JSON.parse(readFileSync(DATA, 'utf8'))
const EP = data.episode
const SLUG = data.slug
const LANGS = data.words.map((w) => w.label).join(',')
console.log(`\n═══ 第 ${String(EP).padStart(2, '0')} 期 · ${data.title_zh} (${SLUG}) ═══`)

// ---------------------------------------------------------------- 1 生成源文件
if (!SKIP_BUILD) {
  run('node', ['--import', 'tsx', join(here, 'build_episode.mjs'), '--data', DATA, '--out', OUT])
}

// ---------------------------------------------------------------- 2 字体子集
feuille(['poster', 'fetch-fonts', join(OUT, 'fonts.json')])

// ---------------------------------------------------------------- 3 韩语补丁（逐音节实测 → 注入）
// ⚠️ **融合音节不进补丁**：初声+中声笔画横接成一个连通域时，矩形补丁拆不开
//    （measure-korean 会报 LABEL FAIL 并退出非零）。这类音节在数据文件里用
//    `ko_fused_syllables` 显式声明，走 `.cv` 融合渐变整字降级。
//    「哪些音节融合」**必须实测**，不猜——所以只量非融合的那些。
const koWord = data.words.find((w) => w.locale === 'ko-KR') ?? {}
const koAll = koWord.ko_syllables ?? []
const koFused = new Set(koWord.ko_fused_syllables ?? [])
const koSyllables = koAll.filter((s) => !koFused.has(s))
if (koFused.size > 0) {
  console.log(`  韩语融合音节（走 .cv 渐变，不做矩形补丁）：${[...koFused].join('/')}`)
}
if (koSyllables.length > 0) {
  const out = feuille(
    ['poster', 'measure-korean', ...koSyllables, '--family', 'Food KR', '--css', join(OUT, 'fonts.css'), '--out', join(OUT, 'k_measure')],
    { capture: true },
  )
  const blocks = [...out.matchAll(/\.k[0-9A-Fa-f]{4,6} \{[^}]*\}/g)].map((m) => m[0])
  if (blocks.length !== koSyllables.length) {
    console.error(`✖ 韩语补丁块数 ${blocks.length} ≠ 非融合音节数 ${koSyllables.length}——测量没出齐`)
    process.exit(1)
  }
  const css = blocks.join('\n')
  for (const f of ['poster_src.html', 'video_src.html']) {
    const p = join(OUT, f)
    writeFileSync(p, readFileSync(p, 'utf8').replace('/*__KO_CSS__*/', css), 'utf8')
  }
  writeFileSync(join(OUT, 'k_measure', 'ko.css'), css, 'utf8')
  console.log(`  韩语补丁：${koSyllables.join('/')} → ${blocks.length} 块已注入`)
}

// ---------------------------------------------------------------- 4 海报 + 三版封面
feuille(['poster', 'assemble', join(OUT, 'poster_src.html'), join(OUT, 'index.html')])
feuille(['poster', 'render', join(OUT, 'index.html'), join(OUT, 'poster.png'), '1240', '1754', '2'])
feuille(['poster', 'make-covers', join(OUT, 'poster_src.html'), join(OUT, 'cover_src.html')])
feuille(['poster', 'assemble', join(OUT, 'cover_src.html'), join(OUT, 'cover.html')])
feuille(['poster', 'render', join(OUT, 'cover.html'), join(OUT, 'cover_lc.png'), '1920', '1080', '1'])
feuille(['poster', 'render', `${join(OUT, 'cover.html')}?fmt=P`, join(OUT, 'cover_pt.png'), '1080', '1920', '1'])
feuille(['poster', 'render', `${join(OUT, 'cover.html')}?fmt=T`, join(OUT, 'cover_t34.png'), '1080', '1440', '1'])

// ---------------------------------------------------------------- 5 门禁：字符 / 适配 / 颜色
feuille(['poster', 'audit-charset', join(OUT, 'poster_src.html'), join(OUT, 'fonts.json')])
feuille(['poster', 'audit-charset', join(OUT, 'video_src.html'), join(OUT, 'fonts.json')])

// fit-diag：自己 dump（page-dump 不是产线命令）——Chrome stdout 必须走管道写文件
const chrome = platform.browserPath()
if (!chrome) { console.error('✖ 找不到 Chromium 系浏览器（设 CHROME_BIN）'); process.exit(1) }
const dumpUrl = 'file:///' + join(OUT, 'index.html').replace(/\\/g, '/') + '?verify=1'
const dump = spawnSync(chrome, [
  '--headless=new', '--disable-gpu', '--no-sandbox', '--virtual-time-budget=15000',
  '--window-size=1240,1754', '--force-device-scale-factor=1', '--hide-scrollbars', '--dump-dom', dumpUrl,
], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
writeFileSync(join(OUT, 'diag.txt'), dump.stdout ?? '', 'utf8')
feuille(['poster', 'fit-diag', join(OUT, 'diag.txt')])

const vcOut = feuille(
  ['poster', 'verify-colors', join(OUT, 'poster.png'), '--cols', '3', '--rows', '4', '--langs', LANGS],
  { capture: true },
)
console.log(vcOut.split('\n').filter((l) => l.includes('lines:')).join('\n'))

// ---------------------------------------------------------------- 5b 融合音节渲染门
// 韩语融合音节（`ko_fused_syllables`）整字走 `.cv` 渐变。若 CSS 规则误用
// `background:` 简写，background-clip 会被重置回 border-box → 渐变画满整个
// 盒子 → 渲染成实心色块（2026-10-20 实测：ep04「토」/ep11「버」）。
// 视频侧 CSS 无此规则 → 成片正常、只有海报坏，肉眼极易漏，必须像素门兜。
run('node', ['--import', 'tsx', join(here, 'check_fused_glyph.mjs'), '--out', OUT])

// ---------------------------------------------------------------- 6 叠印对齐门（ar/he/hi 三格）
{
  // 词框从 fit-diag 的 dump 里取（页面自己报的 .word 矩形，CSS px）：
  // check-overlay 的 x/y/w/h 是 **CSS px**（工具自己乘 --scale 换算设备像素），
  // 且必须是**词形墨迹框**——给整格会让「红独/蓝独」的语境变大，但用词框
  // 才与手测口径一致（实测手测矩形 = dump 里的 word 矩形，逐位相同）。
  const diagTxt = readFileSync(join(OUT, 'diag.txt'), 'utf8')
  const dm = /<title>DIAG (\{.*?\})<\/title>/s.exec(diagTxt)
  if (!dm) { console.error('✖ diag.txt 里没有 DIAG 诊断（fit-diag 的 dump 形状变了？）'); process.exit(1) }
  const cells = JSON.parse(dm[1]).cells
  const rectOf = (label) => {
    const c = cells.find((x) => x.lang === label)
    return c ? c.word : null
  }
  for (const [tag, hideLayer] of [['lay', 'top'], ['top', 'lay']]) {
    const css = `\n/* overlay probe: force grayscale AA, hide one layer */\n.stack .lay, .stack .top { will-change: transform; }\n.stack .${hideLayer} { visibility:hidden; }\n`
    const p = join(OUT, 'poster_src.html')
    writeFileSync(join(OUT, `overlay_${tag}_src.html`), readFileSync(p, 'utf8').replace('</style>', `${css}</style>`), 'utf8')
    feuille(['poster', 'assemble', join(OUT, `overlay_${tag}_src.html`), join(OUT, `overlay_${tag}.html`)])
    feuille(['poster', 'render', join(OUT, `overlay_${tag}.html`), join(OUT, `overlay_${tag}.png`), '1240', '1754', '2'])
  }
  for (const label of ['印地语', '阿拉伯语', '希伯来语']) {
    const r = rectOf(label)
    if (!r) { console.error(`✖ diag 里没有「${label}」的词框`); process.exit(1) }
    feuille(['poster', 'check-overlay', join(OUT, 'overlay_lay.png'), join(OUT, 'overlay_top.png'),
      String(r[0]), String(r[1]), String(r[2]), String(r[3]), '--scale', '2'])
    console.log(`  叠印门 ${label}：${r.join(',')}（CSS px）`)
  }
}

// ---------------------------------------------------------------- 7 配音
feuille(['karaoke', 'tts', join(OUT, 'voices.json'), join(OUT, 'tts')])

// ---------------------------------------------------------------- 8 时间线 + BGM 增益
const cfgPath = join(OUT, 'video.json')
const cfg = existsSync(cfgPath)
  ? JSON.parse(readFileSync(cfgPath, 'utf8'))
  : {
    src: 'video.html', fonts_css: 'fonts.css', tts_dir: 'tts',
    locales: data.words.map((w) => w.locale),
    preroll: 0.8, tail: 0.8, done: 0.5, intro: 2.2, outro: 2.8,
    intro_image: 'cover_lc.png', desk: '0xe8e2d4',
    formats: [
      { name: 'landscape', w: 1920, h: 1080, frames: 'frames', output: `out/${SLUG}_landscape.mp4`, fmt: null, poster_filter: 'scale=1920:1080', intro_image: 'cover_lc.png' },
      { name: 'portrait', w: 1080, h: 1920, frames: 'frames_v', output: `out/${SLUG}_portrait.mp4`, fmt: 'v', poster_filter: 'scale=1080:1920', intro_image: 'cover_pt.png' },
    ],
  }
// 先落一版没有 bgm 的配置，量旁白要用它的 locales
writeFileSync(cfgPath, JSON.stringify(cfg, null, 1) + '\n', 'utf8')
const nar = JSON.parse(run('node', [join(here, 'measure_narration.mjs'), OUT], { capture: true, quiet: true }))
console.log(`  旁白实测：${nar.narration_rms_dbfs} dBFS（最响 ${nar.loudest.loc} / 最轻 ${nar.quietest.loc}，跨度 ${nar.spread_db} dB）`)
console.log(`  成片时长：${nar.video_total_s}s（床需 ≥ ${nar.bed_target_s}s）`)

if (BGM) {
  if (!BGM_JSON) { console.error('✖ 给了 --bgm 就必须给 --bgm-json（床的电平是事实源）'); process.exit(1) }
  const side = JSON.parse(readFileSync(BGM_JSON, 'utf8'))
  const bedRms = side?.measured?.rms_dbfs
  if (typeof bedRms !== 'number') { console.error('✖ 床边车里没有 measured.rms_dbfs——不能算 gain'); process.exit(1) }
  if (side.measured.duration_s < nar.bed_target_s) {
    console.error(`✖ 床只有 ${side.measured.duration_s}s < 成片 ${nar.bed_target_s}s——尾部裸奔，床不能用`)
    process.exit(1)
  }
  const gain = Math.pow(10, (nar.narration_rms_dbfs - TARGET_UNDER_DB - bedRms) / 20)
  cfg.bgm = { file: BGM.split(/[\\/]/).pop(), gain: +gain.toFixed(4), fade_in: 1.5, fade_out: 3.0 }
  console.log(`  床：${cfg.bgm.file} ${side.measured.duration_s}s / ${bedRms} dBFS → gain ${cfg.bgm.gain}（旁白 ${nar.narration_rms_dbfs} − 目标 ${TARGET_UNDER_DB} dB − 床 ${bedRms}）`)
  writeFileSync(cfgPath, JSON.stringify(cfg, null, 1) + '\n', 'utf8')
  // 边车复制进本期目录（床的事实源跟着走）
  const bedCopy = join(OUT, `${cfg.bgm.file}.json`)
  writeFileSync(bedCopy, readFileSync(BGM_JSON, 'utf8'), 'utf8')
  if (!existsSync(join(OUT, cfg.bgm.file))) {
    writeFileSync(join(OUT, cfg.bgm.file), readFileSync(BGM))
  }
} else {
  console.log('  （无 BGM：无床成片——发布前必须补）')
}

// ---------------------------------------------------------------- 9 成片
feuille(['poster', 'assemble', join(OUT, 'video_src.html'), join(OUT, 'video.html')])
feuille(['karaoke', 'build', cfgPath, ...(ONLY ? ['--only', ONLY] : [])])

// ---------------------------------------------------------------- 10 成片验收
const vids = cfg.formats.map((f) => join(OUT, f.output)).filter((v) => existsSync(v))
feuille(['karaoke', 'scan-blank', ...vids])
for (const f of cfg.formats) {
  const v = join(OUT, f.output)
  if (!existsSync(v)) continue
  feuille(['karaoke', 'verify-sync',
    '--video', v, '--frames', join(OUT, f.frames), '--tts', join(OUT, 'tts'),
    '--locales', cfg.locales.join(','),
    '--preroll', String(cfg.preroll), '--done', String(cfg.done), '--intro', String(cfg.intro)])
}

// ---------------------------------------------------------------- 11 发布侧
// 三平台发布词 → facts.json / copy-*.md / manifest.json → 两道发布门禁。
// 发布词是**内容创作**：由作者写进 publish/{xiaohongshu,douyin,bilibili}.md。
// 脚本只抽取、只生成清单，不改写一个字（清单与稿件必须同源）。
// 没有发布词就跳过（不是失败——「还没写稿」与「稿子写坏了」是两回事）。
if (existsSync(join(OUT, 'publish', 'xiaohongshu.md'))) {
  run('node', ['--import', 'tsx', join(here, 'make_publish.mjs'), '--data', DATA, '--out', OUT])
  feuille(['copy', 'check', join(OUT, 'publish'), '--facts', join(OUT, 'publish', 'facts.json')])
  feuille(['publish', 'check-plan', join(OUT, 'publish', 'manifest.json'), '--root', OUT])
} else {
  console.log('  （无发布词：publish/*.md 不存在——跳过发布侧清单与门禁）')
}

console.log(`\n✅ 第 ${String(EP).padStart(2, '0')} 期（${data.title_zh}）产线跑完：${OUT}`)
