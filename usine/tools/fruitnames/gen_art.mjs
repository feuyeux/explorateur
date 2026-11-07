// gen_art.mjs — 水果系列插画生成（MCode Matrix 图像生成线）
//
// 一集 = 4 种水果 = 4 张插画；10 集 = 40 张。
//
// **为什么走 Matrix 而不是 Gemini**：2026-11-06 实测，本工作区的 Gemini
// 免费层生图配额为 0（`Quota exceeded … limit: 0`，模型
// gemini-3-pro-image / gemini-2.5-flash-image / gemini-3.1-flash-image
// 全部如此；不是某一模型的问题，重试要等 18h59m）。Matrix 线用 Code 登录态，
// 无需 key，整批可用。
//
// **两步走（出透明贴纸）**：
//   ① generate_image      —— 白底出图（背景纯白才好抠）
//   ② remove_image_background —— 去背成透明 PNG
// 直接出「奶油底」的图不行：那张图带一圈白色贴纸边（sticker halo），
// 贴在纸色上会露出一圈白边；去背把白底和那圈白边一起抠掉。
//
// 风格后缀在 STYLE 里钉死（40 张逐字相同）——风格的唯一事实源。
//
// 事实源与纪律：
// - 主体描述在 SUBJECTS 里逐个写**外观特征**（形状/颜色/细节），
//   不写水果名——写名字模型会自由发挥成写实渲染。
// - 生成类命令默认不覆盖已有产物（显式 --force 才覆盖）。
// - 验收靠人眼（判据见 prompts/style-test.md），机器判不了风格一致性。
//
// 跑法（仓库根目录）：
//   node --import tsx tools/fruitnames/gen_art.mjs --list
//   node --import tsx tools/fruitnames/gen_art.mjs --only apple
//   node --import tsx tools/fruitnames/gen_art.mjs --episodes 1 --force
//
// 引擎（--engine）：
//   matrix（默认）—— mcode 运行时的 Matrix connector。**启动器只在 mcode
//     运行时进程的 PATH 上**（asset.json 的 sessionId 就是它）；从 ZCode 的
//     shell 里跑会 `where mcode-tools` 找不到，2026-11-07 实测。
//   mmx —— `mmx image generate`（image-01，API-key 登录态随 mmx config），
//     这台机器随时可跑。image-01 的家法是光泽卡通：探针 7 轮（probe/
//     mmx-apple-v1..v7）实测「扁平色块」这条轴随机、「描边/无投影/无字/
//     居中」五条轴在 MMX_STYLE 下稳定——所以 mmx 引擎**逐图过 VLM 风格门**
//     （mmx vision describe 六问，全 yes 才落盘，最多重试 2 次），门不过的
//     宁缺毋滥。跨引擎不混批：同一集的图必须同一引擎出的，风格才成套。
import { execFileSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'

const here = dirname(fileURLToPath(import.meta.url))
const USINE = resolve(here, '..', '..')
const ART_DIR = join(USINE, 'examples', 'fruitnames', 'art')
const DATA = join(USINE, 'examples', 'fruitnames', 'data', 'fruitlist.json')

// 旗标写成显式字面量：SKILL.md 旗标对账门（dsh-plugin parity）扫描脚本里的
// '--xxx' 字面量——拼出来的（'--' + name）会被判成幻觉旗标。
function arg(flag, dflt) {
  const i = process.argv.indexOf(flag)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}
const ONLY = arg('--only')
const EPISODES = arg('--episodes') ? String(arg('--episodes')).split(',').map((s) => Number(s.trim())) : null
const FORCE = process.argv.includes('--force')
const RESOLUTION = arg('--resolution', '1K')
const BATCH = Number(arg('--batch', '5'))
const ENGINE = arg('--engine', 'matrix')
if (!['matrix', 'mmx'].includes(ENGINE)) {
  console.error(`✖ 未知引擎 --engine ${ENGINE}（可选：matrix / mmx）`)
  process.exit(1)
}

// ---------------------------------------------------------------- 风格（唯一事实源）
//
// 口径来自 2026-11-06 的五组对照探测（tools/fruitnames/probe_style.mjs，
// 结果见 examples/fruitnames/probe/_sheet.jpg）：**短口径**最稳——
// 「flat vector illustration, thick dark outline, solid flat colors,
// one green leaf, centered on plain cream background, no text」
// 出的图奶油底、无白边、深棕描边，最贴参考图。写长了反而易被模型拆解成
// 别的读法（实测有一轮整批跑成黑白线稿——**偶发**，所以每批都要人眼核）。
//
// 底色用**奶油**而不是纯白：奶油底直接就是海报纸色，插画不必抠透明；
// 白色贴纸边（sticker halo）在奶油底上会露出来，而短口径天然不出白边。
const STYLE = [
  'flat vector illustration',
  'thick dark outline',
  'solid flat colors',
  'one green leaf',
  'centered on plain cream background',
  'no text',
].join(', ')

// mmx（image-01）专用的风格后缀——2026-11-07 按参考海报 VLM 实测重写。
// 与 matrix 的 STYLE 不是一回事：image-01 的家法是光泽卡通，**投影**是
// 唯一必须压死的轴（参考海报明确无投影），体积明暗反而允许（参考图就有）。
// 两条引擎各留各的后缀，不共用。
const MMX_STYLE = [
  'bold cartoon sticker illustration',
  'thick dark brown outline around every shape',
  'simple flat shading for volume',
  'no drop shadow',
  'no ground shadow',
  'no shadow of any kind',
  'the background is one flat plain warm cream color filling the entire canvas',
  'no scene',
  'no ground line',
  'one small green leaf and short brown stem on top',
  "children's educational flashcard style",
  'no text',
  'no watermark',
].join(', ')

// ---------------------------------------------------------------- 主体描述（逐个水果的外观特征）
const SUBJECTS = {
  apple: 'a bright red apple with a round slightly heart-shaped body, a shallow dimple at the top, smooth glossy skin, faint lighter blush patch',
  banana: 'a curved yellow banana with a gentle crescent shape, blunt rounded tips, a brown stem at the top, a thin brown line along its inner curve',
  orange: 'a round orange with smooth bright orange dimpled peel, a small pale star-shaped calyx scar at the top',
  strawberry: 'a red strawberry with a plump heart shape tapering to a point, dotted with small golden seeds, topped by a green leafy calyx of pointed sepals',
  watermelon: 'a whole round watermelon with dark green striped rind and a pale green band between the stripes',
  pear: 'a pale yellow-green pear with a slender neck widening into a rounded base, smooth skin, a thin brown stem',
  peach: 'a round peach with soft pink-orange skin, a faint crease down one side, a short green stem and one leaf',
  grape: 'a cluster of round purple grapes hanging from a short brown stem, the berries overlapping in a triangular bunch',
  mango: 'an elongated mango with a kidney shape, one end narrower, skin blending from deep red-orange at the top to yellow-green at the bottom',
  pineapple: 'a golden-yellow pineapple with a cross-hatched diamond pattern on its body, topped with a crown of spiky green leaves',
  cherry: 'a pair of glossy deep red cherries joined by two slender green stems',
  lemon: 'a bright yellow lemon with pointed nipples at both ends and a smooth dimpled peel',
  blueberry: 'a small round blueberry with deep dusty blue skin and a pale star-shaped calyx crown at the top',
  raspberry: 'a cluster of small pink-red round drupelets forming a bumpy raspberry shape, topped with a green leafy calyx',
  grapefruit: 'a large round grapefruit with pale pink-orange skin and a small dimple at the top',
  lime: 'a small round lime with bright green dimpled peel',
  kiwi: 'a whole brown fuzzy kiwi with an oval shape and a slight taper at one end',
  melon: 'an oval melon with a golden-tan finely netted rind, faint pale green streaks between the netting, and a small dry stem scar at one end',
  plum: 'a smooth round deep purple plum with a subtle dusty bloom and a short stem',
  coconut: 'a whole brown coconut with a round hairy shell and three small round eyes on one face',
  pomegranate: 'a whole round pomegranate with deep red leathery skin and a crown-shaped calyx at the top',
  persimmon: 'a squat orange-red persimmon with a flat top and a green leafy calyx of four pointed sepals',
  lychee: 'a round lychee with a rough bumpy scaly red shell',
  durian: 'a durian with a spiky yellow-brown husk of sharp triangular thorns, oval shape',
  dragonfruit: 'a magenta dragon fruit with bright green wavy-edged scales curling outward over an oval body',
  avocado: 'a whole dark green pear-shaped avocado with bumpy textured skin',
  papaya: 'an elongated pear-shaped fruit with smooth vivid orange skin, gently curved and tapering toward the stem end, a small green star-shaped leaf scar at the top',
  fig: 'a whole fig with a teardrop shape, deep purple skin and a short stem at the narrow top',
  passionfruit: 'a whole round passion fruit with deep purple skin and a short stem',
  date: 'an oval brown date with wrinkled glossy skin and a small stem',
  mulberry: 'an elongated mulberry made of many tiny clustered bumpy drupelets, deep purple-red',
  loquat: 'a round yellow-orange loquat with smooth skin and a small brown stem with a leaf',
  hawthorn: 'a round bright red hawthorn with a few tiny brown speckles and a short stem',
  olive: 'a smooth oval olive in deep green with a glossy highlight and a small stem',
  cranberry: 'a small round deep red cranberry with a faint dimple at the top',
  guava: 'a round apple-shaped fruit with pale green slightly bumpy skin, a short stem and one small broad leaf at the top',
  mangosteen: 'a round deep purple fruit with a smooth thick rind, a green leafy calyx of four stubby sepals on top, and a small flower-shaped scar on the underside',
  capegooseberry: 'a round translucent yellow-green cape gooseberry enclosed in a papery pale husk',
  nectarine: 'a smooth round nectarine with deep red and yellow streaked skin, no fuzz',
  apricot: 'a small round apricot with orange skin, a faint crease and a short green stem',
}

// ---------------------------------------------------------------- mcode-tools 调用
// mcode-tools 在 Windows 上是 `mcode-tools.cmd` 包装器（不是 .exe）。Node 26
// 对 .cmd 直接 spawn 报 EINVAL（Windows 侧的 .cmd 不能被 CreateProcess 直启），
// 必须经 cmd.exe /c。POSIX 上直接跑。
const IS_WIN = process.platform === 'win32'
const MCODE = IS_WIN ? 'cmd.exe' : 'mcode-tools'
const mcodeCmd = (args) => (IS_WIN ? ['/d', '/s', '/c', 'mcode-tools', ...args] : args)

/** 跑一条 mcode-tools connector 命令，返回解析后的 JSON。 */
function mcode(tool, args) {
  const argsFile = join(tmpdir(), `mcode_${Date.now()}_${Math.random().toString(36).slice(2)}.json`)
  // UTF-8 无 BOM：PowerShell 的 Set-Content -Encoding UTF8 会写 BOM，JSON 解析会炸
  writeFileSync(argsFile, JSON.stringify(args), 'utf8')
  try {
    const out = execFileSync(MCODE, mcodeCmd(['connector', 'call', tool, '--args-file', argsFile]), {
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
      timeout: 900_000,
    })
    return JSON.parse(out)
  } finally {
    try { unlinkSync(argsFile) } catch { /* 临时文件清理失败不影响主流程 */ }
  }
}

function mcodePlain(args) {
  return execFileSync(MCODE, mcodeCmd(args), { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, timeout: 300_000 })
}

/** 下载 node_id 对应的文件到本地。
 *  用 Node 内置 fetch 而不是 curl：Windows 的 curl 走 schannel，吊销服务器
 *  脱机时报 CRYPT_E_REVOCATION_OFFLINE（实测 2026-11-06），下载整体失败。
 *  fetch 走 Node 自己的 TLS 栈，没这个毛病。
 */
async function download(nodeId, outPath) {
  const info = JSON.parse(mcodePlain(['get_asset_url', nodeId]))
  const res = await fetch(info.download_url)
  if (!res.ok) throw new Error(`下载 ${nodeId}：HTTP ${res.status}`)
  const buf = Buffer.from(await res.arrayBuffer())
  writeFileSync(outPath, buf)
  return buf.length
}

// ---------------------------------------------------------------- mmx 调用
// mmx 也是 npm 的 .cmd 包装器，Windows 上同样必须经 cmd.exe /c。
const MMX = IS_WIN ? 'cmd.exe' : 'mmx'
const mmxCmd = (args) => (IS_WIN ? ['/d', '/s', '/c', 'mmx', ...args] : args)

/** 跑一条 mmx 命令并解析 JSON 输出（--output json --quiet）。 */
function mmxJson(args, timeout = 300_000) {
  const out = execFileSync(MMX, mmxCmd([...args, '--output', 'json', '--quiet']), {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
    timeout,
  })
  // 防御性截取：只要最外层 JSON 对象，容掉可能的进度行
  const s = out.slice(out.indexOf('{'), out.lastIndexOf('}') + 1)
  return JSON.parse(s)
}

/** mmx 出一张图到 rawPath（mmx 自己负责下载，Node 栈无 schannel 问题）。 */
function mmxGenerate(prompt, rawPath) {
  mmxJson(['image', 'generate', '--prompt', prompt, '--aspect-ratio', '1:1', '--out', rawPath])
  if (!existsSync(rawPath)) throw new Error(`mmx 未产出文件：${rawPath}`)
}

// VLM 风格门 + 像素残影判据：全 yes（且残影 ≤ 上限）才落盘。
// VLM 只是预检机器，**风格成套与否仍由人眼在联络表上终审**。
// 口径对齐参考海报（2026-11-07 用 VLM 实测参考海报定音）：体积感的简单
// 明暗/高光**允许**（参考图自己就有弧面渐变与白高光）；**背景投影**没有。
// 第 3 问只问「轮廓外的背景」——VLM 会把果内奶油高光误读成贴地影
// （olive/date 实测两轮冤案），高光在轮廓内、不是影。
// 第 3 问之外还有一道**确定性像素判据**兜底（strip_shadow 的残影检测，
// 抓泛洪剥不掉的连通软影），VLM 漏报时它兜住。
const GATE_PROMPT =
  'Answer strictly, one line each: 1) bold cartoon sticker look (flat colors or simple shading for volume are both fine), NOT a watercolor painting, NOT a 3D render, NOT photorealistic (yes/no)? ' +
  '2) thick dark outline (yes/no)? ' +
  '3) looking ONLY at the cream background around and under the fruit, outside its outline: is it uniform cream with no shadow and no darkened or tinted patch? A light highlight on the fruit skin itself is fine and is not a shadow (yes/no)? ' +
  '4) green foliage present (a leaf, stem or leafy crown as appropriate for this fruit) (yes/no)? ' +
  '5) no text, watermark, label or letters anywhere (yes/no)? ' +
  '6) one single centered subject with nothing else in frame — a natural cluster of the same fruit such as a grape bunch counts as one subject, but no bowls, knives, flowers or extra objects (yes/no)?'

function visionCheck(imgPath) {
  const res = mmxJson(['vision', 'describe', '--image', imgPath, '--prompt', GATE_PROMPT])
  const text = String(res.content ?? '')
  const checks = {}
  for (const m of text.matchAll(/([1-6])\)\s*(yes|no)/gi)) checks[Number(m[1])] = m[2].toLowerCase() === 'yes'
  // 第 3 问（影子）只记录不判门：它已有两桩冤案（把果内奶油高光读成
  // 贴地影，olive/date 实测）且与确定性残影判据矛盾（残影 0 仍报有影）。
  // 影子这条轴以 strip_shadow 的 shadowResidue 为准；其余五问照旧判。
  const pass = [1, 2, 4, 5, 6].every((i) => checks[i] === true)
  return { text, checks, pass }
}
const gateFails = (g) => [1, 2, 4, 5, 6].filter((i) => g.checks[i] !== true).join(',')

