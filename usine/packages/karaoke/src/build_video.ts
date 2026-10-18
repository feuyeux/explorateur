// build_video.ts — 确定性状态帧 + TTS 音轨组装卡拉OK成片
// （karaoke-video/scripts/build_video.py 的 TS 归流）。
//
// video.json 契约与时间线语义见 SKILL.md 与 references/av-sync.md：
// 每场景 preroll（全暗）| 每 token 一帧（在下一 token 的 start 切换）|
// 末词撑到音频结束 + tail | done 帧。所有时长吸附 30fps 网格、按精确帧数
// 编码（concat 漂移的解法，见 references/av-sync.md）。
//
// 归流决定：
// - ffprobe 时长探测 = @feuille/core audio.probeDuration（唯一实现，消掉
//   脚本内 ffprobe 拷贝）；
// - 浏览器解析 = @feuille/core platform.browserPath（唯一事实源）；
// - 截图参数组与 textlayer.shotArgs 同源（参数序照原版镜像）；帧截图是
//   **精确画幅**模式（URL 直载 + window-size=W,H，不做视口亏空补偿——
//   状态帧必须逐像素等于成片画幅），白页哨兵（>90% 近纯白）保留；
// - ffmpeg 编排（intro/outro 卡、分段编码、concat、bgm amix）是本产线的
//   专属逻辑，留在包内。二进制在函数内解析（缺件在调用时报，不在 import
//   时把整个包炸掉——与 Python 脚本顶部 sys.exit 同效但更晚一步，代价是
//   包可以安全地被 barrel 导入）。
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

import sharp from 'sharp'

import { FeuilleError, audio, platform } from '@feuille/core'

const FPS = 30

function ffmpegBin(): string {
  const got = platform.ffmpeg()
  if (!got) {
    throw new FeuilleError('找不到 ffmpeg（feuille.platform 解析；请安装后重跑）')
  }
  return got
}

/** Python sh() 同款：失败/超时把尾部 stderr 报出来（FeuilleError → stderr + 1）。 */
function sh(args: Array<string | number>, timeout?: number): { stdout: string } {
  const strs = args.map(String)
  const r = spawnSync(strs[0]!, strs.slice(1), {
    encoding: 'utf8',
    timeout: timeout == null ? undefined : timeout * 1000,
  })
  if (r.error) {
    throw new FeuilleError(`FAILED: ${strs.join(' ')}\n${r.error.message}`)
  }
  if (r.status !== 0) {
    throw new FeuilleError(`FAILED: ${strs.join(' ')}\n${(r.stderr ?? '').slice(-2000)}`)
  }
  return { stdout: r.stdout ?? '' }
}

/** 时长吸附 fps 网格——时间线逐帧精确（references/av-sync.md）。 */
export function d30(d: number): number {
  return Math.ceil(d * FPS - 1e-9) / FPS
}

/** 近纯白像素占比（min(R,G,B) >= 250；PIL getdata 口径的 sharp 对应）。 */
async function whiteRatio(png: string, w: number, h: number): Promise<number> {
  const { data } = await sharp(png).removeAlpha().resize(w, h).raw()
    .toBuffer({ resolveWithObject: true })
  let white = 0
  for (let i = 0; i < data.length; i += 3) {
    if (data[i]! >= 250 && data[i + 1]! >= 250 && data[i + 2]! >= 250) white++
  }
  return white / (w * h)
}

/** headless 截图——参数组与 library 的 textlayer.shotArgs 同源。
 *
 * **精确画幅模式**：URL 直载（?lang=…&state=… 页内状态机）+ window-size=W,H，
 * 不带 --user-data-dir / --no-sandbox（AGENTS.md 实测：带 user-data-dir
 * 图能出但进程永不退出；不带 1.7s 退出）。timeout=180 兜底，挂了响亮地失败。
 * 白页哨兵同步判：>90% 近纯白 = 页面根本没渲出来，当场停。 */
async function renderChrome(out: string, url: string, w: number, h: number): Promise<void> {
  const browser = platform.browserPath()
  if (!browser) {
    throw new FeuilleError('找不到 Chromium 系浏览器；装 Chrome 或 Edge，或设 CHROME_BIN')
  }
  sh([browser, '--headless=new', '--disable-gpu', ...platform.HEADLESS_FLAGS,
    '--virtual-time-budget=10000', `--window-size=${w},${h}`,
    '--force-device-scale-factor=1', '--hide-scrollbars',
    `--screenshot=${out}`, url], 180)
  if (!existsSync(out)) {
    throw new FeuilleError(`浏览器退出 0 但没写出 ${out}——大概率被已开着的桌面浏览器`
      + `抢占（singleton 移交）。关掉桌面浏览器后重试。\nURL was: ${url}`)
  }
  if (await whiteRatio(out, 64, 36) > 0.9) {
    throw new FeuilleError(`BLANK RENDER (page failed to load?): ${out}\nURL was: ${url}`)
  }
}

