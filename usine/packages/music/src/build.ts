// build.ts — 状态帧渲染 + 帧精确装配（music-annotate-video 的成片核心）。
//
// 为什么不能直接用 `feuille karaoke build`：那条线的音频是**固定增益
// amix**，表达不了本产线要的「摘录绝对偏移 + 旁白期 ducking + 聆听段
// 全电平」。所以这里自建装配器，但**纪律全部沿用**（见
// skills/music-annotate-video/references/music-av-traps.md）：
//
// - §7  段 [t[i−1], t[i]) 显示 state i−1 —— off-by-one 会让高亮整体错一块。
// - §8  音乐轨必须顺延 preroll —— 否则所有高亮滞后 0.8s。
// - §9  时长钳制在**帧域**做（帧数，不是秒）—— 秒域钳制会把短音符撑到 1s。
// - §14 逐场景对账差 0 帧；只看全片总长会漏掉互相抵消的错位。
// - §15 波形用统一 vmaxRef + sqrt 压缩（画面侧，本包只保证数据一致）。
// - §17 播放头只有一份实现（页面 JS overlay），本包只传 ?ph= 参数。
//
// 场景时长模型（验收公式）：`d30(pre + body + done + tail)`。
// **总帧数一次算定**（framesFor(pre+body+done+tail)），各段按自己的时长
// 分配帧数，最后一段吸收舍入余数；编码后再用 ffprobe 独立数帧对账，
// 不能拿同一份计划数同时充当预期值与实测值。
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

import { FeuilleError, framesFor, platform, snapToGrid } from '@feuille/core'

import { numOpt, parseArgs } from './cli.js'

/** 一段旁白。 */
export interface Narration {
  /** 旁白音频文件（相对项目根）。 */
  file: string
  /** 场景内起点（秒）。 */
  at_s: number
  /** 增益（默认 1.0）。 */
  gain?: number
}

/** 一个状态（画面的一段）。 */
export interface SceneState {
  /** 场景内起点（秒）。 */
  t0: number
  /** 场景内终点（秒）。 */
  t1: number
  /**
   * 这一 state's 播放头位置（秒）。缺省 = 段中点。
   *
   * 为什么要单独给：摘录场景有一段「旁白在讲、音乐还没进」的引子，
   * 那段时间里播放头必须停在 0（**没有音乐在走**）。用段中点会把播放头
   * 画到画面中间，看起来像音乐已经开始了——那是画面在说假话。
   */
  playhead_s?: number
}

/** 一个场景。 */
export interface Scene {
  id: string
  /** 场景类型（chords / melody / waveform / bio / map / credit）。 */
  kind?: string
  /**
   * 本场景用的录音文件（相对项目根）。
   *
   * 为什么要按场景覆盖：一部作品常常有**多个录音文件**（分乐章：莫扎特
   * K.550 有三个乐章、四季有十二个协奏曲）。`project.recording.file` 只能
   * 放一个，于是「摘录取自哪个文件」这件事没有地方写——装配时一律去取
   * project.recording.file，摘录时间码就会指向错误的录音。
   */
  recording_file?: string
  /** 录音摘录的绝对区间（秒）。 */
  recording_excerpt?: { start_s: number; end_s: number }
  /** 音乐在场景内的落点（秒）。默认 = preroll。 */
  music_at?: number
  preroll?: number
  tail?: number
  done?: number
  /** 状态序列（场景内秒）。 */
  states: SceneState[]
  /** 注入页面的 DATA（该场景的那一份）。 */
  data?: Record<string, unknown>
  narration?: Narration[]
  /** 是否是制作信息页（两段式）。 */
  credit?: boolean
}

/** 音频轨（母版时间轴上的绝对秒）。 */
export interface AudioTrack {
  role: string
  file: string
  /** 在录音里的绝对位置（秒）——摘录起点。 */
  offset_s?: number
  /** 增益包络（母版绝对秒）。 */
  envelope?: Array<{ from_s: number; to_s: number; gain: number }>
}

/** 项目契约（project.json）。 */
export interface MusicProject {
  work: { title: string; composer?: string; movements?: number }
  recording: { file: string; source_id?: string; duration_s?: number }
  score?: { file: string; source_id?: string; kind?: string }
  fps?: number
  /** 状态帧页面（相对项目根）。 */
  status_frame_html: string
  /** 制作信息页页面（可选；缺省用状态帧页的 credit 卡）。 */
  credit_html?: string
  scenes: Scene[]
  audio?: {
    tracks?: AudioTrack[]
    ducking?: { mode?: string; music_gain?: number; rule?: string }
    loudness?: { I?: number; TP?: number; LRA?: number }
  }
  credit?: {
    placeholder_duration_s?: number
    final_duration_s?: number
    fixed_length?: boolean
    facts?: string
    sources?: string
  }
  acceptance?: {
    ink_min_pct?: number
    ink_gray_threshold?: number
    av_stream_diff_ms_max?: number
    scene_duration_diff_frames?: number
    credit_placeholder_scan?: boolean
  }
}

