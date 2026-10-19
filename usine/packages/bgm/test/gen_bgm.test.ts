// gen_bgm.test.ts — @feuille/bgm 反向验证（verify_skill_scripts.py §2 的移植 + 扩面）
// 零真 API 调用：Lyria 通路（实时 WebSocket / HTTP）不在测试面——免费层
// $0 但区围栏严，测试一律纯函数面 + 本地 ffmpeg 合成音频。
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterAll, afterEach, describe, expect, it, vi } from 'vitest'

import { FeuilleError, audio } from '@feuille/core'
import { gen_bgm } from '@feuille/bgm'

const g = gen_bgm
const D = mkdtempSync(`${tmpdir()}/bgm-test-`)
afterAll(() => rmSync(D, { recursive: true, force: true }))

function captureLog(): { log: string[] } {
  const log: string[] = []
  vi.spyOn(console, 'log').mockImplementation((...a: unknown[]) => {
    log.push(a.map(String).join(' '))
  })
  return { log }
}
afterEach(() => vi.restoreAllMocks())

// ---------- 合成音频 ----------

/** 立体声 PCM：frameIdx → (L, R) 样本。 */
function stereoPcm(frames: number, fn: (i: number) => [number, number]): Buffer {
  const buf = Buffer.alloc(frames * 4)
  for (let i = 0; i < frames; i++) {
    const [l, r] = fn(i)
    buf.writeInt16LE(l, i * 4)
    buf.writeInt16LE(r, i * 4 + 2)
  }
  return buf
}

function sineBed(seconds: number, freq = 1000, amp = 12000, rate = 48000): Buffer {
  return stereoPcm(seconds * rate, (i) => {
    const v = Math.round(amp * Math.sin((2 * Math.PI * freq * i) / rate))
    return [v, v]
  })
}

// ---------- 纯函数判据（verify_skill_scripts.py §2 的机器形态） ----------

describe('垫量与床长判据（§2 移植）', () => {
  it('pad_request：目标 80→92、62→71.3（×1.15 垫量，不是原值）', () => {
    expect(g.padRequest(80)).toBe(92)
    expect(g.padRequest(62)).toBe(71.3)
    expect(g.PAD_FACTOR).toBe(1.15)
  })

  it('床长判据凿洞：实得 78.0<80、54.0<62（两次实测事故）→ ⚠', () => {
    expect(g.bedLenVerdict(78.0, 80).startsWith('⚠')).toBe(true)
    expect(g.bedLenVerdict(54.0, 62).startsWith('⚠')).toBe(true)
    expect(g.bedLenVerdict(78.0, 80)).toContain('78s < 目标 80s（超出 1s 容差）')
  })

  it('床长判据放行：垫量后 92≥80 过；79 在 1s 容差内过（容差边界）', () => {
    expect(g.bedLenVerdict(92.0, 80).startsWith('ok')).toBe(true)
    expect(g.bedLenVerdict(79.0, 80).startsWith('ok')).toBe(true)
  })

  it('rate_guard_bytes：2 秒门 = 48000×2ch×2B×2s = 384000', () => {
    expect(g.rateGuardBytes()).toBe(384000)
  })
})

// ---------- estBpm（起始包络自相关估拍） ----------

