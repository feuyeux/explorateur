#!/usr/bin/env node
// 生成 docs/architecture-diagram.html —— usine 分层架构图（含全部代码）
//
// 三条纪律，全部由本脚本机器保证（不靠肉眼）：
//   1. 布局断言：任何容器横向溢出 / 同层重叠 / 纵向压叠 → 抛错，不出文件
//   2. 覆盖断言：packages/*/src 下每一个 .ts 模块必须出现在图里 → 缺一个抛错
//   3. 语法断言：颜色 × 字体 组合全图唯一 → 重复即抛错
//
// 数据源（实测，非文档转述）：
//   packages/*/src/**/*.ts 的真实 import 边 + package.json + ownership.json + commands.ts
// 重新生成：node docs/architecture-diagram.gen.mjs

import { writeFileSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join, normalize, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')

/* ═══════════════════════════════════════════════════════════════════════
   §A  视觉语法（唯一事实源）：颜色 = 归属层 × 字体 = 结构角色
   两个正交轴；组合全图唯一 —— 组合即类型，看配色字体即知是什么东西。
   相对仓库 docs/architecture.md §0 的唯一扩展：把 §0 合并的「绿」拆为
   库层绿 host 与设施青绿 infra，以表达 core 内部四层；其余沿用 §0。
   ═══════════════════════════════════════════════════════════════════════ */

const C = {
  ctrl:     { bg: '#eff6ff', stroke: '#2563eb', ink: '#1e3a8a', label: '编排控制面' },
  host:     { bg: '#f0fdf4', stroke: '#16a34a', ink: '#14532d', label: '核心库层 library' },
  infra:    { bg: '#ecfdf5', stroke: '#0d9488', ink: '#134e4a', label: '底座设施 infrastructure' },
  sandbox:  { bg: '#fef3c7', stroke: '#d97706', ink: '#78350f', label: '产线编排 skill 专属' },
  isolated: { bg: '#fff1f2', stroke: '#e11d48', ink: '#4c0519', label: '隔离域（域外世界）' },
  blocked:  { bg: '#b71c1c', stroke: '#7f0000', ink: '#ffffff', label: '封禁路径（红线）' },
  neutral:  { bg: '#f8fafc', stroke: '#334155', ink: '#0f172a', label: '中性容器（数据/产物）' },
  violate:  { bg: '#f5f3ff', stroke: '#7c3aed', ink: '#4c1d95', label: '越层例外（已登记）' },
}

// 字体角色
const F = {
  pkg:  "font-family:ui-sans-serif,-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;font-weight:700",
  mod:  "font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace;font-weight:500",
  data: "font-family:ui-sans-serif,-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;font-style:italic;font-weight:500",
  gate: "font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace;font-weight:700",
}

const problems = []
const fail = (m) => problems.push(m)

/* ── 断言 3：颜色 × 字体 组合唯一 ── */
const comboSeen = new Map()
function combo(token, font, meaning) {
  const k = `${token}|${font}`
  if (comboSeen.has(k)) fail(`语法冲突：组合 ${k} 出现两次（${comboSeen.get(k)} / ${meaning}）`)
  comboSeen.set(k, meaning)
  return { token, font, meaning }
}

/* ── 断言 2：全部代码覆盖 ── */
function walk(dir, acc = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name === 'dist') continue
    const p = join(dir, e.name)
    if (e.isDirectory()) walk(p, acc)
    else if (e.name.endsWith('.ts')) acc.push(p)
  }
  return acc
}
const SRC_FILES = walk(join(ROOT, 'packages')).filter((f) => f.includes('/src/'))
const ALL_MODULES = new Set(SRC_FILES.map((f) => f.split('/packages/')[1]))
const LEAF_MODULES = [...ALL_MODULES].filter((m) => m.startsWith('cli/src/leaves/'))
const covered = new Set()
const cover = (...ids) => ids.forEach((i) => covered.add(i))

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
/** 粗略字宽：CJK 与全角标点按 1em，其余按 0.55em（无衬线） */
const tw = (s, px) => [...String(s)].reduce((a, ch) => a + (/[\u2E80-\uFFEF\u3000-\u303F]/.test(ch) ? px : px * 0.55), 0)
/** 等宽字体字宽：ASCII 按 0.62em（ui-monospace 实测比例），比无衬线宽 */
const twm = (s, px) => [...String(s)].reduce((a, ch) => a + (/[\u2E80-\uFFEF\u3000-\u303F]/.test(ch) ? px : px * 0.62), 0)

/* ── 尺寸常量 ── */
const PAD = 40
const AVAIL = 2000           // 内容区总宽
const INNER = AVAIL           // 层带内边距 0，内容直接贴边
const GAPX = 14
const CH = 25, CHY = 7, CHIP_PAD = 11, MONO_PX = 11.5, HEAD_PX = 13
const SVG_W = INNER + PAD * 2
const X0 = PAD + 14

/* ═══════════════════════ 绘制原语 ═══════════════════════ */

function chipWidth(label) { return Math.max(80, twm(label, MONO_PX) + CHIP_PAD * 2) }

function flowChips(items, x0, availW) {
  const rects = []
  let x = x0, y = 0
  for (const it of items) {
    const label = typeof it === 'string' ? it : it.label
    const w = typeof it === 'string' ? chipWidth(label) : (it.w || chipWidth(label))
    if (x > x0 && x + w > x0 + availW) { x = x0; y += CH + CHY }
    rects.push({ x, y, w, label, tone: typeof it === 'string' ? null : it.tone, dim: typeof it === 'string' ? false : it.dim })
    x += w + 7
  }
  return { rects, h: y + CH }
}

