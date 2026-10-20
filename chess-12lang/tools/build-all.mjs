// tools/build-all.mjs —— 12 支批产驱动：封面 → TTS → 合片 → 验收
//
// 用法：node tools/build-all.mjs [--only ep01-white-queen] [--skip-covers] [--formats portrait,landscape]
//
// 两个环境事实（本机实测，见 README「环境坑」）：
//   1) Edge headless 从 Node 子进程启动不落盘截图 → 必须 FEUILLE_BROWSER=chrome；
//   2) 浏览器 --screenshot 只认**绝对路径**（相对路径静默不产出）→ 所有输出路径先 resolve。
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync, copyFileSync, mkdirSync, rmSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const USINE = resolve(ROOT, '..', 'usine')
const TSX_CLI = join(USINE, 'node_modules', 'tsx', 'dist', 'cli.mjs')
const CLI = join(USINE, 'packages', 'cli', 'src', 'main.ts')
const DATA = JSON.parse(readFileSync(join(ROOT, 'data', 'series.json'), 'utf8'))

const argv = process.argv.slice(2)
const only = argv.includes('--only') ? argv[argv.indexOf('--only') + 1] : null
const from = argv.includes('--from') ? Number(argv[argv.indexOf('--from') + 1]) : 1
const to = argv.includes('--to') ? Number(argv[argv.indexOf('--to') + 1]) : 99
const skipCovers = argv.includes('--skip-covers')
const onlyFormats = argv.includes('--formats') ? argv[argv.indexOf('--formats') + 1].split(',') : null

process.env['FEUILLE_BROWSER'] = process.env['FEUILLE_BROWSER']
  ?? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'

function run(args, cwd) {
  // Windows 上 .cmd 包装器不能直接 spawn（要 shell）→ 走 node + tsx 的 js 入口
  const r = spawnSync(process.execPath, [TSX_CLI, CLI, ...args], {
    cwd, encoding: 'utf8', timeout: 3600_000, env: process.env,
    maxBuffer: 64 * 1024 * 1024,
  })
  const out = `${r.stdout ?? ''}${r.stderr ?? ''}`
  if (r.error) console.log('  spawn error:', r.error.message)
  return { code: r.status ?? -1, out }
}

function raw(cmd, args, cwd) {
  const r = spawnSync(cmd, args, { cwd, encoding: 'utf8', timeout: 120_000, maxBuffer: 16 * 1024 * 1024 })
  return { code: r.status ?? -1, out: `${r.stdout ?? ''}${r.stderr ?? ''}` }
}

function step(name, args, cwd) {
  const t0 = Date.now()
  const r = run(args, cwd)
  const sec = ((Date.now() - t0) / 1000).toFixed(1)
  console.log(`  [${name}] exit=${r.code} ${sec}s`)
  if (r.code !== 0) console.log(r.out.split('\n').slice(-12).join('\n'))
  return r
}

const COVER_SPECS = [
  { key: 'douyin', src: 'cover_pt_src.html', out: 'cover_douyin_1080x1920.png' },
  { key: 'douyin34', src: 'cover_t34_src.html', out: 'cover_douyin34_1080x1440.png' },
  { key: 'xiaohongshu', src: 'cover_pt_src.html', out: 'cover_xiaohongshu_1080x1920.png' },
  { key: 'bilibili', src: 'cover_lc_src.html', out: 'cover_bilibili_1920x1080.png' },
]

