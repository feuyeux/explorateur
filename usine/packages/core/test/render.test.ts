// render.test.ts — 帧编码基座的契约验证（render.py 的 TS 移植）。
//
// encode_frames 在 Python 侧没有独立 verify 脚本（由 compose/rig 间接覆盖），
// 这里把它的硬约定直接钉成断言：raw rgb24 管道、显式 -t 时长、帧不足不补、
// 非零退出抛错、坏帧不静默错位（防御直喂的字节流错位检查）。
import { execFileSync } from "node:child_process"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { afterEach, describe, expect, it } from "vitest"

import sharp from "sharp"

import { probeDuration } from "../src/audio.js"
import { platform } from "../src/index.js"
import { encodeFrames } from "../src/render.js"

const FFMPEG = platform.ffmpeg()
const FFPROBE = platform.ffprobe()
const renderSrc = readFileSync(
  fileURLToPath(new URL("../src/render.ts", import.meta.url)), "utf8")

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-render-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
})

const W = 320, H = 240, FPS = 24

function solidFrame(r: number, g: number, b: number): Buffer {
  const buf = Buffer.alloc(W * H * 3)
  for (let i = 0; i < W * H; i++) {
    buf[i * 3] = r
    buf[i * 3 + 1] = g
    buf[i * 3 + 2] = b
  }
  return buf
}

async function* framesOf(buffers: Buffer[], delay = 0): AsyncIterable<Buffer> {
  for (const b of buffers) {
    yield b
    if (delay) await new Promise((res) => setTimeout(res, delay))
  }
}

describe("源级口径：不依赖 ffmpeg 就能断言的纪律", () => {
  it("命令不含 -shortest（坑⑯：时机性丢帧开关），时长显式 -t", () => {
    const src = renderSrc.replace(
      "// 禁用 -shortest：EOF 冲刷时按已入队包随时机丢视频帧（实测高并发批量下", "")
      .replace("// 丢帧、单渲不丢 → framehash 幂等必挂）。纯视频管道，-t dur 是唯一时长开关。", "")
      .replace("不用 `-shortest`", "")
      .replace("- 不用 `-shortest`——它是时机性丢帧开关", "")
    expect(src).not.toContain("-shortest")
    expect(renderSrc).toContain('"-t", String(dur)')
  })
})

describe.skipIf(FFMPEG === null || FFPROBE === null)("真机 rawvideo 管道", () => {
  it("72 帧全红 320×240 @24fps → 喂帧数 72、成片 ≈3.0s、帧确为红", async () => {
    const d = tmp()
    const out = join(d, "out.mp4")
    const n = await encodeFrames(
      framesOf(Array.from({ length: 72 }, () => solidFrame(200, 30, 30))),
      out, { w: W, h: H, fps: FPS, dur: 3.0, preset: "veryfast" },
    )
    expect(n).toBe(72)
    expect(Math.abs(probeDuration(out) - 3.0)).toBeLessThanOrEqual(0.12)
    // 帧像素确证字节流没错位：抽 t=1.0 一帧应仍是纯红
    const png = join(d, "f.png")
    execFileSync(FFMPEG!, ["-y", "-ss", "1.0", "-i", out, "-frames:v", "1", png])
    const { data, info } = await sharp(png).removeAlpha().raw()
      .toBuffer({ resolveWithObject: true })
    let r = 0
    for (let i = 0; i < info.width * info.height; i++) r += data[i * info.channels]!
    expect(Math.abs(r / (info.width * info.height) - 200)).toBeLessThan(25)
  })

  it("sharp 实例帧自动转 RGB（防御直喂 RGBA 错位）", async () => {
    const d = tmp()
    const out = join(d, "out.mp4")
    async function* sharpFrames(): AsyncIterable<ReturnType<typeof sharp>> {
      for (let i = 0; i < 24; i++) {
        yield sharp({ create: { width: W, height: H, channels: 4, background: { r: 0, g: 128, b: 0, alpha: 255 } } })
      }
    }
    const n = await encodeFrames(sharpFrames(), out, { w: W, h: H, fps: FPS, dur: 1.0, preset: "veryfast" })
    expect(n).toBe(24)
    expect(Math.abs(probeDuration(out) - 1.0)).toBeLessThanOrEqual(0.12)
  })

  it("帧字节长度不符 → 显式抛错（不静默错位；契约：调用方供足 ⌈dur×fps⌉ 帧）", async () => {
    const d = tmp()
    const out = join(d, "bad.mp4")
    async function* bad(): AsyncIterable<Buffer> {
      yield solidFrame(0, 0, 0)
      yield Buffer.alloc(W * H * 3 - 3) // 错尺寸帧
    }
    await expect(encodeFrames(bad(), out, { w: W, h: H, fps: FPS, dur: 1.0, preset: "veryfast" }))
      .rejects.toThrow("rawvideo")
  })

  it("帧不足 → rc 0、产物短于 dur 且不补（无静默补帧契约）", async () => {
    const d = tmp()
    const out = join(d, "short.mp4")
    const n = await encodeFrames(
      framesOf(Array.from({ length: 24 }, () => solidFrame(0, 0, 255))),
      out, { w: W, h: H, fps: FPS, dur: 3.0, preset: "veryfast" },
    )
    expect(n).toBe(24)
    expect(probeDuration(out)).toBeLessThan(2.0)
  })
})