// ---------------------------------------------------------------- 主流程
// 插画落到海报格子里，底色必须与纸色一致，否则格子里会出现一块方形色斑。
// 目标纸色 = 参考海报的画布底色 #fffcf5（实测 tools/fruitnames/probe_ref.mjs）。
const PAPER = '#fffcf5'
const list = JSON.parse(readFileSync(DATA, 'utf8'))
const fruits = []
for (const ep of list.episodes) {
  if (EPISODES && !EPISODES.includes(ep.episode)) continue
  for (const f of ep.fruits) fruits.push({ ...f, episode: ep.episode })
}

if (process.argv.includes('--list')) {
  for (const f of fruits) {
    const out = join(ART_DIR, `${f.key}.png`)
    console.log(`${f.key.padEnd(18)} ep${String(f.episode).padStart(2, '0')} ${existsSync(out) ? '[已有]' : '[待生成]'} ${out}`)
  }
  console.log(`\n共 ${fruits.length} 张`)
  process.exit(0)
}

const todo = ONLY ? fruits.filter((f) => f.key === ONLY) : fruits.filter((f) => FORCE || !existsSync(join(ART_DIR, `${f.key}.png`)))
if (!todo.length) {
  console.log('全部已存在（要重生成加 --force）')
  process.exit(0)
}
if (ONLY && !FORCE && existsSync(join(ART_DIR, `${ONLY}.png`))) {
  console.error(`✖ ${ONLY}.png 已存在：显式加 --force 才覆盖`)
  process.exit(1)
}
for (const f of todo) {
  if (!SUBJECTS[f.key]) {
    console.error(`✖ ${f.key}：没有主体描述（SUBJECTS 里缺这一条）`)
    process.exit(1)
  }
}

