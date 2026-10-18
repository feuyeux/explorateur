// compose.test.ts — 母版叠加合成的反向验证（verify_compose.py 的 TS 移植）。
//
// 纯函数层：滤镜图要素（缩放/逐层 overlay enable/配乐压低/人声补齐/终混
// loudnorm）、坑③口径（所有 apad 都在 loudnorm 之前）、坑⑯口径（mux 命令里
// 没有 -shortest，时长控制显式交给 -t）。
//
// 真机 smoke（有 ffmpeg 时）：3s 灰底「母版」+ 1s 人声 + 一块红色文字层
// （enable 1.0–2.0s）→ 成片恰好 dur；t=0.5s 的帧无红、t=1.5s 的帧是红
// ——enable='between' 真生效，不是只看命令拼对。
import { execFileSync, spawnSync } from "node:child_process"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { afterEach, describe, expect, it } from "vitest"

import sharp from "sharp"

import { composeTrack, probeDuration } from "../src/audio.js"
import { filterGraph, lineSpans, mux } from "../src/compose.js"
import { platform } from "../src/index.js"

const FFMPEG = platform.ffmpeg()
const FFPROBE = platform.ffprobe()
const composeSrc = readFileSync(
  fileURLToPath(new URL("../src/compose.ts", import.meta.url)), "utf8")

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-compose-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
})

describe("好数据放行：line_spans 口径", () => {
  it("行区间：不重叠、尾行留 hold", () => {
    const spans = lineSpans([0.0, 1.0, 2.5], [0.8, 0.8, 0.8], { total: 4.0, hold: 0.3 })
    expect(spans).toEqual([[0.0, 1.0], [1.0, 2.1], [2.5, 3.6]])
  })
})

describe("滤镜图要素", () => {
  const [graph, vlabel] = filterGraph(1080, 1920, 2, 15.0)

  it("视频末段标签正确（v1）", () => {
    expect(vlabel).toBe("v1")
  })

  it("两层层级齐全（缩放→逐层 overlay→配乐压低→人声补齐→终混）", () => {
    for (const x of [
      "[0:v]scale=1080:1920:flags=lanczos,fps=24[base]",
      "overlay=0:{y}:enable='between(t,{between})'", "[v0]",
      "[0:a]volume=0.3[bg]",
      "apad=whole_dur=15.000,atrim=0:15.000",
      "amix=inputs=2:normalize=0,loudnorm=I=-14",
    ]) {
      expect(graph).toContain(x)
    }
  })

  it("零 overlay 时末段是 [base]", () => {
    const [, v0] = filterGraph(100, 100, 0, 10.0)
    expect(v0).toBe("base")
  })

  it("坑③口径：所有 apad 都在 loudnorm 之前（后置是实测的非确定竞态）", () => {
    expect(graph.indexOf("apad=whole_dur")).toBeLessThan(graph.indexOf("loudnorm"))
  })
})

describe("坑⑯口径：mux 命令不含 -shortest，时长显式交给 -t", () => {
  // 与 Python inspect.getsource(compose.mux) 同范围：只看 mux 函数体，
  // 模块头的「禁用 -shortest」纪律描述不在判据内
  const src = composeSrc.slice(composeSrc.indexOf("export function mux"))
    .replace("// -shortest 已废（坑⑯，见模块头）：时长控制显式交给 -t", "")
  it("mux 源码里没有 -shortest", () => {
    expect(src).not.toContain("-shortest")
  })
  it("时长控制显式 -t dur（.3f 定点）", () => {
    expect(src).toContain('"-t", opts.dur.toFixed(3)')
  })
})

describe.skipIf(FFMPEG === null || FFPROBE === null)("真机 smoke：红块 overlay 的 enable 生效", () => {
  // 整趟 smoke 一个测试自建自验（与 verify_compose 单趟同构）：
  // 文件级 afterEach 会在每个测试后清掉已注册的临时根，跨测试共享夹具
  // 会被前一个测试的 afterEach 提前删掉。
  it("3s 灰底母版 + 1s 人声 + 红块文字层（enable 1.0–2.0）→ dur/帧色/音轨全对", async () => {
    const d = tmp()
    const master = join(d, "master.mp4")
    const voice = join(d, "voice.m4a")
    const ov = join(d, "ov.png")
    const out = join(d, "out.mp4")
    // 母版是测试夹具（双 lavfi 输入都是定长 3s），不属封装命令纪律管辖
    const r = spawnSync(FFMPEG!, [
      "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=320x240:d=3.0",
      "-f", "lavfi", "-i", "sine=frequency=440:duration=3.0",
      "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
      "-c:a", "aac", "-shortest", master,
    ])
    if (r.status !== 0) throw new Error(`造母版失败：${r.stderr}`)
    // 人声轨：1s 正弦 → compose_track 补齐到 3.0s（坑③口径的轨道级处理）
    const voiceIn = join(d, "v.mp3")
    const rv = spawnSync(FFMPEG!, ["-y", "-f", "lavfi", "-i", "sine=frequency=660:duration=1", voiceIn])
    if (rv.status !== 0) throw new Error(`造人声失败：${rv.stderr}`)
    composeTrack([voiceIn], [0.0], 3.0, voice)
    // 红块文字层（全幅红，y=0）
    await sharp({
      create: { width: 320, height: 240, channels: 4, background: { r: 255, g: 0, b: 0, alpha: 255 } },
    }).png().toFile(ov)

    mux(master, voice, [{ png: ov, y: 0, t0: 1.0, t1: 2.0 }], out, {
      w: 320, h: 240, dur: 3.0, preset: "veryfast",
    })
    // 成片恰好 dur（-t 显式裁齐，非 -shortest 的时机性取舍）
    const dur = probeDuration(out)
    expect(Math.abs(dur - 3.0)).toBeLessThanOrEqual(0.12)

    // t=1.5 的帧是红——enable='between' 真生效，不是只看命令拼对
    async function frameMean(t: string): Promise<{ r: number; g: number }> {
      const png = join(d, `f_${t}.png`)
      execFileSync(FFMPEG!, ["-y", "-ss", t, "-i", out, "-frames:v", "1", png])
      const { data, info } = await sharp(png).removeAlpha().raw()
        .toBuffer({ resolveWithObject: true })
      let r = 0, g = 0
      for (let i = 0; i < info.width * info.height; i++) {
        r += data[i * info.channels]!
        g += data[i * info.channels + 1]!
      }
      const n = info.width * info.height
      return { r: r / n, g: g / n }
    }
    const on = await frameMean("1.5")
    expect(Math.abs(on.r - 255)).toBeLessThan(20)
    expect(on.g).toBeLessThan(60)
    const off = await frameMean("0.5")
    expect(Math.abs(off.r - 128)).toBeLessThan(12)

    // 音轨存在且为 aac（双声道终混）
    const probe = execFileSync(
      FFPROBE!,
      ["-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name",
        "-of", "csv=p=0", out],
      { encoding: "utf8" }).trim()
    expect(probe.startsWith("aac")).toBe(true)
  })
})