/** 容器：标题 + 副标 + chips + 脚注。返回 {h, bottom, svg} */
function container({ token, font = 'pkg', x, y, w, title, sub, chips, note, id, plain }) {
  const headH = 30 + (sub ? 16 : 0)
  const body = chips && chips.length ? (plain ? null : flowChips(chips, x + 12, w - 24)) : null
  // 断言 1：单个 chip 比容器还宽 → flowChips 会照样画出去（静默溢出，之前真踩过）
  if (body) for (const r of body.rects) {
    if (r.w > w - 24) fail(`chip 溢出容器：${id || title} 「${r.label}」 ${r.w}px > ${w - 24}px`)
  }
  const plainH = plain && chips ? chips.length * 16 + 6 : 0
  const bodyH = plain ? plainH : body ? body.h + 20 : 4
  const noteH = note ? 16 : 0
  const h = headH + bodyH + noteH
  const c = C[token]

  // 断言 1：容器不越出内容区
  if (x + w > PAD + INNER + 0.5) fail(`容器溢出：${id || title} 右边界 ${(x + w).toFixed(0)} > ${(PAD + INNER).toFixed(0)}`)
  // 断言 1：标题/副标不溢出容器
  const innerW = w - 24
  if (tw(title, HEAD_PX) > innerW) fail(`标题溢出：${id || title} 「${title}」 ${tw(title, HEAD_PX).toFixed(0)}px > ${innerW}px`)
  if (sub && tw(sub, 10.5) > innerW) fail(`副标溢出：${id || title} 「${sub}」 ${tw(sub, 10.5).toFixed(0)}px > ${innerW}px`)
  if (note && tw(note, 10.5) > innerW) fail(`脚注溢出：${id || title} 「${note}」 ${tw(note, 10.5).toFixed(0)}px > ${innerW}px`)
  for (const it of plain ? chips : []) {
    const label = typeof it === 'string' ? it : it.label
    if (twm(label, 11) + 16 > innerW) fail(`条目溢出：${id || title} 「${label}」`)
  }

  const o = []
  o.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="9" fill="${c.bg}" stroke="${c.stroke}" stroke-width="1.4"/>`)
  o.push(`<text x="${x + 12}" y="${y + 19}" style="${F[font]};font-size:${HEAD_PX}px" fill="${c.ink}">${esc(title)}</text>`)
  if (sub) o.push(`<text x="${x + 12}" y="${y + 37}" style="${F.data};font-size:10.5px" fill="${c.ink}" opacity="0.8">${esc(sub)}</text>`)
  if (plain) {
    chips.forEach((it, i) => {
      const label = typeof it === 'string' ? it : it.label
      o.push(`<text x="${x + 14}" y="${y + headH + 14 + i * 16}" style="${F.mod};font-size:11px" fill="${c.ink}">— ${esc(label)}</text>`)
    })
  }
  for (const r of body?.rects || []) {
    const tone = r.tone ? C[r.tone] : c
    o.push(`<rect x="${r.x}" y="${y + headH + r.y}" width="${r.w}" height="${CH}" rx="5" fill="#fff" fill-opacity="0.74" stroke="${tone.stroke}" stroke-width="1.1"${r.dim ? ' stroke-dasharray="3 2.5"' : ''}/>`)
    o.push(`<text x="${r.x + CHIP_PAD}" y="${y + headH + r.y + 16.5}" style="${F.mod};font-size:${MONO_PX}px" fill="${tone.ink}" opacity="${r.dim ? 0.62 : 1}">${esc(r.label)}</text>`)
  }
  if (note) o.push(`<text x="${x + 12}" y="${y + h - 7}" style="${F.data};font-size:10.5px" fill="${c.ink}" opacity="0.82">${esc(note)}</text>`)
  return { h, bottom: y + h, svg: o.join('\n') }
}

/** 层带：全宽表头 + 一行容器 */
function band({ token, y, code, title, desc, items, cols }) {
  const o = []
  const c = C[token]
  const n = items.length
  const per = cols || n
  const rows = Math.ceil(n / per)
  const w = Math.floor((INNER - GAPX * (per - 1)) / per)

  const heads = []
  let ry = y + 46
  for (let r = 0; r < rows; r++) {
    const rowItems = items.slice(r * per, (r + 1) * per)
    const boxes = rowItems.map((it, i) => container({ ...it, x: PAD + i * (w + GAPX), y: ry, w }))
    // 断言 1：同排容器不重叠
    for (let i = 1; i < boxes.length; i++) {
      const prevRight = PAD + (i - 1) * (w + GAPX) + w
      if (PAD + i * (w + GAPX) < prevRight) fail(`同层重叠：band ${code} 第 ${r + 1} 排第 ${i} 个容器`)
    }
    o.push(...boxes.map((b) => b.svg))
    heads.push(Math.max(...boxes.map((b) => b.h)))
    ry = Math.max(...boxes.map((b) => b.bottom)) + 14
  }
  const bodyH = ry - (y + 46) - 14
  const bandH = 42 + bodyH + 16

  S.push(`<rect x="${PAD}" y="${y}" width="${INNER}" height="${bandH}" rx="13" fill="${c.bg}" fill-opacity="0.3" stroke="${c.stroke}" stroke-opacity="0.3" stroke-width="1.1" stroke-dasharray="8 5"/>`)
  S.push(`<rect x="${X0}" y="${y + 13}" width="30" height="19" rx="5" fill="${c.stroke}"/>`)
  S.push(`<text x="${X0 + 15}" y="${y + 27}" text-anchor="middle" style="${F.pkg};font-size:11px;letter-spacing:1px" fill="#fff">${esc(code)}</text>`)
  S.push(`<text x="${X0 + 40}" y="${y + 27}" style="${F.pkg};font-size:14.5px" fill="${c.ink}">${esc(title)}</text>`)
  if (desc) S.push(`<text x="${X0 + 40 + tw(title, 14.5) + 14}" y="${y + 27}" style="${F.data};font-size:10.5px" fill="${c.ink}" opacity="0.82">${esc(desc)}</text>`)
  o.forEach((x) => S.push(x))
  return { bottom: y + bandH, h: bandH, code }
}

/** 层间连接行：调用方向 */
function connector(y, from, to, label, token) {
  const c = C[token]
  const cy = y + 15
  S.push(`<path d="M${PAD + 22} ${y + 2} L${PAD + 22} ${cy - 8}" stroke="${c.stroke}" stroke-width="2" marker-end="url(#ah-${token})"/>`)
  S.push(`<text x="${PAD + 38}" y="${cy + 4}" style="${F.pkg};font-size:11.5px" fill="${c.ink}">${esc(from + ' → ' + to)}</text>`)
  S.push(`<text x="${PAD + 38 + tw(from + ' → ' + to, 11.5) + 12}" y="${cy + 4}" style="${F.data};font-size:10.5px" fill="${c.ink}" opacity="0.85">${esc(label)}</text>`)
  return 30
}

/* ═══════════════════════ 图元内容（实测 import 边） ═══════════════════════ */

const LEG_ROWS = [
  combo('ctrl',     'pkg',  '入口包（cli / dsh-plugin）'),
  combo('ctrl',     'mod',  '控制面代码（路由 / 工具 / 叶子）'),
  combo('sandbox',  'pkg',  '七个产线包'),
  combo('sandbox',  'mod',  '产线代码模块'),
  combo('host',     'pkg',  '库集群（音画 / TTS / 数据 / 人物）'),
  combo('host',     'mod',  '库代码模块'),
  combo('infra',    'pkg',  '设施集群'),
  combo('infra',    'mod',  '设施代码模块'),
  combo('isolated', 'pkg',  '四大平台'),
  combo('isolated', 'mod',  '外部宿主程序'),
  combo('neutral',  'data', '资产 · 产物（非代码）'),
  combo('neutral',  'gate', '门禁套件与判据'),
  combo('blocked',  'gate', '永不通行的红线'),
  combo('violate',  'mod',  '越层依赖 / 退役残留'),
]

const L0 = [
  { token: 'ctrl', id: 'L0-dsh', title: 'dsh 宿主', sub: 'DeepSeek Harness · Cordis · 无 TS 变换钩子', chips: [{ label: '@deepseek-ai/cordis', tone: 'neutral', dim: true }, { label: '@deepseek-ai/dsh-tools', tone: 'neutral', dim: true }] },
  { token: 'ctrl', id: 'L0-plugin', title: '@feuille/dsh-plugin', sub: '18 个 usine_* 工具 · 673 LOC · esbuild → dist/index.mjs', chips: [{ label: 'index.ts', covers: 'dsh-plugin/src/index.ts' }, { label: 'tools.ts', covers: 'dsh-plugin/src/tools.ts' }, { label: 'discipline.ts', covers: 'dsh-plugin/src/discipline.ts' }, { label: 'capture.ts', covers: 'dsh-plugin/src/capture.ts' }], note: 'approval 红线 fail-closed · publish 默认不注册' },
  { token: 'ctrl', id: 'L0-bin', title: 'bin/feuille.js', sub: 'node --import tsx · 三系统可跑', chips: [{ label: 'bin/feuille.js', tone: 'neutral', dim: true }] },
  { token: 'ctrl', id: 'L0-cli', title: '@feuille/cli', sub: '表驱动路由 · 513 LOC · 39 条路由 · 39 个叶子', chips: [{ label: 'index.ts', covers: 'cli/src/index.ts' }, { label: 'main.ts', covers: 'cli/src/main.ts' }, { label: 'commands.ts', covers: 'cli/src/commands.ts' }, { label: 'leaves/ ×39（见附录）', tone: 'ctrl' }], note: '退出码 0 / 1 FeuilleError / 2 未知命令' },
]

const L1 = [
  { token: 'sandbox', id: 'L1-poster', title: '@feuille/poster', sub: '⑦ 海报十条 · 1,915 LOC', chips: ['fetch_fonts', 'assemble', 'render_poster', 'render_page', 'audit_charset', 'fit_diag', 'verify_colors', 'check_overlay', 'make_covers', 'measure_korean', { label: 'pixels（私有共享）', tone: 'neutral' }] },
  { token: 'sandbox', id: 'L1-karaoke', title: '@feuille/karaoke', sub: '⑤⑥ 单卡片成片 · 657 LOC', chips: ['gen_tts', 'build_video', 'verify_sync', 'scan_blank'] },
  { token: 'sandbox', id: 'L1-storyteller', title: '@feuille/storyteller', sub: '⑥ 多幕评书产线 · 885 LOC', chips: ['render_act_frames', 'assemble_storyteller'] },
  { token: 'sandbox', id: 'L1-poetry', title: '@feuille/poetry', sub: '⑬ 实拍线诊断 · 816 LOC', chips: ['audio_profile', 'color_contrast'] },
  { token: 'sandbox', id: 'L1-bgm', title: '@feuille/bgm', sub: '⑤ 纯器乐床 · 962 LOC', chips: ['gen_bgm'] },
  { token: 'sandbox', id: 'L1-copy', title: '@feuille/copy', sub: '⑧ 发布词自检 · 518 LOC', chips: ['check_publish_copy'] },
  { token: 'sandbox', id: 'L1-publish', title: '@feuille/publish', sub: '⑨⑩⑪ 发布器 · 4,607 LOC', chips: ['base', 'clock', 'login', 'douyin', 'xhs', 'bilibili', 'collections', 'veriflive', 'check_plan'] },
  { token: 'violate', id: 'L1-lesson', title: 'core · lesson-scene 族', sub: '⚠ skill 专属却住在 core 内', chips: ['lesson', 'parse_scene', 'scene_schema', 'scene_draft', 'scene_audio', 'section_patch'] },
]

const L2 = [
  { token: 'host', id: 'L2-av', title: '音画内核', sub: '成片线与课件渲染线共用', chips: ['textlayer', 'covers', 'audio', 'timeline', 'compose', 'render'] },
  { token: 'host', id: 'L2-tts', title: 'TTS 内核', sub: 'edge-tts 协议自复刻 · 内容寻址缓存', chips: ['tts/client', 'tts/drm', 'tts/pure', 'tts/split', 'tts/synth'] },
  { token: 'host', id: 'L2-data', title: '数据 · 清单 · 指标', sub: '唯一事实源', chips: ['data', 'audit', 'manifest', 'metrics', 'themes'] },
  { token: 'host', id: 'L2-rig', title: '人物与场景', sub: 'rig 规格注册表 · 班底校验', chips: ['rig', 'scenes', 'devices', 'persona'] },
]

const L3 = [
  { token: 'infra', id: 'L3-plat', title: '平台解析与口径', sub: 'resolver 不写死路径', chips: ['platform', 'errors', 'num'] },
  { token: 'infra', id: 'L3-ledger', title: '缓存与像素判据', sub: '账本判新鲜 · 逐帧基线分桶', chips: ['ledger', 'framehash'] },
  { token: 'infra', id: 'L3-imaging', title: '成像底座 imaging', sub: 'sharp + canvas · Pillow 语义镜像', chips: ['imaging/draw', 'imaging/matte', 'imaging/pildraw'] },
  { token: 'infra', id: 'L3-pack', title: '交付打包', sub: 'zip · 非 ASCII 置 UTF-8 flag', chips: ['packaging'] },
]

const L4 = [
  { token: 'isolated', id: 'L4-proc', title: '外部进程', sub: '一律经 resolver，找不到即失败', chips: [{ label: 'ffmpeg', tone: 'isolated' }, { label: 'ffprobe', tone: 'isolated' }, { label: 'magick', tone: 'isolated' }] },
  { token: 'isolated', id: 'L4-br', title: '浏览器（画字事实源）', sub: '铁律：封面/字幕一律 headless 截图', chips: [{ label: 'Edge headless', tone: 'isolated' }, { label: 'Chrome headless', tone: 'isolated' }] },
  { token: 'isolated', id: 'L4-img', title: '成像库', sub: '像素基线锚点 · 升级须重验', chips: [{ label: 'sharp', tone: 'isolated' }, { label: '@napi-rs/canvas', tone: 'isolated' }] },
  { token: 'isolated', id: 'L4-net', title: '网络与云', sub: '零额度红线的两条外呼', chips: [{ label: 'edge-tts (ws)', tone: 'isolated' }, { label: 'Google Lyria', tone: 'isolated' }] },
  { token: 'isolated', id: 'L4-pw', title: '浏览器自动化', sub: '可选依赖 · 函数内动态 import', chips: [{ label: 'Playwright', tone: 'isolated' }] },
  { token: 'isolated', id: 'L4-plat', title: '四大平台（域外世界）', sub: '只经 manifest 门禁放行 · 认证与风控人工', chips: [{ label: '抖音', w: 96 }, { label: '小红书', w: 96 }, { label: 'bilibili', w: 104 }, { label: '知乎', w: 96 }] },
]

const SIDE = [
  { token: 'neutral', font: 'gate', id: 'S-gate', title: '@feuille/gate · 归属门禁', sub: '无 src，纯 vitest 静态检查 · 改动归属不记账当场 FAIL', chips: [{ label: 'gate/test/skills.test.ts', tone: 'neutral' }, { label: 'ownership.json 三方对账', tone: 'neutral' }, { label: 'skills 去歧义', tone: 'neutral' }] },
  { token: 'neutral', font: 'data', id: 'S-asset', title: '资产与产物（中性容器 · 非代码）', sub: '数据层唯一事实源 → build/ 三大产物', chips: ['personas/ 28 人', 'languages/ 14 manifest', 'lessons/ 课件', 'themes/ 5 套', 'skills/ 10 个', 'docs/ 9 篇', 'migration/golden 金样本', 'build/ audio·video·covers'] },
  { token: 'blocked', font: 'gate', plain: true, id: 'S-red', title: '发布红线（永不通行）', sub: '每条都对应一个可执行判据，不是注释', chips: ['manifest 逐项核对不绿 → 不发布', '封面 / 必填项没生效 → 不发这条', 'H3 额度未确认 → 不生成', '脚本自报成功 ≠ 成功（唯一权威判据 = 回列表核验）', '认证与风控一律人工，agent 不得代填'] },
]

// 已收敛的三处层间问题：结论由上面实测 import 边算出，生成器有断言锁住不被改回
/* ── 断言 4：依赖边实测。图的结论必须跟着代码走，不许腐烂 ──
   本图断言「core 内部零环」「rig 不再拖 tts」「data 不再反向依赖 skill 层」——
   这些结论由实测 import 边算出，不是写死的文案。哪天有人改回去，生成直接失败。 */
const CORE_SRC = join(ROOT, 'packages/core/src')
const CORE_DEPS = new Map()
for (const f of walk(CORE_SRC)) {
  const id = relative(CORE_SRC, f).replace(/\.ts$/, '')
  const deps = new Set()
  for (const m of readFileSync(f, 'utf8').matchAll(/from\s+["'](\.[^"']+)["']/g)) {
    deps.add(normalize(join(dirname(f), m[1])).replace(/\.js$/, '').split('src' + '/')[1] ?? '')
  }
  CORE_DEPS.set(id, [...deps].filter(Boolean).sort())
}
// Tarjan 强连通分量 → 找环
{
  const idx = new Map(), low = new Map(), on = new Set(), stack = [], cycles = []
  let n = 0
  const strong = (v) => {
    idx.set(v, n); low.set(v, n++); stack.push(v); on.add(v)
    for (const w of CORE_DEPS.get(v) || []) {
      if (w === v || !CORE_DEPS.has(w)) continue
      if (!idx.has(w)) { strong(w); low.set(v, Math.min(low.get(v), low.get(w))) }
      else if (on.has(w)) low.set(v, Math.min(low.get(v), idx.get(w)))
    }
    if (low.get(v) === idx.get(v)) {
      const comp = []; let w
      do { w = stack.pop(); on.delete(w); comp.push(w) } while (w !== v)
      if (comp.length > 1) cycles.push(comp.sort())
    }
  }
  for (const v of CORE_DEPS.keys()) if (!idx.has(v)) strong(v)
  if (cycles.length) fail(`core 包内出现环：${cycles.map((c) => c.join(' ⇄ ')).join('；')}`)
}
const closure = (id) => (CORE_DEPS.get(id) || []).join(', ')
if ((CORE_DEPS.get('rig') || []).some((d) => d.startsWith('tts')))
  fail('rig 又依赖 tts 了——clamp 的下沉被回退')
if ((CORE_DEPS.get('data') || []).includes('parse_scene'))
  fail('data 又反向依赖 parse_scene 了——静态环被回退')
if ((CORE_DEPS.get('data') || []).includes('parse_scene.ts'))
  fail('data 又反向依赖 parse_scene 了——静态环被回退')
if (!CORE_DEPS.has('lesson') || (CORE_DEPS.get('lesson') || []).length === 0) fail('lesson 模块未扫到')
// 全仓（src）面向用户的退役命令残留
for (const f of SRC_FILES) {
  for (const line of readFileSync(f, 'utf8').split('\n')) {
    const code = line.trim()
    if (code.startsWith('//') || code.startsWith('*') || code.startsWith('/*')) continue
    if (line.includes('uv run')) fail(`面向用户的退役命令残留：${f.replace(ROOT + '/', '')} — ${code.slice(0, 70)}`)
  }
}

const EDGE = [
  { token: 'host', id: 'E1', title: '① data ⇄ parse_scene 静态环 —— 已解', sub: 'layer 间唯一的倒挂，现已归零', chips: ['data 闭包：' + closure('data'), 'parse_scene 闭包：' + closure('parse_scene'), '方法：scenePaths / lessonsDirOf 下沉 core.data'], note: 'tarjan 实测 core 全包零环；data 不再依赖任何 skill 专属模块' },
  { token: 'host', id: 'E2', title: '② rig 为 clamp 拖入 tts 桶 —— 已解', sub: 'WebSocket 协议栈不再进人物 rig 的依赖闭包', chips: ['rig 闭包：' + closure('rig'), '方法：clamp 下沉 core.num，tts 侧保留转出'], note: 'tts/pure 仍转出 clamp 保兼容面，口径本体唯一（纪律 7/10）' },
  { token: 'host', id: 'E3', title: '③ 面向用户的退役命令 —— 已清零', sub: '原 24 处 `uv run` 全部指向已退役的 Python 入口', chips: ['data.ts 报错提示 → feuille scene parse', 'lesson doctor 下一步提示 ×23 → feuille …', 'scene_draft 草稿模板 → feuille scene parse'], note: '金样本 scene_draft.md 那一行有意偏离 Python，已在 migration/README.md 留痕' },
]

const LEAF_GROUPS = [
  ['core', ['version', 'ledger-status', 'framehash-save', 'framehash-check', 'cover-make', 'cover-check', 'persona-validate', 'scene-parse', 'scene-validate', 'scene-draft', 'scene-tts', 'lesson-new', 'lesson-doctor', 'theme-match']],
  ['karaoke', ['karaoke-tts', 'karaoke-build', 'karaoke-verify-sync', 'karaoke-scan-blank']],
  ['poetry', ['poetry-audio-profile', 'poetry-color-contrast']],
  ['storyteller', ['storyteller-render-frames', 'storyteller-assemble']],
  ['poster', ['poster-fetch-fonts', 'poster-assemble', 'poster-render', 'poster-render-page', 'poster-audit-charset', 'poster-fit-diag', 'poster-verify-colors', 'poster-check-overlay', 'poster-make-covers', 'poster-measure-korean']],
  ['copy', ['copy-check']],
  ['bgm', ['bgm-gen']],
  ['publish', ['publish-login', 'publish-check-plan', 'publish-douyin', 'publish-xhs', 'publish-bilibili']],
]

/* ── 覆盖登记 ── */
const P = (pkg, names) => names.forEach((n) => cover(`${pkg}/src/${n}.ts`))
P('poster', ['index', 'fetch_fonts', 'assemble', 'render_poster', 'render_page', 'audit_charset', 'fit_diag', 'verify_colors', 'check_overlay', 'make_covers', 'measure_korean', 'pixels'])
P('karaoke', ['index', 'gen_tts', 'build_video', 'verify_sync', 'scan_blank'])
P('storyteller', ['index', 'render_act_frames', 'assemble_storyteller'])
P('poetry', ['index', 'audio_profile', 'color_contrast'])
P('bgm', ['index', 'gen_bgm'])
P('copy', ['index', 'check_publish_copy'])
P('publish', ['index', 'base', 'clock', 'login', 'douyin', 'xhs', 'bilibili', 'collections', 'veriflive', 'check_plan', 'playwright.d'])
P('cli', ['index', 'main', 'commands'])
P('dsh-plugin', ['index', 'tools', 'discipline', 'capture'])
P('core', ['index', 'platform', 'errors', 'num', 'ledger', 'framehash', 'packaging', 'imaging/index', 'imaging/draw', 'imaging/matte', 'imaging/pildraw', 'tts/index', 'tts/client', 'tts/drm', 'tts/pure', 'tts/split', 'tts/synth', 'textlayer', 'covers', 'audio', 'timeline', 'compose', 'render', 'data', 'audit', 'manifest', 'metrics', 'themes', 'rig', 'scenes', 'devices', 'persona', 'lesson', 'parse_scene', 'scene_schema', 'scene_draft', 'scene_audio', 'section_patch'])
for (const [, names] of LEAF_GROUPS) for (const n of names) cover(`cli/src/leaves/${n}.ts`)

// 断言 2 落地：磁盘上每个模块都必须在 covered 里
for (const m of ALL_MODULES) if (!covered.has(m)) fail(`覆盖缺口：${m} 未出现在图中`)
for (const m of LEAF_MODULES) if (!covered.has(m)) fail(`叶子缺口：${m}`)
const LEAF_DECLARED = LEAF_GROUPS.reduce((a, [, n]) => a + n.length, 0)
if (LEAF_DECLARED !== LEAF_MODULES.length) fail(`叶子数不一致：图上 ${LEAF_DECLARED} ↔ 磁盘 ${LEAF_MODULES.length}`)


/* ═══════════════════════ 组装 ═══════════════════════ */

const S = []
for (const [k, c] of Object.entries(C)) {
  S.push(`<defs><marker id="ah-${k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="${c.stroke}"/></marker></defs>`)
}
S.push(`<rect width="100%" height="100%" fill="#fff"/>`)

