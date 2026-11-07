// probe_models.mjs — 探测本账号下哪些图像模型真能出图（一次性诊断脚本）
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'
import { readFileSync } from 'node:fs'

const USINE = resolve(process.cwd())
const require = createRequire(join(USINE, 'packages', 'bgm', 'package.json'))
const { GoogleGenAI } = require('@google/genai')

const env = readFileSync(resolve(USINE, '..', 'config', '.env'), 'utf8')
const key = /^GEMINI_API_KEY=(.+)$/m.exec(env)?.[1]?.trim()
const ai = new GoogleGenAI({ apiKey: key })

const MODELS = [
  'gemini-2.5-flash-image',
  'gemini-3.1-flash-image',
  'gemini-3.1-flash-lite-image',
  'imagen-4.0-generate-001',
  'imagen-3.0-generate-002',
]

const prompt = 'a bright red apple, flat vector illustration sticker, thick dark warm-brown outline, solid flat color fills, one small bright green leaf, centered, plain warm cream background, no text'

for (const model of MODELS) {
  try {
    const res = await ai.models.generateContent({
      model,
      contents: prompt,
      config: { responseModalities: ['TEXT', 'IMAGE'] },
    })
    const parts = res.candidates?.[0]?.content?.parts ?? []
    const img = parts.find((p) => p.inlineData?.data)
    console.log(`${model.padEnd(32)} OK  图片 ${img ? Math.round(img.inlineData.data.length * 0.75 / 1024) + 'KB' : '无'}  文本=${parts.filter((p) => p.text).map((p) => p.text).join(' ').slice(0, 60)}`)
  } catch (e) {
    const msg = String(e.message ?? e)
    const code = /code\":?(\d+)/.exec(msg)?.[1] ?? '?'
    const quota = /Quota exceeded for metric: ([^,]+), limit: (\d+)/.exec(msg)
    console.log(`${model.padEnd(32)} FAIL code=${code} ${quota ? `quota=${quota[1].split('/').pop()} limit=${quota[2]}` : msg.slice(0, 110).replace(/\s+/g, ' ')}`)
  }
}