describe('estBpm', () => {
  it('合成节拍器：48 hop 一拍 → 117.2 BPM（自相关峰值点名）', () => {
    // 节拍对齐 hop 边界（hop=512 样 @48 kHz → fps=93.75；48 hop/拍 →
    // round(60×93.75/48, 1) = 117.2），让 lag 唯一、断言可以打精确值
    const rate = g.RATE
    const beatHop = 48
    const click = new Float64Array(200)
    for (let j = 0; j < click.length; j++) click[j] = 20000 * Math.exp(-j / 40)
    const frames = 8 * rate
    const pcm = stereoPcm(frames, (i) => {
      const hop = Math.floor(i / 512)
      const inBeat = hop % beatHop === 0
      if (!inBeat) return [0, 0]
      const j = i % 512
      return j < click.length ? [Math.round(click[j]!), Math.round(click[j]!)] : [0, 0]
    })
    expect(g.estBpm(pcm, rate)).toBe(117.2)
  })

  it('尾巴上不完整的帧丢掉：多 3 个杂字节不改变读数', () => {
    const pcm = Buffer.concat([stereoPcm(g.RATE * 2, () => [0, 0]), Buffer.alloc(3, 0x7f)])
    expect(g.estBpm(pcm, g.RATE)).toBeNull()
  })

  it('不到 1 秒 / 纯静音 / 恒定包络 → null（谈不上拍）', () => {
    expect(g.estBpm(stereoPcm(g.RATE / 2, () => [12000, 12000]), g.RATE)).toBeNull()
    expect(g.estBpm(stereoPcm(g.RATE, () => [0, 0]), g.RATE)).toBeNull() // 静音：onset 全零
    expect(g.estBpm(stereoPcm(g.RATE * 2, () => [8000, 8000]), g.RATE)).toBeNull() // 恒定音：包络无起伏
  })
})

// ---------- verifyRate（拍速反查采样率解读） ----------

describe('verifyRate', () => {
  it('直接解读命中：168 对 168 → ok（1 倍）', () => {
    const s = g.verifyRate(168, 168)
    expect(s.startsWith('ok')).toBe(true)
    expect(s).toContain('实测 168.0 BPM 命中请求 168 的 1 倍，48 kHz 解读可信')
  })

  it('直读在 ±5% 内先认直读：175.8 对 168 → ok（不误杀，实测踩过）', () => {
    expect(g.verifyRate(175.8, 168).startsWith('ok')).toBe(true)
  })

  it('换算比能解释 → MISMATCH（采样率读错，致命）：154 对 168', () => {
    const s = g.verifyRate(154, 168)
    expect(s.startsWith('MISMATCH')).toBe(true)
    expect(s).toContain('换算比 1.0884 后 ≈ 168 BPM')
    expect(s).toContain('**不要用这个文件**')
  })

  it('都套不上 → inconclusive（模型没照 bpm 走，请人耳确认）', () => {
    const s = g.verifyRate(100, 168)
    expect(s.startsWith('inconclusive')).toBe(true)
    expect(s).toContain('更像模型没照 bpm 走')
  })

  it('测不出拍速 → inconclusive（起始包络过弱）', () => {
    expect(g.verifyRate(null, 72)).toContain('起始包络过弱，测不出拍速')
  })
})

// ---------- FFT（radix-2 + Bluestein）与 bandShare ----------

describe('rfft（自写 radix-2 + Bluestein，任意 N 精确）', () => {
  function naiveRfftMag(x: Float64Array): Float64Array {
    const n = x.length
    const half = Math.floor(n / 2)
    const out = new Float64Array(half + 1)
    for (let k = 0; k <= half; k++) {
      let re = 0, im = 0
      for (let t = 0; t < n; t++) {
        const a = (-2 * Math.PI * k * t) / n
        re += x[t]! * Math.cos(a)
        im += x[t]! * Math.sin(a)
      }
      out[k] = Math.hypot(re, im)
    }
    return out
  }
  const sig = (n: number): Float64Array => {
    const x = new Float64Array(n)
    for (let t = 0; t < n; t++) {
      x[t] = Math.sin(t * 1.7) + 0.5 * Math.cos(t * 0.3) + (((t * 2654435761) % 97) / 97)
    }
    return x
  }

  it('N=16（2 的幂，radix-2 路）与 naive DFT 逐 bin 一致', () => {
    const x = sig(16)
    const got = g.rfftMag(x)
    const want = naiveRfftMag(x)
    for (let k = 0; k < want.length; k++) {
      expect(Math.abs(got[k]! - want[k]!)).toBeLessThan(1e-9 * Math.max(1, want[k]!))
    }
  })

  it('N=21（奇数，Bluestein 路）与 naive DFT 逐 bin 一致', () => {
    const x = sig(21)
    const got = g.rfftMag(x)
    const want = naiveRfftMag(x)
    for (let k = 0; k < want.length; k++) {
      expect(Math.abs(got[k]! - want[k]!)).toBeLessThan(1e-9 * Math.max(1, want[k]!))
    }
  })

  it('大 N 走 Bluestein 也不漂：N=1500 vs naive（平方指数 mod 2N）', () => {
    const x = sig(1500)
    const got = g.rfftMag(x)
    const want = naiveRfftMag(x)
    for (let k = 0; k < want.length; k++) {
      expect(Math.abs(got[k]! - want[k]!)).toBeLessThan(1e-8 * Math.max(1, want[k]!))
    }
  })
})