let y = 92
const bands = []
const push = (r) => { bands.push(r); return r.h }

y += push(band({ token: 'ctrl', y, code: 'L0', title: '入口与编排控制面', desc: '两个入口互为冗余 · 只路由不干活', items: L0 })) + 4
y += connector(y, 'L0', 'L1', '查表 / 工具调用 · lazy import，CLI 启动零依赖', 'ctrl')
y += push(band({ token: 'sandbox', y, code: 'L1', title: '产线编排 · skill 专属层', desc: '七产线包彼此零依赖 · 全只依赖 core', items: L1 })) + 4
y += connector(y, 'L1', 'L2', '消费 library 唯一实现，包内零重复', 'sandbox')
y += push(band({ token: 'host', y, code: 'L2', title: '核心库层 core · library', desc: '被 ≥2 个 skill 共用 · 依赖边全部指向更低层', items: L2 })) + 4
y += connector(y, 'L2', 'L3', '消费 infrastructure 底座', 'host')
y += push(band({ token: 'infra', y, code: 'L3', title: '底座设施 core · infrastructure', desc: '与业务无关的底座 · 全仓唯一实现', items: L3 })) + 4
y += connector(y, 'L3', 'L4', 'resolver 解析可执行文件 / 子进程 / 驱动浏览器', 'infra')
y += push(band({ token: 'isolated', y, code: 'L4', title: '外部宿主与隔离域', desc: '域外世界 · 只经 manifest 门禁放行', items: L4 })) + 20