function sh(args: Array<string | number>, timeout?: number): void {
  const strs = args.map(String)
  const r = spawnSync(strs[0]!, strs.slice(1), {
    encoding: 'utf8',
    timeout: timeout == null ? undefined : timeout * 1000,
    maxBuffer: 1 << 26,
  })
  if (r.error) throw new FeuilleError(`FAILED: ${strs.join(' ')}\n${r.error.message}`)
  if (r.status !== 0) {
    throw new FeuilleError(`FAILED: ${strs.join(' ')}\n${(r.stderr ?? '').slice(-2000)}`)
  }
}

// ============================================================
//  页面 DATA 注入
// ============================================================

/**
 * 把项目的 DATA 注入状态帧页面（替换 `const DATA = {…}` 这一个字面量）。
 *
 * 为什么是「替换字面量」而不是「另开一个 data.json 用 fetch 读」：
 * 页面走 `file://`，fetch 本地文件会被 CORS 挡掉；而模板的纪律明写
 * 「DATA 必须在消费者之前」（const 无提升）。替换字面量既保住了脚本顺序，
 * 也保住了「只改 DATA 与几何，不重写脚本顺序」。
 *
 * 注入用括号配对找字面量的边界（不是正则——DATA 里可能有嵌套括号与字符串）。
 */
export function injectData(html: string, data: Record<string, unknown>): string {
  const marker = 'const DATA ='
  const at = html.indexOf(marker)
  if (at < 0) throw new FeuilleError('状态帧页面里找不到 `const DATA =`（模板结构变了？）')
  const open = html.indexOf('{', at)
  if (open < 0) throw new FeuilleError('`const DATA =` 后面没有 `{`')
  let depth = 0
  let inStr: string | null = null
  let esc = false
  for (let i = open; i < html.length; i++) {
    const ch = html[i]!
    if (inStr) {
      if (esc) esc = false
      else if (ch === '\\') esc = true
      else if (ch === inStr) inStr = null
      continue
    }
    if (ch === '"' || ch === "'" || ch === '`') {
      inStr = ch
      continue
    }
    if (ch === '{') depth++
    else if (ch === '}') {
      depth--
      if (depth === 0) {
        const json = JSON.stringify(data, null, 1)
        return `${html.slice(0, open)}${json}${html.slice(i + 1)}`
      }
    }
  }
  throw new FeuilleError('`const DATA =` 的字面量没有闭合')
}

// ============================================================
//  状态帧渲染
// ============================================================

/** 一个场景的渲染产物。 */
export interface RenderedScene {
  id: string
  /** 每段的 PNG 路径（顺序：preroll → states → done）。 */
  frames: string[]
  /** 每段的帧数（与 frames 等长）。 */
  frameCounts: number[]
  /** 场景总帧数。 */
  totalFrames: number
  /** 场景总时长（秒）。 */
  durationSec: number
}

function browserBin(): string {
  const b = platform.browserPath()
  if (!b) throw new FeuilleError('找不到 Chromium 系浏览器；装 Chrome 或 Edge，或设 CHROME_BIN')
  return b
}

/**
 * 截一张状态帧。
 *
 * 旗标照抄 skills/music-annotate-video/references/headless-render.md：
 * --headless=new（不抢已开着的桌面浏览器）、--disable-gpu、钥匙串隔离、
 * 1x 缩放、隐藏滚动条、virtual-time-budget、精确 window-size。
 * **不带 --user-data-dir**（macOS + Edge 实测进程永不退出）。
 */