describe('bandShare（频段能量分布）', () => {
  it('60 Hz + 1.5 kHz 双音各半：<100 ≈ 50%、1k-3k ≈ 50%（离频段边界远，窗旁瓣不越界）', () => {
    const p = `${D}/two_tones.wav`
    const rate = g.RATE
    const pcm = stereoPcm(rate, (i) => {
      const v = Math.round(8000 * Math.sin((2 * Math.PI * 60 * i) / rate)
        + 8000 * Math.sin((2 * Math.PI * 1500 * i) / rate))
      return [v, v]
    })
    g.writeWav(p, pcm)
    const bands = g.bandShare(p)
    expect(bands['<100']!).toBeGreaterThan(45)
    expect(bands['<100']!).toBeLessThan(55)
    expect(bands['1k-3k']!).toBeGreaterThan(45)
    expect(bands['1k-3k']!).toBeLessThan(55)
    expect(bands['400-1k']!).toBeLessThan(1)
    expect(bands['100-400']!).toBeLessThan(1)
    expect(bands['>3k']!).toBeLessThan(1)
  })

  it('不足 1 秒 → {}（判据不硬编数据）', () => {
    const p = `${D}/short.wav`
    g.writeWav(p, sineBed(0.5))
    expect(g.bandShare(p)).toEqual({})
  })

  it('读头解析：RIFF/wave 帧数与声道换算（readWav）', () => {
    const p = `${D}/rw.wav`
    const pcm = sineBed(1)
    g.writeWav(p, pcm)
    const w = g.readWav(p)
    expect(w.sampleRate).toBe(g.RATE)
    expect(w.channels).toBe(2)
    expect(w.data.length).toBe(pcm.length)
    writeFileSync(`${D}/notwav.bin`, 'nope')
    expect(() => g.readWav(`${D}/notwav.bin`)).toThrow(FeuilleError)
  })
})

// ---------- tonalVerdict（配器判据） ----------

describe('tonalVerdict', () => {
  it('低频嗡鸣事故形态 → ⚠ 太暗（实测坑：>3k 0.1%、<100 70%）', () => {
    const s = g.tonalVerdict({ '<100': 70, '100-400': 20, '400-1k': 0.5, '1k-3k': 0.4, '>3k': 0.1 })
    expect(s.startsWith('⚠ 太暗')).toBe(true)
    expect(s).toContain('>3 kHz 仅 0.1%、<100 Hz 占 70.0%')
  })

  it('中高频偏少 → ⚠ 发闷；ok 形态 → ok；空 → inconclusive', () => {
    expect(g.tonalVerdict({ '<100': 20, '100-400': 70, '400-1k': 1, '1k-3k': 1, '>3k': 8 }).startsWith('⚠ 中高频偏少')).toBe(true)
    const ok = g.tonalVerdict({ '<100': 10, '100-400': 30, '400-1k': 20, '1k-3k': 25, '>3k': 15 })
    expect(ok.startsWith('ok')).toBe(true)
    expect(ok).toContain('400 Hz–3 kHz 共 45.0%，>3 kHz 15.0%')
    expect(g.tonalVerdict({})).toBe('inconclusive（不足 1 秒，测不了）')
  })
})

// ---------- measure（真 ffmpeg，量电平/时长） ----------

