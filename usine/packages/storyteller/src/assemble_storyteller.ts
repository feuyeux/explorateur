// assemble_storyteller.ts — 评书成片组装（幕帧 → 叠化转场 → 醒木混音）
// （skills/storyteller-video/scripts/assemble_storyteller.py 的 TS 归流）。
//
// 帧序：片头卡(cover) → 幕1帧…[叠化0.5s]…幕2帧… → 片尾卡。
// 音频：逐幕 mp3 以 preroll 偏移拼接（与 karaoke build 同口径）+ 醒木在每幕
// 开口帧对齐插入（音量 0.7，淡出已烘焙在音效里）。
//
// 归流决定：
// - ffprobe 时长 = core audio.probeDuration（消掉脚本内 ffprobe 拷贝）；
// - Python round() 银行家舍入 = core roundHalfEven；
// - PIL Image.blend 转场帧 = sharp raw 读 + JS 混合直写（栅格化器差异按
//   「比结构与几何」纪律吸收）；
// - 幕段编码用 image2 序列输入（一条 -i 直读连续帧名），**不用 concat
//   demuxer**——它对图片清单每项只给 1 帧时长（DTS 崩，每段只有 1-2 帧
//   的实测事故），原版注释整段照搬；
// - n_in 输入计数器纪律照搬（len(inputs) 会把 flag+路径都数进去——28 事故）。
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

import sharp from 'sharp'

import { FeuilleError, roundHalfEven, audio, platform } from '@feuille/core'

type Cfg = Record<string, any>

function ffmpegBin(): string {
  return platform.requireTool(platform.ffmpeg(), 'ffmpeg')
}

/** Python sh() 同款：失败/超时把尾部 stderr 报出来。 */
function sh(args: Array<string | number>, timeout?: number): void {
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
}

/** 任意 PNG → 3 通道 raw（info.channels 步长抽取）。 */
async function rgbRaw(png: string): Promise<{ data: Buffer; width: number; height: number }> {
  const { data, info } = await sharp(png).raw().toBuffer({ resolveWithObject: true })
  if (info.channels === 3) return { data, width: info.width, height: info.height }
  const out = Buffer.alloc(info.width * info.height * 3)
  for (let i = 0, j = 0; i < info.width * info.height; i++, j += 3) {
    const s = i * info.channels
    out[j] = data[s]!
    out[j + 1] = data[s + 1]!
    out[j + 2] = data[s + 2]!
  }
  return { data, width: info.width, height: info.height }
}

/** PIL Image.blend(a, b, al) 的直实现：out = a·(1−al) + b·al，落 PNG。 */
async function blendPngs(aPng: string, bPng: string, al: number, outPng: string): Promise<void> {
  const a = await rgbRaw(aPng)
  const b = await rgbRaw(bPng)
  if (a.width !== b.width || a.height !== b.height || a.data.length !== b.data.length) {
    throw new FeuilleError(`转场帧尺寸不一致：${aPng} vs ${bPng}`)
  }
  const out = Buffer.alloc(a.data.length)
  for (let i = 0; i < a.data.length; i++) {
    out[i] = Math.round(a.data[i]! * (1 - al) + b.data[i]! * al)
  }
  await sharp(out, { raw: { width: a.width, height: a.height, channels: 3 } })
    .png().toFile(outPng)
}

const ENC = ['-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18'] as const

/** CLI 入口：`feuille storyteller assemble <acts.json> <frames_dir> <out.mp4>
 * [--cover cover_portrait.png] [--outro-card outro_card.png]`。 */