export function shootState(
  browser: string,
  htmlPath: string,
  scene: string,
  state: number,
  ph: number | null,
  outPng: string,
  w: number,
  h: number,
): void {
  const url = new URL(pathToFileURL(resolve(htmlPath)).href)
  url.searchParams.set('scene', scene)
  url.searchParams.set('state', String(state))
  if (ph !== null) url.searchParams.set('ph', ph.toFixed(3))
  // 画幅：由**截图尺寸**推出，不另外传参。竖版是 h > w，横版是 w > h。
  // 为什么不加一个独立的 --fmt：画幅已经在 --width/--height 里表达了一遍，
  // 再传一次就是两处事实源，必有一处会漂（纪律 7/10）。模板按这个参数切
  // CSS 变量与排版，不靠媒体查询（headless 下媒体查询宽度未必等于 PNG 尺寸）。
  url.searchParams.set('fmt', h > w ? 'v' : 'h')
  sh([browser,
    '--headless=new', '--disable-gpu', ...platform.HEADLESS_FLAGS,
    '--force-device-scale-factor=1', '--hide-scrollbars',
    '--virtual-time-budget=10000', `--window-size=${w},${h}`,
    `--screenshot=${resolve(outPng)}`, url.toString()], 180)
  if (!existsSync(outPng)) {
    throw new FeuilleError(`浏览器退出 0 但没写出 ${outPng}——大概率被已开着的桌面浏览器`
      + `抢占（singleton 移交）。关掉桌面浏览器后重试。\nURL was: ${url.toString()}`)
  }
}

/** 一个场景的时间模型。 */
export interface SceneTiming {
  preroll: number
  body: number
  done: number
  tail: number
  /** 场景总帧数（一次算定）。 */
  totalFrames: number
  /** 场景总时长（秒）。 */
  durationSec: number
}

/** 算场景的时间模型。 */
export function sceneTiming(scene: Scene, fps: number): SceneTiming {
  const preroll = scene.preroll ?? 0.8
  const done = scene.done ?? 0.5
  const tail = scene.tail ?? 0.8
  const body = scene.states.reduce((a, s) => a + Math.max(0, s.t1 - s.t0), 0)
  const totalFrames = framesFor(preroll + body + done + tail, fps)
  return { preroll, body, done, tail, totalFrames, durationSec: totalFrames / fps }
}

// ============================================================
//  装配
// ============================================================

/** 装配结果。 */
export interface BuildResult {
  outPath: string
  /** 逐场景对账（视频总帧数 vs 预期帧数）。 */
  reconciliation: Array<{ scene: string; expectedFrames: number; actualFrames: number; diff: number }>
  /** 总时长（秒，ffprobe 实测）。 */
  durationSec: number
  /** 双流时长差（毫秒）。 */
  avDiffMs: number
}

/**
 * 渲染 + 装配一条影片。
 *
 * `creditPass`：制作信息页的两段式。
 *   - pass 1（creditPass='placeholder'）：卡上写占位文字，先把片长定死；
 *   - pass 2（creditPass='final'）：用实测数字重渲同一段、重新拼接。
 *   **卡长在 pass 1 之前就定死**（8.0s），回填只改内容不改帧数——否则
 *   总时长变 → 数字变 → 再变，永远不收敛（traps §11）。
 */