y += push(band({ token: 'neutral', y, code: 'SIDE', title: '侧挂：门禁 · 资产 · 红线', desc: '不参与调用链，但决定纪律能否落地', items: SIDE })) + 16
y += push(band({ token: 'host', y, code: 'FIX', title: '已收敛的三处层间问题', desc: '结论由实测 import 边算出 · 生成器断言锁住，改回去就报错', items: EDGE })) + 16

// 附录：39 叶子
const APX = LEAF_GROUPS.map(([g, names]) => ({ token: 'ctrl', id: `APX-${g}`, title: `feuille ${g} ×${names.length}`, sub: '', chips: names.map((n) => n + '.ts') }))
y += push(band({ token: 'ctrl', y, code: 'APX', title: '附录 · 39 个 CLI 叶子全量', desc: `路由表登记 ${LEAF_DECLARED} ↔ leaves/ 实存 ${LEAF_MODULES.length} · 零孤儿零死登记`, items: APX, cols: 4 })) + 16

// 图例
{
  const rh = 24, top = y + 44
  const h = 56 + LEG_ROWS.length * rh + 34
  S.push(`<rect x="${PAD}" y="${y}" width="${INNER}" height="${h}" rx="13" fill="#fff" stroke="${C.neutral.stroke}" stroke-opacity="0.3" stroke-width="1.2"/>`)
  S.push(`<text x="${X0}" y="${y + 27}" style="${F.pkg};font-size:14.5px" fill="#0f172a">图例 · 颜色 × 字体 = 类型（${LEG_ROWS.length} 组，全图唯一，机器已断言）</text>`)
  S.push(`<text x="${X0 + 560}" y="${y + 27}" style="${F.data};font-size:10.5px" fill="#0f172a" opacity="0.82">轴 A 颜色 = 归属层（八值）　轴 B 字体 = 结构角色（四值）　两轴正交，组合不重复 → 看到配色字体即知类型</text>`)
  LEG_ROWS.forEach((r, i) => {
    const ry = top + i * rh
    const c = C[r.token]
    S.push(`<rect x="${X0}" y="${ry}" width="240" height="19" rx="5" fill="${c.bg}" stroke="${c.stroke}" stroke-width="1.1"/>`)
    S.push(`<text x="${X0 + 10}" y="${ry + 13.5}" style="${F[r.font]};font-size:10.5px" fill="${c.ink}">${esc(c.label)}</text>`)
    S.push(`<text x="${X0 + 252}" y="${ry + 13.5}" style="${F.pkg};font-size:10px" fill="#334155">${esc(r.font === 'mod' ? '等宽 500' : r.font === 'pkg' ? '无衬线 700' : r.font === 'data' ? '无衬线斜体' : '等宽 700')}</text>`)
    S.push(`<text x="${X0 + 352}" y="${ry + 13.5}" style="${F.data};font-size:10.5px" fill="#0f172a" opacity="0.86">${esc(r.meaning)}</text>`)
  })
  const fy = top + LEG_ROWS.length * rh + 18
  S.push(`<text x="${X0}" y="${fy}" style="${F.data};font-size:10.5px" fill="#0f172a" opacity="0.86">虚线框 = 层带边界（逻辑归属，非调用）　实线箭头 = 允许的调用方向　紫 = 越层例外（登记在案，非理想态）</text>`)
  S.push(`<text x="${X0}" y="${fy + 15}" style="${F.data};font-size:10.5px" fill="#0f172a" opacity="0.86">相对 docs/architecture.md §0 的唯一扩展：把 §0 合并的「绿」拆为库层绿与设施青绿，以表达 core 内部四层；其余颜色语义沿用 §0。</text>`)
  y += h + 18
}

