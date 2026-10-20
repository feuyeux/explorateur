// tools/dbg-boundaries.ts —— 打印某段文本的 edge-tts 词边界（诊断用，不进产线）
// 用法：tsx tools/dbg-boundaries.ts "<文本>"
import { stream } from '../../usine/packages/core/src/tts/client.js'

const text = process.argv[2] ?? '测试文本'
const voice = process.argv[3] ?? 'zh-CN-YunyangNeural'
const words: Array<{ w: string; t: number; d: number }> = []
for await (const chunk of stream({ text, voice, rate: '+0%', pitch: '+0%' })) {
  if (chunk.type === 'WordBoundary') words.push({ w: chunk.text, t: chunk.offset / 1e7, d: chunk.duration / 1e7 })
}
console.log('text len (codepoints):', [...text].length)
console.log('boundaries:', words.length)
for (const w of words) console.log(JSON.stringify(w.w), w.t.toFixed(2), (w.t + w.d).toFixed(2))
// 覆盖检查：词边界拼起来是否覆盖全文（去空格）
const joined = words.map((w) => w.w).join('')
const stripped = [...text].filter((c) => c !== ' ').join('')
console.log('joined len:', [...joined].length, 'text-no-space len:', [...stripped].length)
console.log('missing from joined:', [...stripped].filter((c) => !joined.includes(c)).join(''))