export function buildProject(
  project: MusicProject,
  root: string,
  outPath: string,
  opts: { creditPass?: 'placeholder' | 'final'; width?: number; height?: number } = {},
): BuildResult {
  const fps = project.fps ?? 30
  const w = opts.width ?? 1920
  const h = opts.height ?? 1080
  const browser = browserBin()
  const workDir = join(root, 'build')
  const framesDir = join(workDir, 'frames')
  mkdirSync(framesDir, { recursive: true })
  mkdirSync(dirname(outPath), { recursive: true })

  // ---- 页面：状态帧页注入 DATA；制作信息页用 credit.html ----
  const htmlPath = join(root, project.status_frame_html)
  if (!existsSync(htmlPath)) throw new FeuilleError(`找不到状态帧页面：${htmlPath}`)
  const dataByScene: Record<string, unknown> = {}
  for (const s of project.scenes) {
    if (s.data) dataByScene[s.id] = s.data
  }
  const injectedPath = join(workDir, 'status-frame.html')
  writeFileSync(injectedPath, injectData(readFileSync(htmlPath, 'utf8'), dataByScene), 'utf8')

  const creditScene = project.scenes.find((s) => s.credit)
  // 制作信息页**由 facts/sources 生成**，落在 workDir/credit.html；
  // 渲染时必须用**这一份**。第一版把生成物写到 workDir/credit.html，
  // 却让渲染去读 project.credit_html 指向的文件——于是「回填实测数字后
  // 重渲」这一遍重渲的还是老页面，两段式形同虚设。
  const creditHtmlPath = creditScene ? join(workDir, 'credit.html') : null
  if (creditScene) {
    // 制作信息页单独渲染：内容由 facts.json 回填（pass 2 才有实测数字）
    const factsPath = join(root, project.credit?.facts ?? 'facts.json')
    if (!existsSync(factsPath)) {
      throw new FeuilleError(
        `制作信息页要读 ${factsPath}，但它不存在——`
        + '交付信息页不许缺（facts.json 记的是实测数字，不是可选项）',
      )
    }
    const facts = readFileSync(factsPath, 'utf8')
    const sourcesPath = join(root, project.credit?.sources ?? 'sources.json')
    const sources = existsSync(sourcesPath)
      ? readFileSync(sourcesPath, 'utf8')
      : '{}'
    writeFileSync(
      join(workDir, 'credit.html'),
      renderCreditHtml(
        JSON.parse(facts), JSON.parse(sources),
        opts.creditPass ?? 'placeholder', { width: w, height: h },
      ),
      'utf8',
    )
  }

  // ---- 逐场景渲染 + 编码 ----
  const segVideo: string[] = []
  const segAudio: string[] = []
  const reconciliation: BuildResult['reconciliation'] = []
  let totalFrames = 0
  let masterStartSec = 0

  for (const scene of project.scenes) {
    const t = sceneTiming(scene, fps)
    const isCredit = !!scene.credit
    const targetHtml = isCredit && creditHtmlPath ? creditHtmlPath : injectedPath
    const prefix = join(framesDir, scene.id)

    // 段清单：preroll（state -1）→ 各 state → done（state N）
    const pngs: string[] = []
    const durations: number[] = []
    const playheads: (number | null)[] = []

    const pre = join(prefix + '-pre.png')
    shootState(browser, targetHtml, scene.id, -1, null, pre, w, h)
    pngs.push(pre)
    durations.push(t.preroll)
    playheads.push(null)

    for (let i = 0; i < scene.states.length; i++) {
      const st = scene.states[i]!
      const png = join(prefix + `-s${String(i).padStart(3, '0')}.png`)
      // 播放头默认取本状态的中点：state 是一段静止画面，取中点才有「已播罩亮」
      // 的信息量（取起点等于画面刚进入、罩亮为 0）。state 可以显式给
      // playhead_s（引子段用：音乐还没进，播放头必须停在 0）。
      const ph = st.playhead_s ?? (st.t0 + st.t1) / 2
      shootState(browser, targetHtml, scene.id, i, ph, png, w, h)
      pngs.push(png)
      durations.push(st.t1 - st.t0)
      playheads.push(ph)
    }

    const donePng = join(prefix + '-done.png')
    shootState(browser, targetHtml, scene.id, scene.states.length, null, donePng, w, h)
    pngs.push(donePng)
    durations.push(t.done)
    playheads.push(null)

    // 帧数分配：各段按自己的时长取整，**最后一段吸收舍入余数**
    const counts = durations.map((d) => framesFor(d, fps))
    const used = counts.reduce((a, b) => a + b, 0)
    const last = counts.length - 1
    counts[last] = counts[last]! + (t.totalFrames - used)
    if (counts[last]! < 0) {
      throw new FeuilleError(
        `场景 ${scene.id}：段时长合计 ${used} 帧已超过场景总帧数 ${t.totalFrames}——`
        + `states 的时长之和与 preroll/done/tail 口径不一致`)
    }

    // 视频段：逐段按精确帧数编码，再流拷贝拼接
    const sceneVideo = join(workDir, `_v_${scene.id}.mp4`)
    const partFiles: string[] = []
    for (let i = 0; i < pngs.length; i++) {
      const n = counts[i]!
      // **零帧的段不编码**：片头卡这类场景的 preroll/done 是 0 秒，
      // 编码出来的 mp4 是空的（无视频流），后面 concat 会报
      // 「Output file does not contain any stream」——第一版就这样炸的。
      if (n <= 0) continue
      const part = join(workDir, `_v_${scene.id}_${String(i).padStart(3, '0')}.mp4`)
      sh([ffmpegBin(), '-y', '-loglevel', 'error', '-loop', '1', '-framerate', fps,
        '-i', pngs[i]!, '-t', (n / fps).toFixed(6), '-frames:v', n,
        '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'medium',
        '-crf', '18', part])
      partFiles.push(part)
    }
    const listFile = join(workDir, `_v_${scene.id}.txt`)
    writeFileSync(listFile, partFiles.map((p) => `file '${p}'\n`).join(''), 'utf8')
    sh([ffmpegBin(), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
      '-i', listFile, '-c:v', 'copy', sceneVideo])
    segVideo.push(sceneVideo)
    totalFrames += t.totalFrames

    // 音频段：场景摘录或母版轨 + 旁白期 ducking + 聆听段全电平
    const sceneAudio = join(workDir, `_a_${scene.id}.wav`)
    buildSceneAudio(project, scene, root, sceneAudio, t.durationSec, masterStartSec)
    masterStartSec += t.durationSec
    segAudio.push(sceneAudio)

    reconciliation.push(reconcileVideoFrames(scene.id, t.totalFrames, sceneVideo))
  }

  // ---- 拼接 ----
  const vList = join(workDir, 'concat_v.txt')
  const aList = join(workDir, 'concat_a.txt')
  writeFileSync(vList, segVideo.map((p) => `file '${p}'\n`).join(''), 'utf8')
  writeFileSync(aList, segAudio.map((p) => `file '${p}'\n`).join(''), 'utf8')
  const vNoAudio = join(workDir, 'video_noaudio.mp4')
  const aAll = join(workDir, 'audio_all.wav')
  sh([ffmpegBin(), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
    '-i', vList, '-c:v', 'copy', vNoAudio])
  sh([ffmpegBin(), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
    '-i', aList, '-c:a', 'pcm_s16le', aAll])

  // 终混 loudnorm 必须在流长锁死之后（改了流长，前面所有对账都作废）
  const loud = project.audio?.loudness ?? {}
  const I = loud.I ?? -14
  const TP = loud.TP ?? -1.5
  const LRA = loud.LRA ?? 11
  // 终混要**按帧数显式裁长**：loudnorm 会把音频拉长一点点（实测 +66.7ms，
  // 因为它内部重采样到 192kHz 再回来），两流就不等长了——声画会漂。
  // 目标时长取**视频帧数 ÷ fps**，不是 ffprobe 读回来的时长（后者已被
  // 拉长的音频带偏）。
  const targetSec = totalFrames / fps
  sh([ffmpegBin(), '-y', '-loglevel', 'error',
    '-i', vNoAudio, '-i', aAll,
    '-filter_complex',
    `[1:a]loudnorm=I=${I}:TP=${TP}:LRA=${LRA}[aout]`,
    '-map', '0:v', '-map', '[aout]', '-c:v', 'copy',
    '-t', targetSec.toFixed(6),
    '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', outPath])

  const durationSec = probeDuration(outPath)
  const avDiffMs = streamDiffMs(outPath)
  return { outPath, reconciliation, durationSec, avDiffMs }
}

