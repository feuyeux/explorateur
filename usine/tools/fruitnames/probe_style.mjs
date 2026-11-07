// probe_style.mjs — 一次性诊断：同一水果换几种提示词口径，看哪条稳
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, unlinkSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { tmpdir } from 'node:os'

const USINE = resolve(process.cwd())
const OUT = join(USINE, 'examples', 'fruitnames', 'probe')
mkdirSync(OUT, { recursive: true })

const IS_WIN = process.platform === 'win32'
const MCODE = IS_WIN ? 'cmd.exe' : 'mcode-tools'
const mcodeCmd = (args) => (IS_WIN ? ['/d', '/s', '/c', 'mcode-tools', ...args] : args)

function mcode(tool, args) {
  const f = join(tmpdir(), `m_${Date.now()}_${Math.random().toString(36).slice(2)}.json`)
  writeFileSync(f, JSON.stringify(args), 'utf8')
  try {
    return JSON.parse(execFileSync(MCODE, mcodeCmd(['connector', 'call', tool, '--args-file', f]), {
      encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, timeout: 900_000,
    }))
  } finally { try { unlinkSync(f) } catch { /* noop */ } }
}
function plain(args) {
  return execFileSync(MCODE, mcodeCmd(args), { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, timeout: 300_000 })
}
async function dl(nodeId, out) {
  const info = JSON.parse(plain(['get_asset_url', nodeId]))
  const res = await fetch(info.download_url)
  writeFileSync(out, Buffer.from(await res.arrayBuffer()))
}

const SUBJ = 'a single bright red apple with a round slightly heart-shaped body, a shallow dimple at the top, smooth glossy skin, faint lighter blush patch'

const VARIANTS = {
  v1_cream_plain: `${SUBJ}, flat vector illustration sticker, thick dark warm-brown outline, solid flat color fills, minimal subtle shading, one small bright green leaf and a short stem on top, centered, isolated on a plain warm cream background, no shadow, no text, no label, no watermark, cute educational flashcard style, clean and consistent`,
  v2_cream_short: `${SUBJ}, flat vector illustration, thick dark outline, solid flat colors, one green leaf, centered on plain cream background, no text`,
  v3_white_short: `${SUBJ}, flat vector illustration, thick dark outline, solid flat colors, one green leaf, centered on plain white background, no text`,
  v4_cream_kids: `Cute flat vector cartoon sticker of a single bright red apple, thick dark brown outline, solid flat colors, small green leaf, plain cream background, children's flashcard, no text`,
  v5_cream_stickerword: `${SUBJ}, flat vector sticker illustration, bold dark brown outline, flat vibrant colors, simple green leaf, isolated on solid cream background, children's educational poster style, no text, no shadow`,
}

const requests = Object.entries(VARIANTS).map(([k, prompt]) => ({
  prompt, aspect_ratio: '1:1', resolution: '1K', output_file: `${k}.png`,
}))

const res = mcode('connector__matrix__generate_image', { requests })
console.log(JSON.stringify(res).slice(0, 500))
for (const it of res.success_items ?? []) {
  const key = Object.keys(VARIANTS).find((k) => it.file_name?.startsWith(k))
  if (!key) { console.log('? ', it.file_name); continue }
  await dl(it.node_id, join(OUT, `${key}.jpg`))
  console.log('✓', key, '→', join(OUT, `${key}.jpg`))
}