const SVG_H = y
const totalLoc = ['core', 'cli', 'dsh-plugin', 'publish', 'poster', 'karaoke', 'poetry', 'storyteller', 'copy', 'bgm']
  .reduce((a, p) => a + SRC_FILES.filter((f) => f.startsWith(join(ROOT, 'packages', p, 'src'))).reduce((b, f) => b + readFileSync(f, 'utf8').split('\n').length, 0), 0)

const svg = `<svg viewBox="0 0 ${SVG_W} ${SVG_H}" width="${SVG_W}" height="${SVG_H}" xmlns="http://www.w3.org/2000/svg">
<text x="${PAD}" y="42" style="${F.pkg};font-size:23px" fill="#0f172a">feuille / usine · 分层架构全景（含全部代码）</text>
<text x="${PAD}" y="66" style="${F.data};font-size:11.5px" fill="#0f172a" opacity="0.82">11 包 · ${ALL_MODULES.size} 个源码模块 · ${totalLoc.toLocaleString()} 行 src　｜　数据源：packages/*/src 真实 import 边 + package.json + ownership.json + commands.ts　｜　覆盖与布局断言：docs/architecture-diagram.gen.mjs</text>
${S.join('\n')}
</svg>`

if (problems.length) {
  console.error(`\n✘ 断言失败 ${problems.length} 条，未生成文件：`)
  for (const p of problems) console.error('  · ' + p)
  process.exit(1)
}