function ffmpegBin(): string {
  return platform.requireTool(platform.ffmpeg(), 'ffmpeg')
}

function ffprobeBin(): string {
  return platform.requireTool(platform.ffprobe(), 'ffprobe')
}

/** ffprobe 取容器时长。 */
export function probeDuration(path: string): number {
  const r = spawnSync(ffprobeBin(), [
    '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path,
  ], { encoding: 'utf8' })
  if (r.status !== 0) throw new FeuilleError(`ffprobe 失败：${path}\n${(r.stderr ?? '').slice(-500)}`)
  return Number.parseFloat(r.stdout.trim())
}

/** 独立解码并数出视频流实际帧数。 */
export function probeVideoFrames(path: string): number {
  const r = spawnSync(ffprobeBin(), [
    '-v', 'error', '-count_frames', '-select_streams', 'v:0',
    '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', path,
  ], { encoding: 'utf8' })
  if (r.status !== 0) throw new FeuilleError(`ffprobe 数帧失败：${path}\n${(r.stderr ?? '').slice(-500)}`)
  const frames = Number.parseInt(r.stdout.trim(), 10)
  if (!Number.isFinite(frames) || frames < 0) {
    throw new FeuilleError(`ffprobe 没返回有效帧数：${path}（${r.stdout.trim()}）`)
  }
  return frames
}

/** 用编码产物的实测帧数做逐场景对账。 */
export function reconcileVideoFrames(
  scene: string,
  expectedFrames: number,
  sceneVideo: string,
): BuildResult['reconciliation'][number] {
  const actualFrames = probeVideoFrames(sceneVideo)
  return { scene, expectedFrames, actualFrames, diff: actualFrames - expectedFrames }
}

/** 视频流与音频流的时长差（毫秒）。 */
export function streamDiffMs(path: string): number {
  const r = spawnSync(ffprobeBin(), [
    '-v', 'error', '-show_entries', 'stream=codec_type,duration', '-of', 'json', path,
  ], { encoding: 'utf8' })
  if (r.status !== 0) throw new FeuilleError(`ffprobe 失败：${path}`)
  const data = JSON.parse(r.stdout) as { streams?: Array<{ codec_type?: string; duration?: string }> }
  let v = 0
  let a = 0
  for (const s of data.streams ?? []) {
    const d = Number.parseFloat(s.duration ?? '0')
    if (s.codec_type === 'video') v = d
    else if (s.codec_type === 'audio') a = d
  }
  return Math.abs(v - a) * 1000
}