type FmtCfg = Record<string, any>

async function buildFormat(fmt: FmtCfg, cfg: Record<string, any>, here: string, ttsDir: string): Promise<void> {
  const FF = ffmpegBin()
  const F = join(here, fmt['frames'])
  mkdirSync(F, { recursive: true })
  const W = fmt['w'] as number, H = fmt['h'] as number
  const fmtq = fmt['fmt'] ? `&fmt=${fmt['fmt']}` : ''
  const PREROLL = cfg['preroll'] as number, TAIL = cfg['tail'] as number, DONE = cfg['done'] as number

  // intro / outro 卡片来自 intro 图（每画幅可覆盖）；图片与画幅同尺寸时
  // filter 是 no-op scale——满幅无 desk 留边
  const desk = cfg['desk'] ?? '0xe8e2d4'
  const vf = (fmt['poster_filter'] as string).replaceAll('{desk}', desk)
  const img = join(here, fmt['intro_image'] ?? cfg['intro_image'])
  for (const name of ['intro', 'outro']) {
    sh([FF, '-y', '-loglevel', 'error', '-i', img, '-vf', vf, join(F, `${name}.png`)])
  }

  const videoParts: Array<[string, number]> = [] // [png, 网格化时长]
  const audioParts: string[] = []
  for (const [name, dur] of [['_sil_intro', cfg['intro']], ['_sil_outro', cfg['outro']]] as const) {
    sh([FF, '-y', '-loglevel', 'error', '-f', 'lavfi',
      '-i', 'anullsrc=r=24000:cl=mono', '-t', dur, join(F, `${name}.wav`)])
  }
  videoParts.push([join(F, 'intro.png'), d30(cfg['intro'])])
  audioParts.push(join(F, '_sil_intro.wav'))

  for (const loc of cfg['locales'] as string[]) {
    const meta = JSON.parse(readFileSync(join(ttsDir, `${loc}.json`), 'utf8'))
    const toks = meta['tokens'] as Array<{ start: number }>
    const k = toks.length
    const adur = audio.probeDuration(join(ttsDir, `${loc}.mp3`))

    await renderChrome(join(F, `${loc}-pre.png`),
      `${pathToFileURL(join(here, cfg['src'])).href}?lang=${loc}&state=-1${fmtq}`, W, H)
    videoParts.push([join(F, `${loc}-pre.png`), d30(PREROLL)])
    const sceneDurs: number[] = []
    for (let s = 0; s < k; s++) {
      await renderChrome(join(F, `${loc}-${s}.png`),
        `${pathToFileURL(join(here, cfg['src'])).href}?lang=${loc}&state=${s}${fmtq}`, W, H)
      const d = s < k - 1
        ? toks[s + 1]!['start'] - toks[s]!['start']
        : adur - toks[s]!['start'] + TAIL
      sceneDurs.push(d30(d))
      videoParts.push([join(F, `${loc}-${s}.png`), sceneDurs[sceneDurs.length - 1]!])
    }
    await renderChrome(join(F, `${loc}-done.png`),
      `${pathToFileURL(join(here, cfg['src'])).href}?lang=${loc}&state=${k}${fmtq}`, W, H)
    sceneDurs.push(d30(DONE))
    videoParts.push([join(F, `${loc}-done.png`), sceneDurs[sceneDurs.length - 1]!])

    const total = d30(PREROLL) + sceneDurs.reduce((a, b) => a + b, 0) // 必须含 preroll 帧
    const seg = join(F, `${loc}-seg.wav`)
    sh([FF, '-y', '-loglevel', 'error', '-i', join(ttsDir, `${loc}.mp3`),
      '-af', `adelay=${Math.trunc(PREROLL * 1000)}:all=1,apad`, '-t', total.toFixed(3),
      '-ar', '24000', '-ac', '1', seg])
    audioParts.push(seg)
    console.log(`  ${loc}: ${k} tokens, scene ${total.toFixed(2)}s`)
  }

  videoParts.push([join(F, 'outro.png'), d30(cfg['outro'])])
  audioParts.push(join(F, '_sil_outro.wav'))

  // concat：每段按精确帧数编码，再流拷贝（concat 漂移的解法）
  const segFiles: string[] = []
  for (let i = 0; i < videoParts.length; i++) {
    const [png, d] = videoParts[i]!
    const n = Math.max(1, Math.round(d * FPS))
    const out = join(F, `_vseg${String(i).padStart(3, '0')}.mp4`)
    sh([FF, '-y', '-loglevel', 'error', '-loop', '1', '-framerate', FPS,
      '-i', png, '-t', (n / FPS).toFixed(6), '-frames:v', n,
      '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'medium',
      '-crf', '18', out])
    segFiles.push(out)
  }
  writeFileSync(join(here, 'concat_v.txt'),
    segFiles.map((seg) => `file '${seg}'\n`).join(''), 'utf8')
  writeFileSync(join(here, 'concat_a.txt'),
    audioParts.map((wav) => `file '${wav}'\n`).join(''), 'utf8')

  sh([FF, '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
    '-i', join(here, 'concat_v.txt'), '-c:v', 'copy', join(here, 'video_noaudio.mp4')])
  sh([FF, '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
    '-i', join(here, 'concat_a.txt'), '-c:a', 'pcm_s16le', join(here, 'audio_all.wav')])
  const out = join(here, fmt['output'])

  const bgm = cfg['bgm'] as Record<string, any> | undefined
  if (bgm) {
    // 底床垫在旁白下：裁到视频网格、两端淡入淡出、固定增益，再 amix
    // （normalize=0 保住人声电平）
    const vdur = audio.probeDuration(join(here, 'video_noaudio.mp4'))
    const fi = bgm['fade_in'] ?? 1.5, fo = bgm['fade_out'] ?? 3.0
    const track = join(F, '_bgm_track.wav')
    sh([FF, '-y', '-loglevel', 'error',
      '-i', resolve(join(here, bgm['file'])),
      '-af', `afade=t=in:st=0:d=${fi},`
        + `afade=t=out:st=${Math.max(0, vdur - fo).toFixed(3)}:d=${fo},`
        + `volume=${bgm['gain'] ?? 0.1}`,
      '-t', vdur.toFixed(3), '-ar', '48000', '-ac', '2', track])
    sh([FF, '-y', '-loglevel', 'error', '-i', join(here, 'video_noaudio.mp4'),
      '-i', join(here, 'audio_all.wav'), '-i', track,
      '-filter_complex',
      '[1:a]aformat=sample_rates=48000:channel_layouts=stereo[nar];'
      + '[nar][2:a]amix=inputs=2:duration=first:normalize=0[aout]',
      '-map', '0:v', '-map', '[aout]', '-c:v', 'copy',
      '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', out])
  } else {
    sh([FF, '-y', '-loglevel', 'error', '-i', join(here, 'video_noaudio.mp4'),
      '-i', join(here, 'audio_all.wav'), '-c:v', 'copy', '-c:a', 'aac',
      '-b:a', '128k', '-movflags', '+faststart', out])
  }
  console.log(`  wrote ${out}`)
}