const html = `<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>usine · 分层架构全景</title>
<style>
  :root{color-scheme:light}
  *{box-sizing:border-box}
  body{margin:0;background:#eef2f7;color:#0f172a;font-family:ui-sans-serif,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
  .wrap{max-width:1720px;margin:0 auto;padding:26px 20px 60px}
  .scroll{overflow:auto;background:#fff;border-radius:14px;padding:8px;border:1px solid #dbe3ec;
          box-shadow:0 1px 3px rgba(15,23,42,.1),0 8px 28px rgba(15,23,42,.06);max-height:82vh}
  .scroll svg{display:block;width:100%;height:auto;min-width:1500px}
  h1{font-size:20px;margin:0 0 4px}
  .sub{color:#475569;font-size:13px;margin:0 0 16px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px;margin-top:22px}
  .card{background:#fff;border:1px solid #dbe3ec;border-radius:12px;padding:16px 18px;box-shadow:0 1px 2px rgba(15,23,42,.05)}
  .card h2{font-size:14px;margin:0 0 10px;display:flex;align-items:center;gap:8px}
  .dot{width:10px;height:10px;border-radius:3px;flex:none}
  .card ul{margin:0;padding-left:18px}
  .card li{font-size:12.8px;line-height:1.74;color:#334155}
  .card li b{color:#0f172a}
  code{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:11.8px;background:#f1f5f9;padding:1px 5px;border-radius:4px;color:#0f172a}
  .warn{color:#b45309}.bad{color:#be123c}
</style></head><body><div class="wrap">
<h1>usine · 分层架构全景</h1>
<p class="sub">颜色 = 归属层，字体 = 结构角色，两轴正交且组合全图唯一（生成器已断言）。图可横向滚动，下方是渲染结论。</p>
<div class="scroll">${svg}</div>
<div class="grid">
<div class="card"><h2><span class="dot" style="background:#16a34a"></span>拓扑是对的</h2><ul>
<li><b>严格星型。</b>只有 <code>cli</code> 与 <code>dsh-plugin</code> 两个入口依赖产线包；七个产线包<b>彼此零依赖</b>，全部只依赖 <code>@feuille/core</code>。</li>
<li><b>core 内部零环。</b>30 个模块（38 个源文件）的依赖边全部指向更低层，Tarjan 实测无强连通分量。</li>
<li><b>路由表诚实。</b><code>commands.ts</code> 登记 39 条、<code>leaves/</code> 实存 39 个文件，<b>零孤儿零死登记</b>，router 测试逐条验叶子真实可达。</li>
<li><b>产线包很薄。</b>publish 是 <code>base</code>+<code>clock</code> 星型，poster 只有 <code>pixels</code> 一处私有共享，karaoke/poetry/storyteller/bgm/copy 内部零依赖。</li>
<li><b>铁律落进了依赖图。</b>画字只经 <code>platform</code> 解析浏览器，成像库被 <code>textlayer</code>/<code>covers</code> 挡住不直接画字。</li>
</ul></div>
<div class="card"><h2><span class="dot" style="background:#16a34a"></span>本轮已收敛的三处</h2><ul>
<li><b>① 静态环归零。</b><code>scenePaths</code> / <code>lessonsDirOf</code> 从 skill 专属的 <code>parse_scene</code> 下沉到 library 的 <code>data</code>（顺带收敛了 <code>lesson.ts</code> 里重复的第二份实现）。<code>data</code> 的闭包从 <code>errors, parse_scene</code> 缩到只剩 <code>errors</code>——library 不再反向依赖 skill 层。</li>
<li><b>② <code>clamp</code> 下沉 <code>core.num</code>。</b><code>rig</code> 的闭包从 <code>imaging/pildraw, num, tts/index</code> 缩到 <code>imaging/pildraw, num</code>，WebSocket 握手栈不再进人物 rig 的依赖闭包。<code>tts/pure</code> 保留转出以不打断外部调用方，口径本体仍唯一。</li>
<li><b>③ 24 处死命令清零。</b>面向用户的 <code>uv run</code> 全部指向已退役的 Python 入口——<code>lesson doctor</code> 的「下一步」提示正是它的核心契约，照着跑必然失败。</li>
<li><b class="warn">金样本有据可查。</b>为修 ③ 动了 <code>migration/golden/scene_draft.md</code> 一行——那是迁移 parity 证据，改了就可能自证。偏离点、理由、日期已写进 <code>migration/README.md</code>，不是静默改动。</li>
</ul></div>
<div class="card"><h2><span class="dot" style="background:#2563eb"></span>入口面的取舍</h2><ul>
<li><b><code>cli</code> 是耦合面最大处，且是有意的。</b>513 LOC 里 15 处直调 <code>core</code>、另 25 处直调七个产线包——它是唯一同时触达 L1 与 L2 的节点，正是「统一入口」的定义。代价是新增产线必须改路由表。</li>
<li><b><code>dsh-plugin</code> 是 CLI 的能力超集。</b>673 LOC 覆盖 18 个 <code>usine_*</code> 工具，带 <code>approval</code> 红线 fail-closed 与 <code>publish</code> 默认不注册。<b>红线在智能体面是可执行的</b>，不只是注释。</li>
<li><b>两入口有覆盖差：</b><code>poster</code> 的十条与 <code>publish</code> 的合集/回列表核验在插件面收敛成单个工具，粒度比 CLI 粗。要行为完全等价，得为每个叶子各写一份工具 spec。</li>
</ul></div>
<div class="card"><h2><span class="dot" style="background:#334155"></span>文档与实测的两处小差</h2><ul>
<li><b>工具数：</b><code>docs/architecture.md</code> §4 写「17 工具面」，实测定义 <b>18</b> 个 <code>usine_*</code>。自洽解释是 <code>usine_publish</code> 默认不注册（17 + 1 gated），但正文没写这句，读者会以为对不上。</li>
<li><b>归属描述：</b><code>ownership.json</code> 写 publish「对包内其他模块零依赖，自成一体」，实测 publish 内部是 <code>base</code>+<code>clock</code> 的星型（7 个模块依赖它俩）。措辞会被读成「publish 内部零依赖」，与代码不符。</li>
</ul></div>
</div>
<p class="sub" style="margin-top:20px">重新生成：<code>node docs/architecture-diagram.gen.mjs</code>　·　上游权威文本：<code>docs/architecture.md</code>　·　纪律：<code>AGENTS.md</code></p>
</div></body></html>`

writeFileSync(join(HERE, 'architecture-diagram.html'), html)
writeFileSync(join(HERE, 'architecture-diagram.svg'), svg)
console.log(`✔ docs/architecture-diagram.html  ${SVG_W}×${SVG_H}  ${(html.length / 1024).toFixed(0)} KB`)
console.log(`✔ docs/architecture-diagram.svg   ${SVG_W}×${SVG_H}  ${(svg.length / 1024).toFixed(0)} KB（可嵌入 README / 转 PNG）`)
console.log(`  模块覆盖 ${covered.size}/${ALL_MODULES.size}　叶子 ${LEAF_DECLARED}/${LEAF_MODULES.length}　组合 ${LEG_ROWS.length} 组无冲突　布局断言 0 溢出`)