/**
 * 造一个场景的音频段（长度精确等于场景时长）。
 *
 * 音频图：
 *   场景音乐轨：录音摘录 → adelay 到场景内落点 → 旁白期 ducking。
 *   母版音频轨：有 audio.tracks[] 时取代场景摘录，按 masterStartSec 切当前
 *               场景，并把母版绝对秒 envelope 平移成场景内秒。
 *   旁白轨：各 mp3 → adelay 到 at_s → volume gain
 *   混合：amix normalize=0（保住人声电平）→ apad → -t 场景时长
 */
export function buildSceneAudio(
  project: MusicProject,
  scene: Scene,
  root: string,
  outWav: string,
  durationSec: number,
  masterStartSec = 0,
): void {
  const FF = ffmpegBin()
  const musicGain = project.audio?.ducking?.music_gain ?? 0.25
  const inputs: string[] = []
  const filters: string[] = []

  const globalTracks = project.audio?.tracks ?? []
  const musicAt = scene.music_at ?? scene.preroll ?? 0.8
  // 母版轨已经表达整条音乐床；再叠加场景摘录会把同一录音混两遍。
  const ex = globalTracks.length === 0 ? scene.recording_excerpt : undefined
  if (ex) {
    // 场景自带录音文件优先（多乐章作品），否则用项目级那一份。
    const recFile = scene.recording_file ?? project.recording.file
    inputs.push('-i', resolve(root, recFile))
    const delayMs = Math.trunc(musicAt * 1000)
    // ducking 窗口：旁白出声的区间（场景内秒）
    const windows = (scene.narration ?? [])
      .map((n) => {
        const dur = probeDuration(resolve(root, n.file))
        return [n.at_s, n.at_s + dur] as const
      })
      .filter(([a, b]) => b > a)
    const expr = windows.length
      ? `if(${windows.map(([a, b]) => `between(t,${a.toFixed(3)},${b.toFixed(3)})`).join('+')},${musicGain},1)`
      : '1'
    filters.push(
      `[0:a]atrim=start=${ex.start_s.toFixed(3)}:end=${ex.end_s.toFixed(3)},`
      + `asetpts=PTS-STARTPTS,adelay=${delayMs}:all=1,`
      + `volume=volume='${expr}':eval=frame[m]`,
    )
  }

  const globalInputs: string[] = []
  for (let i = 0; i < globalTracks.length; i++) {
    const track = globalTracks[i]!
    inputs.push('-i', resolve(root, track.file))
    const idx = inputs.length / 2 - 1
    const sourceStart = (track.offset_s ?? 0) + masterStartSec
    const sourceEnd = sourceStart + durationSec
    const expression = (track.envelope ?? [])
      .filter((w) => w.to_s > w.from_s)
      .reduceRight((fallback, w) => {
        const from = w.from_s - masterStartSec
        const to = w.to_s - masterStartSec
        return `if(between(t,${from.toFixed(3)},${to.toFixed(3)}),${w.gain},${fallback})`
      }, '1')
    filters.push(
      `[${idx}:a]atrim=start=${sourceStart.toFixed(6)}:end=${sourceEnd.toFixed(6)},`
      + `asetpts=PTS-STARTPTS,volume=volume='${expression}':eval=frame[g${i}]`,
    )
    globalInputs.push(`[g${i}]`)
  }

  const nars = scene.narration ?? []
  const nInputs: string[] = []
  for (let i = 0; i < nars.length; i++) {
    const n = nars[i]!
    inputs.push('-i', resolve(root, n.file))
    const idx = inputs.length / 2 - 1
    const delayMs = Math.trunc(n.at_s * 1000)
    filters.push(
      `[${idx}:a]adelay=${delayMs}:all=1,volume=${n.gain ?? 1.0}[n${i}]`,
    )
    nInputs.push(`[n${i}]`)
  }

  const mixInputs = [...(ex ? ['[m]'] : []), ...globalInputs, ...nInputs]
  const nMix = mixInputs.length
  if (nMix === 0) {
    // 没有音乐也没有旁白 → 纯静音（不能拼出 inputs=0 的 amix）
    sh([FF, '-y', '-loglevel', 'error', '-f', 'lavfi',
      '-i', 'anullsrc=r=48000:cl=stereo', '-t', durationSec.toFixed(6), outWav], 300)
    return
  }
  // **apad 必须写进 filter_complex，不能用裸 `-apad` 输出选项**——
  // ffmpeg 6.1 实测：裸 `-apad` 会把下一个参数当成自己的值吃掉
  // （`-apad -t 4.5` → `-apad` 吞掉 `-t`，`4.5` 被当成输出文件名）。
  // 而 `-af apad` 又与 `-filter_complex` 冲突（同一路流不能同时用简单/复杂过滤）。
  filters.push(
    `${mixInputs.join('')}amix=inputs=${nMix}:duration=longest:normalize=0[amx]`,
  )
  filters.push('[amx]apad[am]')

  sh([FF, '-y', '-loglevel', 'error', ...inputs,
    '-filter_complex', filters.join(';'),
    '-map', '[am]', '-t', durationSec.toFixed(6),
    '-ar', '48000', '-ac', '2', outWav], 900)
}