describe('measure（本地 ffmpeg 实测）', () => {
  it('1.5 s 正弦床：时长 ±0.05s、峰值 ≈ −6 dBFS（0.5 满幅）', () => {
    const p = `${D}/measured.wav`
    // amp 16384 ≈ 满幅一半 → 峰值 dBFS ≈ 20·log10(16384/32768) = −6.02
    g.writeWav(p, stereoPcm(Math.round(1.5 * g.RATE), (i) => {
      const v = Math.round(16384 * Math.sin((2 * Math.PI * 440 * i) / g.RATE))
      return [v, v]
    }))
    const m = g.measure(p)
    expect(m.duration_s).toBeGreaterThan(1.45)
    expect(m.duration_s).toBeLessThan(1.55)
    expect(m.rms_dbfs).not.toBeNull()
    expect(m.peak_dbfs!).toBeGreaterThan(-6.3)
    expect(m.peak_dbfs!).toBeLessThan(-5.7)
  })

  it('ffprobe 时长走 core audio.probeDuration（同源唯一实现）', () => {
    const p = `${D}/probe.wav`
    g.writeWav(p, sineBed(2))
    expect(audio.probeDuration(p)).toBeCloseTo(g.measure(p).duration_s, 2)
  })
})

// ---------- 凭据与 env 文件 ----------

describe('key 文件与环境', () => {
  const savedBedEnv = process.env['BGM_BED_ENV']
  const savedKey = process.env['GEMINI_API_KEY']
  afterEach(() => {
    if (savedBedEnv === undefined) delete process.env['BGM_BED_ENV']
    else process.env['BGM_BED_ENV'] = savedBedEnv
    if (savedKey === undefined) delete process.env['GEMINI_API_KEY']
    else process.env['GEMINI_API_KEY'] = savedKey
  })

  it('loadEnvFile：灌环境、不覆盖已有变量、剥两端引号、跳过注释/空行/无 = 行', () => {
    const f = `${D}/keys.env`
    writeFileSync(f,
      '# 注释行\n'
      + '\n'
      + 'NOEQ 行\n'
      + 'GEMINI_API_KEY="from-file"\n'
      + "OTHER_KEY='single'\n", 'utf8')
    process.env['BGM_BED_ENV'] = f
    delete process.env['GEMINI_API_KEY']
    delete process.env['OTHER_KEY']
    expect(g.loadEnvFile()).toBe(f)
    expect(process.env['GEMINI_API_KEY']).toBe('from-file')
    expect(process.env['OTHER_KEY']).toBe('single')
    // 环境优先于文件：已有变量不覆盖 → 返回 null（无可加载行）
    process.env['BGM_BED_ENV'] = f
    delete process.env['GEMINI_API_KEY']
    process.env['GEMINI_API_KEY'] = 'from-env'
    expect(g.loadEnvFile()).toBeNull()
    expect(process.env['GEMINI_API_KEY']).toBe('from-env')
    // 文件不存在 → null（不是错误）
    process.env['BGM_BED_ENV'] = `${D}/nope.env`
    expect(g.loadEnvFile()).toBeNull()
  })

  it('--list-providers：key 文件加载行 + lyria 凭据行 + 就绪提示（零网络）', async () => {
    process.env['BGM_BED_ENV'] = `${D}/nope.env`
    process.env['GEMINI_API_KEY'] = 'dummy-key-for-list-providers'
    const { log } = captureLog()
    expect(await g.main(['--list-providers'])).toBe(0)
    const out = log.join('\n')
    expect(out).toContain('lyria')
    expect(out).toContain('✓ GEMINI_API_KEY / ~/.gemini_api_key')
    expect(out).toContain(`key 文件：${D}/nope.env（不存在或没可解析行`)
    expect(out).toContain('Lyria 线凭据就绪，可以生成。')
  })
})

// ---------- recheck（按现有边车重算判据并回写） ----------