export async function main(argv: string[]): Promise<number> {
  const pos: string[] = []
  let cover = 'cover_portrait.png'
  let outroCard = 'outro_card.png'
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!
    if (a === '--cover') {
      if (i + 1 >= argv.length) throw new FeuilleError('--cover 缺值')
      cover = argv[++i]!
    } else if (a === '--outro-card') {
      if (i + 1 >= argv.length) throw new FeuilleError('--outro-card 缺值')
      outroCard = argv[++i]!
    } else if (a.startsWith('--')) {
      throw new FeuilleError(`未知旗标：${a}`)
    } else {
      pos.push(a)
    }
  }
  if (pos.length < 3) {
    console.error('usage: feuille storyteller assemble <acts.json> <frames_dir> <out.mp4> '
      + '[--cover cover_portrait.png] [--outro-card outro_card.png]')
    return 2
  }
  const [actsJson, framesDir, outMp4] = pos as [string, string, string]

  const FF = ffmpegBin()
  const cfg = JSON.parse(readFileSync(actsJson, 'utf8')) as Cfg
  const F = resolve(framesDir)
  const timing = (cfg['timing'] ?? {}) as Cfg
  const fps = Number(timing['fps'] ?? 30)
  const introD = Number(timing['intro'] ?? 3.0)
  const outroD = Number(timing['outro'] ?? 3.4)
  const transD = Number(timing['transition'] ?? 0.5)
  const preroll = Number(timing['preroll'] ?? 0.8)

  const here = resolve(actsJson, '..')
  // Python 版读了 formats[0] 的 W/H 但全程未用——按原样镜像保留（死值不动）
  void (cfg['formats'] as Array<Cfg>)[0]!['w']

  // ---- 每幕：音频段（mp3 + preroll 偏移）与帧清单 ----
  const actAudio: Array<[string, string, number]> = []
  const actFrameGroups: Array<[string, string, number]> = []
  for (const act of cfg['acts'] as Array<Cfg>) {
    const aid = String(act['id'])
    // gen_tts 按 locale 键落盘（zh-<act>）；先试裸 id 再试带前缀（与 render 同口径）
    const cand = [join(here, 'tts', `${aid}.mp3`), join(here, 'tts', `zh-${aid}.mp3`)]
    const mp3 = cand.find((c) => existsSync(c))
    if (mp3 === undefined) {
      throw new FeuilleError(`缺 TTS 产物 ${join(here, 'tts', `${aid}.mp3`)}`)
    }
    // TTS 落盘键（zh-<act>）。`[\\/]`：win32 路径是 `\` 分隔，`^.*[/]` 剥不掉
    // 目录会把整条绝对路径当键拼进 join，ENOENT 翻倍路径（win32 实测事故）。
    const ttsKey = mp3.replace(/^.*[\\/]/, '').replace(/\.mp3$/, '')
    const framePrefix = aid                                        // 帧名前缀 = render 的 act id（fa1…）
    const adur = audio.probeDuration(mp3)
    // 幕时长 = preroll + 词段（由词表尾推）+ done —— 与 render 口径一致
    const meta = JSON.parse(readFileSync(join(here, 'tts', `${ttsKey}.json`), 'utf8')) as Cfg
    const toks = meta['tokens'] as Array<{ start: number }>
    const nTok = toks.length
    // 帧数（render_act_frames 的口径复算）
    const durs: number[] = [preroll]
    const tail = Number(timing['tail'] ?? 0.8)
    for (let i = 0; i < nTok; i++) {
      const d = i < nTok - 1
        ? toks[i + 1]!['start'] - toks[i]!['start']
        : (adur - toks[i]!['start']) + tail
      durs.push(Math.ceil(d * fps - 1e-9) / fps)
    }
    durs.push(Number(timing['done'] ?? 0.5))
    const nFrames = durs.reduce((acc, d) => acc + roundHalfEven(d * fps), 0)
    actFrameGroups.push([aid, framePrefix, nFrames])
    actAudio.push([aid, mp3, adur])
  }

  // ---- 视频段：cover / acts / outro ----
  const segFiles: string[] = []
  let totalFrames = 0
  const coverImg = join(here, 'video', cover)
  let n = roundHalfEven(introD * fps)
  const p1 = join(F, '_seg_cover.mp4')
  sh([FF, '-y', '-loglevel', 'error', '-loop', '1', '-framerate', fps,
    '-i', coverImg, '-t', (n / fps).toFixed(6), '-frames:v', n, ...ENC, p1], 600)
  segFiles.push(p1); totalFrames += n

  for (let gi = 0; gi < actFrameGroups.length; gi++) {
    const [aid, fpref, nFrames] = actFrameGroups[gi]!
    if (gi > 0) {
      // 叠化转场：前幕末帧 + 本幕首帧 混合若干中间帧
      const [prevAid, prevPref, prevN] = actFrameGroups[gi - 1]!
      void prevAid
      const prevLast = join(F, `f${prevPref}-${String(prevN - 1).padStart(4, '0')}.png`)
      const curFirst = join(F, `f${fpref}-0000.png`)
      const nt = roundHalfEven(transD * fps)
      const tpaths: string[] = []
      for (let k = 1; k <= nt; k++) {
        const al = k / (nt + 1)
        const tp = join(F, `_trans-${gi}-${String(k).padStart(3, '0')}.png`)
        await blendPngs(prevLast, curFirst, al, tp)
        tpaths.push(tp)
      }
      for (const tp of tpaths) {
        const stem3 = tp.replace(/^.*[\\/]/, '').replace(/\.png$/, '').slice(-3)
        const pT = join(F, `_seg_t${gi}-${stem3}.mp4`)
        sh([FF, '-y', '-loglevel', 'error',
          '-framerate', fps, '-loop', '1', '-i', tp,
          '-frames:v', 1, ...ENC, pT], 300)
        segFiles.push(pT); totalFrames += 1
        unlinkSync(tp)
      }
    }
    const p = join(F, `_seg_${aid}.mp4`)
    // 帧序列 concat（同尺寸 png 序列）
    // image2 序列输入：帧名连续（f<act>-0000..NNNN），一条 -i 直读；
    // 不用 concat demuxer——它对图片清单每项只给 1 帧时长（DTS 崩，
    // 每段只有 1-2 帧的实测事故）。-framerate 驱动时间轴。
    sh([FF, '-y', '-loglevel', 'error',
      '-framerate', fps, '-start_number', '0',
      '-i', join(F, `f${fpref}-%04d.png`),
      '-frames:v', nFrames, ...ENC, p], 1800)
    segFiles.push(p); totalFrames += nFrames
  }

  const outroImg = join(here, 'video', outroCard)
  n = roundHalfEven(outroD * fps)
  const p2 = join(F, '_seg_outro.mp4')
  sh([FF, '-y', '-loglevel', 'error', '-loop', '1', '-framerate', fps,
    '-i', outroImg, '-t', (n / fps).toFixed(6), '-frames:v', n, ...ENC, p2], 600)
  segFiles.push(p2); totalFrames += n

  writeFileSync(join(F, '_concat.txt'),
    segFiles.map((s) => `file '${resolve(s)}'\n`).join(''), 'utf8')
  const videoNoaudio = join(F, '_video_noaudio.mp4')
  sh([FF, '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
    '-i', join(F, '_concat.txt'), '-c', 'copy', videoNoaudio])

  // ---- 音频轨：逐幕（偏移累加）+ 醒木对齐幕开口 ----
  const videoDur = audio.probeDuration(videoNoaudio)
  const inputs: string[] = []
  const filters: string[] = []
  const ordered: string[] = []
  let nIn = 0                    // 输入计数器（len(inputs) 会把 flag+路径都数进去——28 事故）
  let sceneStart = introD
  const gavelWav = join(F, 'gavel.wav')
  for (let gi = 0; gi < actAudio.length; gi++) {
    const [aid, mp3] = actAudio[gi]!
    void aid
    inputs.push('-i', mp3)
    filters.push(
      `[${nIn}:a]adelay=${Math.trunc(sceneStart * 1000)}:all=1,`
      + `apad=whole_dur=${videoDur.toFixed(3)},atrim=0:${videoDur.toFixed(3)}[a${gi}]`)
    ordered.push(`[a${gi}]`); nIn += 1
    // Python get("gavel", True)：缺省真、显式 null 为 falsy（镜像，?? 会把 null 也兜成 true）
    const gflag = (cfg['acts'] as Array<Cfg>)[gi]!['gavel']
    if (gflag === undefined ? true : !!gflag) {
      const gdelay = sceneStart + 0.15   // 幕开口 0.15s 处拍下
      inputs.push('-i', gavelWav)
      filters.push(
        `[${nIn}:a]adelay=${Math.trunc(gdelay * 1000)}:all=1,`
        + `apad=whole_dur=${videoDur.toFixed(3)},atrim=0:${videoDur.toFixed(3)}[g${gi}]`)
      ordered.push(`[g${gi}]`); nIn += 1
    }
    // 幕时长（含转场帧的公共时间）——按帧数口径推进
    const nFrames = actFrameGroups[gi]![2]!
    sceneStart += nFrames / fps + (gi > 0 ? transD : 0.0)
  }

  filters.push(`${ordered.join('')}amix=inputs=${ordered.length}:duration=longest:normalize=0[aout]`)
  const fc = filters.join(';')
  sh([FF, '-y', '-loglevel', 'error', ...inputs,
    '-i', videoNoaudio,
    '-filter_complex', fc,
    '-map', `${nIn}:v`, '-map', '[aout]',
    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
    '-movflags', '+faststart', outMp4], 1200)
  console.log(`wrote ${outMp4}  (${totalFrames} 帧, ${(totalFrames / fps).toFixed(1)}s @ ${fps}fps)`)
  return 0
}