/** CLI 入口：`feuille karaoke build <video.json> [--only FORMAT_NAME]`。
 * 原版 `sys.argv[index("--only")+1]`：--only 缺值在 Python 是 IndexError
 * 当场炸——这里 FeuilleError 同位报（统一入口 → 1）。 */
export async function main(argv: string[]): Promise<number> {
  const cfgPath = argv.find((a) => !a.startsWith('--'))
  if (!cfgPath) {
    console.error('usage: feuille karaoke build <video.json> [--only FORMAT_NAME]')
    return 2
  }
  const onlyIdx = argv.indexOf('--only')
  if (onlyIdx >= 0 && argv.length <= onlyIdx + 1) {
    throw new FeuilleError('usage: feuille karaoke build <video.json> [--only FORMAT_NAME]')
  }
  const only = onlyIdx >= 0 ? argv[onlyIdx + 1]! : null
  const cfg = JSON.parse(readFileSync(cfgPath, 'utf8'))
  const here = resolve(cfgPath, '..') // 绝对路径：相对 dir 会让 file:// URL
  // 按 host 解析 → Chrome 去搜 Google（原版注释的坑）
  const ttsDir = join(here, cfg['tts_dir'] ?? 'tts')

  // html 组装一次（注入字体）。按原样镜像：产物 video_build.html 落盘，
  // 但状态帧截图的 URL 用的是**原始** cfg.src（Python 原版如此——要改另立议题）
  const html = readFileSync(join(here, cfg['src']), 'utf8')
  const fonts = readFileSync(join(here, cfg['fonts_css']), 'utf8')
  writeFileSync(join(here, 'video_build.html'), html.replace('/*__FONTS__*/', fonts), 'utf8')

  for (const fmt of cfg['formats'] as FmtCfg[]) {
    if (only && fmt['name'] !== only) continue
    console.log(`format: ${fmt['name']} (${fmt['w']}x${fmt['h']})`)
    await buildFormat(fmt, cfg, here, ttsDir)
  }

  // 中间产物即弃
  for (const p of ['audio_all.wav', 'video_noaudio.mp4']) {
    const f = join(here, p)
    if (existsSync(f)) unlinkSync(f)
  }
  return 0
}