describe('recheck', () => {
  const savedNarr = process.env['NARRATION_RMS_DB']
  afterEach(() => {
    if (savedNarr === undefined) delete process.env['NARRATION_RMS_DB']
    else process.env['NARRATION_RMS_DB'] = savedNarr
  })

  function makeBed(name: string, seconds: number, freq = 1000): { out: string; side: string } {
    const out = `${D}/${name}.wav`
    g.writeWav(out, sineBed(seconds, freq))
    return { out, side: `${out}.json` }
  }

  it('好床：边车重算齐活（measured/bpm_detected/rate_check/band_share/tonal/bed_len）→ 0', () => {
    const { out, side } = makeBed('bed_ok', 3)
    writeFileSync(side, JSON.stringify({
      provider: 'lyria', model: 'lyria-realtime-exp',
      bpm_requested: 72, duration_target_s: 2,
    }), 'utf8')
    const { log } = captureLog()
    expect(g.recheck(out, side, null, 16)).toBe(0)
    const rec = JSON.parse(readFileSync(side, 'utf8'))
    expect(rec['measured']['duration_s']).toBeGreaterThan(2.9)
    // 1 kHz 正弦一个 hop 装不下整周期（512 样 = 10.67 周期）——包络有起伏，
    // estBpm 名得出确定性读数 187.5（60×93.75/30）；Python 对同款数据同读数。
    // 拍速反查 → 离请求 72 远且换算比套不上 → inconclusive（不是 MISMATCH，不 block）
    expect(rec['bpm_detected']).toBe(187.5)
    expect(rec['rate_check']).toContain('inconclusive：实测 187.5 BPM 离请求 72 远')
    expect(rec['tonal_check'].startsWith('ok')).toBe(true)
    expect(rec['bed_len_check'].startsWith('ok')).toBe(true)
    const out0 = log.join('\n')
    expect(out0).toContain('床长判据：ok（3s ≥ 目标 2s）') // pyG 语义：3.0 → '3'
  })

  it('床短于目标 → ⚠ 进 blocked → 退出码 2（判据不通过要让退出码说话）', () => {
    const { out, side } = makeBed('bed_short', 3)
    writeFileSync(side, JSON.stringify({
      provider: 'lyria', model: 'lyria-realtime-exp',
      bpm_requested: 72, duration_target_s: 10,
    }), 'utf8')
    const { log } = captureLog()
    expect(g.recheck(out, side, null, 16)).toBe(2)
    expect(log.join('\n')).toContain('床长判据：⚠ 成曲 3s < 目标 10s')
  })

  it('NARRATION_RMS_DB 环境兜底 + suggested_gain 反推回写', () => {
    const { out, side } = makeBed('bed_gain', 3)
    writeFileSync(side, JSON.stringify({
      provider: 'lyria', model: 'lyria-realtime-exp',
      bpm_requested: 72, duration_target_s: 2,
    }), 'utf8')
    process.env['NARRATION_RMS_DB'] = '-21.4'
    const { log } = captureLog()
    expect(g.recheck(out, side, null, 16)).toBe(0)
    const rec = JSON.parse(readFileSync(side, 'utf8'))
    expect(typeof rec['suggested_gain']).toBe('number')
    expect(rec['gain_basis']).toContain('旁白 -21.4 dBFS − 目标 16 dB − 床')
    expect(log.join('\n')).toMatch(/→ gain [\d.]+（旁白 -21.4 dBFS − 目标 16 dB − 床/)
  })

  it('旧版边车（只有 duration_requested_s）退化取它；缺前提 → 显式炸', () => {
    const { out, side } = makeBed('bed_old', 3)
    writeFileSync(side, JSON.stringify({
      provider: 'lyria', model: 'lyria-realtime-exp', bpm_requested: 72,
      duration_requested_s: 2,
    }), 'utf8')
    const { log } = captureLog()
    expect(g.recheck(out, side, null, 16)).toBe(0)
    expect(log.join('\n')).toContain('床长判据：ok（3s ≥ 目标 2s）')

    const { out: o2, side: s2 } = makeBed('bed_bad', 3)
    writeFileSync(s2, JSON.stringify({ note: '不是本命令写的' }), 'utf8')
    expect(() => g.recheck(o2, s2, null, 16)).toThrow(FeuilleError)
    expect(() => g.recheck(`${D}/ghost.wav`, `${D}/ghost.wav.json`, null, 16)).toThrow(FeuilleError)
  })
})

// ---------- main 的 argparse 镜像护栏 ----------