// ============================================================
//  制作信息页（两段式）
// ============================================================

/**
 * 渲染制作信息页 HTML。
 *
 * pass 1（placeholder）：卡上写「见成片 ffprobe / 渲染完成后回填」这类
 * **占位字样**——它必须显眼到「不可能被误当成品」，但也必须在 pass 2
 * 被完全替换掉（validate-facts 的交付模式会拒收含 `{{…}}` 的成片）。
 * pass 2（final）：用实测数字重渲同一段；**卡长不变**。
 */
export function renderCreditHtml(
  facts: Record<string, unknown>,
  sources: Record<string, unknown>,
  pass: 'placeholder' | 'final',
  size: { width?: number; height?: number } = {},
): string {
  const w = size.width ?? 1920
  const h = size.height ?? 1080
  // 画幅跟着截图尺寸走。写死 1920×1080 时竖版截图会得到「1080 宽视口里一张
  // 1920 宽的页」——右半边被裁掉，看着像字段缺失（实测）。竖版还要把两栏
  // 改成一栏、字号上一档：1080 宽塞两栏时每栏 470px，19px 的行会频繁折行。
  const vertical = h > w
  const L: string[] = []
  L.push(`<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">`)
  L.push(`<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body { width:${w}px; height:${h}px; overflow:hidden; background:#f7f2e6; }
  body { color:#2c2620; font-family: Georgia,"Noto Serif CJK SC","Source Han Serif SC",serif;
         padding:${vertical ? '96px 56px' : '56px 84px'}; display:flex; flex-direction:column; }
  .k { font-size:${vertical ? 24 : 24}px; letter-spacing:.5em; color:#b8860b; margin-bottom:18px; }
  h1 { font-size:${vertical ? 54 : 44}px; font-weight:600; margin-bottom:24px; }
  .cols { display:flex; flex-direction:${vertical ? 'column' : 'row'};
          gap:${vertical ? 36 : 56}px; flex:1; min-height:0; }
  .col { flex:1; min-width:0; }
  h2 { font-size:${vertical ? 30 : 24}px; color:#8a7e6c; margin-bottom:12px; font-weight:600; }
  .row { font-size:${vertical ? 26 : 19}px; line-height:1.5; color:#5a5142; margin-bottom:9px; }
  .row b { color:#2c2620; }
  .foot { margin-top:auto; padding-top:14px; border-top:1px solid #d9cdb7;
          font-size:${vertical ? 22 : 17}px; color:#8a7e6c; }
  </style></head><body>`)

  if (pass === 'placeholder') {
    L.push(`<div class="k">PRODUCTION NOTES</div>`)
    L.push(`<h1>制作信息（占位 · 本片尚未回填）</h1>`)
    L.push(`<div class="cols"><div class="col">`)
    L.push(`<div class="row">时长：见成片 ffprobe（渲染完成后回填）</div>`)
    L.push(`<div class="row">摘录清单：渲染完成后回填</div>`)
    L.push(`<div class="row">来源与许可：渲染完成后回填</div>`)
    L.push(`</div><div class="col"><div class="row">这一页在第二遍重渲时被完全替换。</div>`)
    L.push(`</div></div>`)
    L.push(`<div class="foot">Music Annotate Video · placeholder pass</div>`)
  } else {
    const work = (facts['work'] ?? {}) as Record<string, unknown>
    const excerpts = (facts['excerpts'] ?? []) as Array<Record<string, unknown>>
    const items = ((sources as { items?: unknown[] }).items ?? []) as Array<Record<string, unknown>>
    L.push(`<div class="k">PRODUCTION NOTES</div>`)
    L.push(`<h1>制作信息</h1>`)
    L.push(`<div class="cols"><div class="col">`)
    L.push(`<h2>作品</h2>`)
    L.push(`<div class="row"><b>${esc(String(work['title'] ?? ''))}</b>${work['composer'] ? ' · ' + esc(String(work['composer'])) : ''}</div>`)
    if (work['movements'] !== undefined) L.push(`<div class="row">乐章数：${esc(String(work['movements']))}</div>`)
    if (facts['duration_s'] !== undefined) L.push(`<div class="row">成片时长：${esc(String(facts['duration_s']))} 秒</div>`)
    if (facts['excerpt_count'] !== undefined) L.push(`<div class="row">摘录段数：${esc(String(facts['excerpt_count']))}</div>`)
    if (facts['excerpt_ratio'] !== undefined) L.push(`<div class="row">选段总长 / 全曲时长：${esc(String(facts['excerpt_ratio']))}</div>`)
    L.push(`</div><div class="col">`)
    L.push(`<h2>摘录清单</h2>`)
    for (const e of excerpts) {
      L.push(`<div class="row">${esc(String(e['label'] ?? ''))}：`
        + `${esc(String(e['start_s'] ?? ''))}s → ${esc(String(e['end_s'] ?? ''))}s`
        + (e['why'] ? `（${esc(String(e['why']))}）` : '') + `</div>`)
    }
    L.push(`<h2>来源与许可</h2>`)
    for (const it of items) {
      L.push(`<div class="row"><b>${esc(String(it['title'] ?? ''))}</b> · `
        + `${esc(String(it['license'] ?? ''))} · ${esc(String(it['attribution'] ?? ''))}</div>`)
    }
    L.push(`</div></div>`)
    L.push(`<div class="foot">Music Annotate Video · ${esc(String(facts['generated_at'] ?? ''))}</div>`)
  }
  L.push(`</body></html>`)
  return L.join('\n')
}

