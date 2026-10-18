// tts-drm.test.ts — Sec-MS-GEC v2 令牌 parity：固定时间戳下与 Python
// （edge-tts 7.3.1 drm.py）输出逐字节相等。这是协议复刻最重的一块——
// 魔改 SHA-256 + CS64，任何一处进位/常量差都会在这里炸。
import { describe, expect, it } from "vitest"

import { generateSecMsGecV2 } from "../src/tts/drm.js"

// 由 usine/.venv 的 edge-tts 7.3.1 generate_sec_ms_gec_v2(ts) 采得（2026-10-18）。
// 注意 300 秒桶量化：0 与 1.5 同桶、1760000000.123 与 .9 同桶。
const PY_FIXTURES: [number, string][] = [
  [0.0, "52BC7A17B50DFEC9-28C4394775C8751CD2F6859C030C06DB1489ACAB3B3A7651831FC26895177ED6"],
  [1.5, "52BC7A17B50DFEC9-28C4394775C8751CD2F6859C030C06DB1489ACAB3B3A7651831FC26895177ED6"],
  [1760000000.123, "6D50DDDB91812C33-DD68EFB01898B0750C9797D51A5FF93471DFDAE6888A1039D532CBDCCE54545D"],
  [1760000000.9, "6D50DDDB91812C33-DD68EFB01898B0750C9797D51A5FF93471DFDAE6888A1039D532CBDCCE54545D"],
  [1234567890.987654, "BA405D1577B8E0CE-61F01E88539977A1A1E969572D82EECFA45FB1E5DEBD122D6ACBAF0054F959E5"],
]

describe("Sec-MS-GEC v2 令牌（drm.ts ↔ edge-tts 7.3.1 drm.py）", () => {
  it("固定时间戳输出逐字节相等", () => {
    for (const [ts, expected] of PY_FIXTURES) {
      expect(generateSecMsGecV2(ts)).toBe(expected)
    }
  })

  it("令牌形状：<16hex 大写>-<64hex 大写>", () => {
    const tok = generateSecMsGecV2(Date.now() / 1000)
    expect(tok).toMatch(/^[0-9A-F]{16}-[0-9A-F]{64}$/)
  })

  it("300 秒桶量化：同桶时间戳同令牌", () => {
    expect(generateSecMsGecV2(1760000100.0)).toBe(generateSecMsGecV2(1760000100.9))
  })
})