describe('main 护栏（不触网络）', () => {
  const savedKey = process.env['GEMINI_API_KEY']
  afterEach(() => {
    if (savedKey === undefined) delete process.env['GEMINI_API_KEY']
    else process.env['GEMINI_API_KEY'] = savedKey
  })

  it('缺 --out → 显式炸（--list-providers 除外）', async () => {
    await expect(g.main([])).rejects.toThrow('--out 必填（--list-providers 除外）')
  })

  it('未知旗标 → FeuilleError；多余位置参数 → usage + 2', async () => {
    await expect(g.main(['--nope'])).rejects.toThrow(FeuilleError)
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(await g.main(['stray-positional'])).toBe(2)
    expect(err.mock.calls[0]!.join(' ')).toContain('usage: feuille bgm gen')
  })

  it('已存在不覆盖（纪律 13）：--out 落地文件已存在 → 炸；--force 越过后还要提示词', async () => {
    const out = `${D}/exists.wav`
    g.writeWav(out, sineBed(1))
    await expect(g.main(['--out', out])).rejects.toThrow('已存在；生成类命令默认不覆盖（纪律 13）。确要覆盖加 --force')
    await expect(g.main(['--out', out, '--force'])).rejects.toThrow('至少给一个 --prompt 或一段 --text')
  })

  it('数值旗标要数值；--bpm 要整数', async () => {
    const out = `${D}/x.wav`
    await expect(g.main(['--out', out, '--duration', 'abc'])).rejects.toThrow('--duration 要数值')
    await expect(g.main(['--out', out, '--bpm', '72.5'])).rejects.toThrow('--bpm 要整数')
  })

  it('lyria-3.x HTTP 后端要 --text（--prompt 有了才走得到这条）；没有提示词 → 主守卫先拦', async () => {
    process.env['GEMINI_API_KEY'] = 'dummy'
    const out = `${D}/y.wav`
    // 主守卫在前（Python main 同序）：无 prompt 且无 text → 主守卫的报错
    await expect(g.main(['--out', out]))
      .rejects.toThrow('至少给一个 --prompt 或一段 --text——lyria 要提示词')
    // --prompt 给了、--text 没给、模型走 HTTP → gen_lyria 的专门报错
    await expect(g.main(['--out', out, '--model', 'lyria-3.5', '--prompt', 'x']))
      .rejects.toThrow('--text 是 --model lyria-3.x 这条 HTTP 后端必需的')
  })

  // 本机可能真有 ~/.gemini_api_key / 统一凭据文件——key 缺席路径只有干净机器才可测
  it.skipIf(existsSync(join(homedir(), '.gemini_api_key'))
    || existsSync(join(homedir(), '.config', 'feuille', 'keys.env'))
    || existsSync(join(homedir(), '.config', 'feuille', 'bgm-bed.env')))(
    '找不到 key → 显式炸（不静默走空请求）', async () => {
      const savedKey = process.env['GEMINI_API_KEY']
      const savedBedEnv = process.env['BGM_BED_ENV']
      delete process.env['GEMINI_API_KEY']
      process.env['BGM_BED_ENV'] = `${D}/nope.env`
      try {
        await expect(g.main(['--out', `${D}/z.wav`, '--prompt', 'soft piano']))
          .rejects.toThrow('找不到 Lyria key：设 GEMINI_API_KEY 或写 ~/.gemini_api_key')
      } finally {
        if (savedKey !== undefined) process.env['GEMINI_API_KEY'] = savedKey
        if (savedBedEnv === undefined) delete process.env['BGM_BED_ENV']
        else process.env['BGM_BED_ENV'] = savedBedEnv
      }
    })
})

// ---------- barrel ----------

it('@feuille/bgm 出包面：gen_bgm 命名空间齐全', () => {
  for (const k of ['padRequest', 'bedLenVerdict', 'verifyRate', 'estBpm', 'bandShare',
    'tonalVerdict', 'measure', 'loadEnvFile', 'detectProviders', 'recheck', 'main',
    'writeWav', 'readWav', 'rfftMag', 'rateGuardBytes'] as const) {
    expect(typeof (g as Record<string, unknown>)[k]).toBe('function')
  }
})