const summary = []
for (const ep of DATA.episodes) {
  if (only && ep.id !== only) continue
  if (ep.no < from || ep.no > to) continue
  const dir = join(ROOT, 'episodes', ep.id)
  mkdirSync(join(dir, 'out'), { recursive: true })
  mkdirSync(join(dir, 'tts'), { recursive: true })
  console.log(`\n=== ${ep.id} · ${ep.title_zh} ===`)
  const rec = { id: ep.id, title: ep.title_zh, no: ep.no }

  if (!skipCovers) {
    for (const spec of COVER_SPECS) {
      const r = step(`cover:${spec.key}`, ['cover', 'make', spec.key, spec.src, join(dir, spec.out)], dir)
      if (r.code !== 0) rec.coverError = spec.key
    }
    // 片头/片尾卡：竖版用 9:16，横版用 16:9
    copyFileSync(join(dir, 'cover_douyin_1080x1920.png'), join(dir, 'cover_pt.png'))
    copyFileSync(join(dir, 'cover_bilibili_1920x1080.png'), join(dir, 'cover_lc.png'))
  }

  const tts = step('tts', ['karaoke', 'tts', 'voices.json', 'tts'], dir)
  rec.tts = tts.code

  // 验收 D（插在合片之前）：每个 token 都得有起止时间。
  // 工厂的 `karaoke tts` 在 token 时间为 null 时崩在 `fmt2(null)`，报错完全看不出
  // 是哪支哪一语种哪个字——这里把「缺口」自己算出来说清楚，并且**不往下走**。
  if (tts.code === 0) {
    const problems = []
    for (const loc of ['nar', ...DATA.locales.map((l) => l.locale)]) {
      const p = join(dir, 'tts', `${loc}.json`)
      if (!existsSync(p)) { problems.push(`${loc}: 缺 ${loc}.json`); continue }
      const j = JSON.parse(readFileSync(p, 'utf8'))
      const bad = (j.tokens ?? []).filter((t) => t.start === null || t.end === null)
      if (bad.length) {
        problems.push(`${loc}: ${bad.length} 个 token 没有时间（${bad.slice(0, 3).map((t) => t.text).join(' / ')}）`)
      }
    }
    if (problems.length) {
      rec.ttsTokenTimes = problems
      console.log(`  [tts-token-times] FAIL ${problems.join(' | ')}`)
    } else {
      rec.ttsTokenTimes = 'PASS'
    }
  }

  // TTS 没成 / token 时间有缺口 → 不往下走（合片只会报一堆看不懂的 ENOENT）
  if (tts.code !== 0 || (rec.ttsTokenTimes && rec.ttsTokenTimes !== 'PASS')) {
    rec.build = -1
    summary.push(rec)
    writeFileSync(join(ROOT, 'build-summary.json'), JSON.stringify(summary, null, 1), 'utf8')
    continue
  }

  const buildArgs = ['karaoke', 'build', 'video.json']
  for (const f of onlyFormats ?? []) buildArgs.push('--only', f)
  const build = step('build', buildArgs, dir)
  rec.build = build.code
  if (build.code !== 0) { summary.push(rec); continue }

  // 验收 A：时长实测（两版）
  for (const f of onlyFormats ?? ['portrait', 'landscape']) {
    const mp4 = join(dir, 'out', `${ep.id}_${f}.mp4`)
    if (!existsSync(mp4)) { rec[`${f}_missing`] = true; continue }
    const pr = raw('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', mp4], dir)
    rec[`${f}_dur`] = Number((pr.out || '').trim())
  }

  // 验收 B：全片白页扫描
  const vids = (onlyFormats ?? ['portrait', 'landscape'])
    .map((f) => join(dir, 'out', `${ep.id}_${f}.mp4`)).filter((p) => existsSync(p))
  const blank = step('scan-blank', ['karaoke', 'scan-blank', ...vids], dir)
  rec.scanBlank = blank.code

  // 验收 C：AV 同步（状态帧 vs 成片抓帧像素差）
  for (const f of onlyFormats ?? ['portrait', 'landscape']) {
    const framesDir = f === 'portrait' ? 'frames_v' : 'frames'
    const mp4 = join(dir, 'out', `${ep.id}_${f}.mp4`)
    if (!existsSync(mp4)) continue
    const locales = ['nar', ...DATA.locales.map((l) => l.locale)].join(',')
    const sync = step(`verify-sync:${f}`, [
      'karaoke', 'verify-sync', '--video', mp4, '--frames', join(dir, framesDir),
      '--tts', join(dir, 'tts'), '--locales', locales,
    ], dir)
    rec[`sync_${f}`] = sync.code
  }

  summary.push(rec)
  writeFileSync(join(ROOT, 'build-summary.json'), JSON.stringify(summary, null, 1), 'utf8')
}

writeFileSync(join(ROOT, 'build-summary.json'), JSON.stringify(summary, null, 1), 'utf8')
console.log('\n=== 汇总 ===')
for (const r of summary) console.log(JSON.stringify(r))
