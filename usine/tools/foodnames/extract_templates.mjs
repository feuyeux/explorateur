// extract_templates.mjs — 从第 01 期（手写）的 poster_src.html / video_src.html 里
// 剥出「与期数无关」的模板（CSS + 逐格自适应 JS），供 build_episode.mjs 复用。
//
// 一次性工具：跑完就把结果提交进 tools/foodnames/templates/，之后不再依赖它。
// 做法是**按标记切片**而不是整段复制，保证模板与第 01 期的实际渲染一致。
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

const USINE = resolve(process.argv[2] ?? '.')
const EP01 = join(USINE, 'examples', 'sushi-12lang')
const OUT = join(USINE, 'tools', 'foodnames', 'templates')
mkdirSync(OUT, { recursive: true })

function cut(text, startMark, endMark) {
  const a = text.indexOf(startMark)
  if (a < 0) throw new Error(`not found: ${startMark}`)
  const b = text.indexOf(endMark, a)
  if (b < 0) throw new Error(`not found: ${endMark}`)
  return text.slice(a, b)
}

// ---- poster ----
const poster = readFileSync(join(EP01, 'poster_src.html'), 'utf8')
const posterStyle = cut(poster, ':root {', '</style>')
  // 韩语逐音节补丁类由测量产物注入（每期音节不同）→ 留占位
  .replace(/\.k[0-9A-F]{4,6} \{[^}]*\}\s*/g, '{{KO_CSS}}\n')
  .replace(/(\{\{KO_CSS\}\}\n)+/g, '{{KO_CSS}}\n')
const posterFit = cut(poster, '<script>\n// per-cell auto-fit', '</script>') + '</script>\n'
writeFileSync(join(OUT, 'poster_style.css'), posterStyle, 'utf8')
writeFileSync(join(OUT, 'poster_fit.js'), posterFit, 'utf8')

// ---- video ----
const video = readFileSync(join(EP01, 'video_src.html'), 'utf8')
const videoStyle = cut(video, ':root {', '</style>')
  .replace(/\.k[0-9A-F]{4,6} \{[^}]*\}\s*/g, '{{KO_CSS}}\n')
  .replace(/(\{\{KO_CSS\}\}\n)+/g, '{{KO_CSS}}\n')
const videoScript = cut(video, '<script>\n// ?lang=zh-CN&state=-1', '</script>') + '</script>\n'
writeFileSync(join(OUT, 'video_style.css'), videoStyle, 'utf8')
writeFileSync(join(OUT, 'video_script.js'), videoScript, 'utf8')

console.log('templates written to', OUT)
for (const f of ['poster_style.css', 'poster_fit.js', 'video_style.css', 'video_script.js']) {
  console.log(' ', f, readFileSync(join(OUT, f), 'utf8').length, 'bytes')
}