function esc(s: string): string {
  return s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

/** 把「秒」格式化成 mm:ss。 */
export function fmtTime(sec: number): string {
  const s = Math.max(0, Math.round(sec))
  const m = Math.floor(s / 60)
  return `${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

/** 网格吸附的再导出（供调用方核对帧数时用）。 */
export { snapToGrid }

// ============================================================
//  CLI：feuille music build
// ============================================================

/**
 * `feuille music build <project.json> [--out <out.mp4>] [--credit-pass placeholder|final]`
 *
 * 产出：成片 mp4 + `build/` 下的分段产物 + 终端里的逐场景对账表。
 *
 * **两段式**：`--credit-pass placeholder` 先出占位信息页并把片长定死；
 * 成片出来后用实测数字回填，再跑一次 `--credit-pass final`——**卡长不变**
 * （否则总时长变 → 数字变 → 再变，永远不收敛）。
 */
export async function main(argv: string[]): Promise<number> {
  const args = parseArgs(argv)
  const cfgPath = args.positional[0]
  if (!cfgPath) {
    console.error('usage: feuille music build <project.json> [--out <out.mp4>] [--credit-pass placeholder|final]')
    return 2
  }
  const project = JSON.parse(readFileSync(cfgPath, 'utf8')) as MusicProject
  const root = resolve(cfgPath, '..')
  const pass = (args.opts['credit-pass'] === 'final' ? 'final' : 'placeholder') as
    'placeholder' | 'final'
  const outPath = resolve(root, args.opts['out'] ?? 'out.mp4')

  const result = buildProject(project, root, outPath, {
    creditPass: pass,
    width: numOpt(args, 'width', 1920),
    height: numOpt(args, 'height', 1080),
  })

  console.log(`build: ${outPath}`)
  for (const r of result.reconciliation) {
    const flag = r.diff === 0 ? 'ok' : `MISMATCH(${r.diff})`
    console.log(`  场景 ${r.scene}: 期望 ${r.expectedFrames} 帧 / 实际 ${r.actualFrames} 帧  ${flag}`)
  }
  const bad = result.reconciliation.filter((r) => r.diff !== 0)
  console.log(`  时长 ${result.durationSec.toFixed(3)}s · 双流差 ${result.avDiffMs.toFixed(1)}ms`)
  if (bad.length) {
    console.error(`  逐场景对账未过：${bad.length} 个场景差帧——不许当「差不多」读。`)
    return 1
  }
  if (result.avDiffMs > 50) {
    console.error(`  双流差 ${result.avDiffMs.toFixed(1)}ms > 50ms——声画会漂。`)
    return 1
  }
  return 0
}