mkdirSync(ART_DIR, { recursive: true })
const manifest = []
const gateLog = []
let made = 0

if (ENGINE === 'mmx') {
  // mmx：单张同步出图 → 程序去影（strip_shadow）→ 双层门（像素残影 +
  // VLM 六问）→ 失败重试（≤2 次），门不过不落盘。
  const { normalizeBg } = await import('./normalize_bg.mjs')
  const { stripShadow } = await import('./strip_shadow.mjs')
  // 残影上限：全分辨率下「厚块」像素数。干净样图实测 0，描边沿贡献 <100；
  // 真投影是几十像素厚的软斑，一出场就是几千。400 给足余量又不放过影。
  const SHADOW_MAX = 400
  for (const f of todo) {
    const raw = join(ART_DIR, `_raw_${f.key}.png`)
    const clean = join(ART_DIR, `_clean_${f.key}.png`)
    // 主体描述是 matrix 线写的，夹着 glossy/shiny（光泽）与 blush patch
    // （浅色斑块=高光邀请）这类词——image-01 会照字面画出高光/渐变，跟
    // matte 风格直接冲突（apple 三连败的根因）。引擎边界上统一剥掉，
    // 不改 SUBJECTS 本体。
    const subj = SUBJECTS[f.key]
      .replace(/\bglossy\b|\bshiny\b/gi, 'matte')
      .replace(/,\s*faint lighter blush patch/i, '')
    const prompt = `${subj}, ${MMX_STYLE}`
    let gate = null
    let shadowOk = false
    let residue = -1
    let attempt = 0
    const MAX_TRIES = 3
    try {
      for (; attempt < MAX_TRIES; attempt++) {
        mmxGenerate(prompt, raw)
        const sr = await stripShadow(raw, clean, PAPER)
        residue = sr.shadowResidue
        shadowOk = residue <= SHADOW_MAX
        gate = visionCheck(clean)
        if (gate.pass && shadowOk) break
        console.log(`  ↻ ${f.key} 第 ${attempt + 1} 次未过门（缺 ${gateFails(gate) || '-'}${shadowOk ? '' : `；残影 ${residue}>${SHADOW_MAX}`}）`)
      }
      if (!(gate.pass && shadowOk)) {
        // 最后一次的落选稿留在盘上（_rejected_ 前缀），人眼复查有凭据
        try { copyFileSync(clean, join(ART_DIR, `_rejected_${f.key}.png`)) } catch { /* 留档失败不影响主流程 */ }
        console.error(`  ✖ ${f.key}：${MAX_TRIES} 次都未过风格门，不落盘（缺 ${gateFails(gate) || '-'}${shadowOk ? '' : `；残影 ${residue}>${SHADOW_MAX}`}）`)
        gateLog.push({ key: f.key, ok: false, attempts: attempt, checks: gate.checks, shadowResidue: residue, text: gate.text })
        continue
      }
      // 去影已完成大半（底色已被泛洪拉到纸色），normalize_bg 收尾：把
      // 主体周围残余的底色漂移统一拉平（理由同 matrix 分支的注释）
      const out = join(ART_DIR, `${f.key}.png`)
      const r = await normalizeBg(clean, out, PAPER)
      console.log(`  ✓ ${f.key}（第 ${attempt + 1} 次过门，残影 ${residue}）→ ${out}（底色归一化 rgb(${r.bg.join(',')}) → rgb(${r.target.join(',')})）`)
      gateLog.push({ key: f.key, ok: true, attempts: attempt + 1, checks: gate.checks, shadowResidue: residue })
      manifest.push({ key: f.key, episode: f.episode, engine: 'mmx' })
      made++
    } catch (e) {
      console.error(`  ✖ ${f.key}：${e.message}`)
      gateLog.push({ key: f.key, ok: false, error: e.message })
    } finally {
      for (const p of [raw, clean]) {
        if (existsSync(p)) { try { unlinkSync(p) } catch { /* 清不掉不算失败 */ } }
      }
    }
  }
  writeFileSync(join(ART_DIR, '_gate.json'), JSON.stringify({ engine: 'mmx', ts: new Date().toISOString(), results: gateLog }, null, 2) + '\n', 'utf8')
} else {
  for (let i = 0; i < todo.length; i += BATCH) {
    const chunk = todo.slice(i, i + BATCH)
    const requests = chunk.map((f) => ({
      prompt: `${SUBJECTS[f.key]}, ${STYLE}`,
      aspect_ratio: '1:1',
      resolution: RESOLUTION,
      output_file: `${f.key}.png`,
    }))
    console.log(`\n▶ 生成 ${chunk.map((f) => f.key).join(', ')}`)
    const res = mcode('connector__matrix__generate_image', { requests })
    const ok = res.success_items ?? []
    const failed = res.failed_items ?? []
    for (const it of failed) console.error(`  ✖ ${it.output_file ?? it.prompt?.slice(0, 30)}：${JSON.stringify(it).slice(0, 300)}`)
    for (const it of ok) {
      const key = chunk.find((f) => it.file_name?.startsWith(f.key))?.key
      if (!key) { console.error(`  ! 认不出输出对应哪种水果：${it.file_name}`); continue }
      const raw = join(ART_DIR, `_raw_${key}.jpg`)
      await download(it.node_id, raw)
      // 底色归一化到纸色（不抠透明）——理由见 normalize_bg.mjs 头注：
      // 这条素材的底色带 JPEG 4:2:0 色度块伪影，抠透明不可靠，归一化可靠。
      const out = join(ART_DIR, `${key}.png`)
      const { normalizeBg } = await import('./normalize_bg.mjs')
      const r = await normalizeBg(raw, out, PAPER)
      console.log(`  ✓ ${key} → ${out}（底色归一化 rgb(${r.bg.join(',')}) → rgb(${r.target.join(',')})，${r.touched} 像素）`)
      manifest.push({ key, episode: chunk.find((f) => f.key === key)?.episode, node_id: it.node_id })
      made++
    }
    // 原始图删掉（去背后不需要），留白占空间
    // ⚠️ 只有在**成图已成功落盘**时才删原始图——2026-11-06 实测：
    // 先删后处理，去背失败时原图已经没了，事后连诊断都做不了。
    for (const f of chunk) {
      const out = join(ART_DIR, `${f.key}.png`)
      if (!existsSync(out)) continue
      const raw = join(ART_DIR, `_raw_${f.key}.jpg`)
      if (existsSync(raw)) { try { unlinkSync(raw) } catch { /* 清不掉不算失败 */ } }
    }
  }
}

const failedKeys = gateLog.filter((g) => !g.ok).map((g) => g.key)
console.log(`\n生成 ${made}/${todo.length} 张 → ${ART_DIR}${failedKeys.length ? `\n未过门：${failedKeys.join(', ')}（用 --only <key> --engine mmx 单独重跑）` : ''}`)
