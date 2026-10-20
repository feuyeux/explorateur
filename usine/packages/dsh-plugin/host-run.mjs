// host-run.mjs —— dsh 真宿主实跑（钉版 0.2.1-rc.2）：把「插件挂上了」「红线在
// dispatch 层生效」变成可机检的证据，而不是一句「跑过了」。
//
// 为什么要有这个脚本：vitest 的 fakeCtx 结构上测不到宿主（服务解析、inject 语义、
// approval 服务、审计事件都看不见）；2026-10-18 的真宿主首测只留下一份散文记录
// （后来被删），钉版从 0.1.7 升到 0.2.1-rc.2 之后没有再验过。装配链的最终证据归
// 这里管。
//
// 它证明五件事（任何一件不成立即非零退出）：
//   1. 插件在**真宿主**里挂上了：装配清单新鲜、工具面 17 个、与契约逐字相符；
//   2. 模型确实发起了视频 submit（真发起了，不是「应该会发起」）；
//   3. 审批走的是**原生 dispatch 层**：会话日志里有 approval/asked +
//      approval/decided 事件对（dsh 自己写的审计，不是插件自述）；
//   4. 红线真的拦住了：工具体在执行之前就被拒——没有 task_id、通道没被碰；
//   5. 拒绝是 **dsh 原生语义**（the user rejected tool "…"），不是插件的一个 status。
//
// 证据从**会话日志**里取（不是通知流）：approval/asked + approval/decided 是
// log-only 事件（写进会话日志，不进通知流）；会话日志是多段 zstd 帧拼接的，逐帧解码。
//
// 用法（凭据：MiniMax 平台 key，优先环境变量 MINIMAX_API_KEY，其次 mmx 凭据店；
// 本入口零额度——审批 policy=never 确定性拒绝）：
//   pnpm --filter @feuille/dsh-plugin host-run
//
// 产物（版本化）：
//   docs/dsh-host-evidence.ndjson  关键事件（tool/call、tool/result、approval/*）
//   docs/dsh-host-summary.json    版本、工具名单、判定结论、模型回复
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { zstdDecompressSync } from 'node:zlib'

import { MINIMAX_KEY_HINT, resolveMinimaxCredentials } from './credentials.mjs'

const require = createRequire(import.meta.url)
const here = fileURLToPath(new URL('.', import.meta.url))
const usineRoot = resolve(here, '../..')
const docsDir = resolve(here, '../../docs')
const evidencePath = join(docsDir, 'dsh-host-evidence.ndjson')
const summaryPath = join(docsDir, 'dsh-host-summary.json')
const manifestPath = join(docsDir, '.dsh-host-manifest.json')

const { DeepSeekHarness } = await import('@deepseek-ai/dsh-sdk-client')

const wantsMiniMax = (process.env.FEUILLE_DSH_PROVIDER ?? 'minimax') === 'minimax'
if (wantsMiniMax && !resolveMinimaxCredentials()) {
  console.error(MINIMAX_KEY_HINT)
  process.exit(1)
}

const pkg = JSON.parse(readFileSync(join(here, 'package.json'), 'utf8'))
const pinned = pkg.dependencies['@deepseek-ai/dsh-sdk-client']
const sdkPkg = require.resolve('@deepseek-ai/dsh-sdk-client/package.json')
const dshPkg = require.resolve('@deepseek-ai/dsh/package.json', { paths: [sdkPkg] })
const dshVersion = JSON.parse(readFileSync(dshPkg, 'utf8')).version

// 装配清单：插件 apply 成功后写这个文件（生产宿主不写，env 没设就不写）。
process.env.FEUILLE_DSH_MANIFEST = manifestPath

const notifications = []
const harness = new DeepSeekHarness({
  provider: process.env.FEUILLE_DSH_PROVIDER ?? 'minimax',
  model: process.env.FEUILLE_DSH_MODEL ?? 'MiniMax-M3.1-Flash',
  patches: [join(here, 'ask.cordis.yml')],
  cwd: usineRoot,
})

const TASK = `你在一个加载了 feuille-usine 工具面的 dsh 环境里工作。请依次完成三步，只用 usine_* 工具，不要用 shell：

1. 调用 usine_version 报告 usine 版本号。
2. 调用 usine_verify 跑一次离线验证门禁，然后报告：门禁是否通过、通过/跳过/失败的测试数量（从工具输出里读）。
3. 红线验证：调用 usine_video_generation 发起一次 submit（分辨率 768P、时长 6 秒、提示词任意一句）。预期是它**在派发层就被拦住**、实际没有提交任何生成任务——被拒即预期结果。请原样报告工具返回的内容。

完成后用三行小结回答：版本号、门禁结果摘要、视频生成是否正确停在审批。不要做这三步之外的任何事，不要发布任何内容。`

console.log(`[host-run] dsh 钉版 ${pinned} / 宿主 runtime ${dshVersion}`)
const result = await harness.run(TASK, {
  onNotification: (n) => { notifications.push({ method: n.method, params: n.params }) },
})
await harness.close()

// ---------------------------------------------------------------------------
// 证据抽取
// ---------------------------------------------------------------------------

/** 会话日志：多段 zstd 帧拼接，逐帧解码（Node 的 zstdDecompressSync 只解第一帧）。 */
function readSessionLog(sessionId) {
  const base = join(homedir(), '.dsh', 'sessions')
  let dir = null
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    const p = join(base, d, sessionId)
    if (existsSync(p)) { dir = p; break }
  }
  if (!dir) return []
  const f = join(dir, 'session.v4.jsonl.zstd')
  if (!existsSync(f)) return []
  const b = readFileSync(f)
  const magic = Buffer.from([0x28, 0xB5, 0x2F, 0xFD])
  const offsets = []
  let i = 0
  while ((i = b.indexOf(magic, i)) >= 0) { offsets.push(i); i += 1 }
  let text = ''
  for (const p of offsets) {
    try { text += zstdDecompressSync(b.slice(p)).toString('utf8') } catch { /* 坏帧跳过 */ }
  }
  const out = []
  for (const line of text.split('\n')) {
    if (!line.trim()) continue
    try { out.push(JSON.parse(line)) } catch { /* 非 JSON 行跳过 */ }
  }
  return out
}

const log = readSessionLog(result.sessionId)

/** 递归收集所有字符串值（按解析后的对象走，不用原文正则——JSON 里引号是转义的）。 */
function strings(node, acc = []) {
  if (typeof node === 'string') { acc.push(node); return acc }
  if (Array.isArray(node)) { for (const v of node) strings(v, acc); return acc }
  if (node && typeof node === 'object') { for (const v of Object.values(node)) strings(v, acc) }
  return acc
}

/** 递归收集指定键的所有值。 */
function valuesOf(node, key, acc = []) {
  if (Array.isArray(node)) { for (const v of node) valuesOf(v, key, acc); return acc }
  if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) {
      if (k === key) acc.push(v)
      valuesOf(v, key, acc)
    }
  }
  return acc
}

const logTypes = new Set(log.map((e) => e?.type).filter(Boolean))
const logStrings = strings(log)

const sawApprovalAsked = logTypes.has('approval/asked')
const sawApprovalDecided = logTypes.has('approval/decided')
const sawToolCall = log.some((e) => e?.type === 'tool/call'
  && JSON.stringify(e).includes('usine_video_generation'))
// task_id 必须**没有**——没有就是「没提交」，有值才是真提交了。
const taskIds = valuesOf(log, 'task_id').filter((v) => typeof v === 'string' && v.length > 0)
const sawTaskId = taskIds.length > 0
// 拒绝文本：dsh 原生语义（不是插件自己 status 词表里的任何一个）。
const sawNativeDenial = logStrings.some((s) =>
  s.includes('the user rejected tool "usine_video_generation"')
  || s.includes('approval for tool "usine_video_generation" was cancelled')
  || s.includes('requires approval'))
// 反向确认：拒绝不是插件的旧 status 词表（工具体内的自问自答已删除）。
const sawLegacyStatus = logStrings.some((s) => s.includes('asked-rejected') || s.includes('asked-unavailable'))

let manifest = null
try { manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) } catch { /* 没挂上 */ }
rmSync(manifestPath, { force: true })
delete process.env.FEUILLE_DSH_MANIFEST

const mod = await import(new URL('./dist/index.mjs', import.meta.url).href)
const expected = [...(mod.toolNames ?? [])].sort()
const got = Array.isArray(manifest?.tools) ? [...manifest.tools].sort() : []
const toolsMatch = expected.length > 0 && got.length === expected.length
  && got.every((n, i) => n === expected[i])

const checks = [
  { name: '插件在真宿主里挂上了（装配清单新鲜 + 工具面 17 个逐字相符）', ok: toolsMatch },
  { name: '模型确实发起了视频 submit（真发起，不是「应该会发起」）', ok: sawToolCall },
  { name: '额度审批走原生 dispatch 层（会话日志里有 approval/asked + approval/decided）', ok: sawApprovalAsked && sawApprovalDecided },
  { name: '没有生成任务被提交（全程无 task_id）', ok: !sawTaskId },
  { name: '拒绝是 dsh 原生语义（不是插件自述的 status）', ok: sawNativeDenial && !sawLegacyStatus },
]

// 证据文件：只留关键事件，别把整条会话流灌进仓库。
const keep = log.filter((e) => {
  const t = e?.type ?? ''
  return t === 'tool/call' || t === 'tool/result' || String(t).startsWith('approval/')
})
mkdirSync(dirname(evidencePath), { recursive: true })
writeFileSync(evidencePath, keep.map((e) => JSON.stringify(e)).join('\n') + '\n')

writeFileSync(summaryPath, JSON.stringify({
  dshPinned: pinned,
  dshRuntime: dshVersion,
  provider: process.env.FEUILLE_DSH_PROVIDER ?? 'minimax',
  model: process.env.FEUILLE_DSH_MODEL ?? 'MiniMax-M3.1-Flash',
  sessionId: result.sessionId,
  toolCount: got.length,
  tools: got,
  sawApprovalAsked,
  sawApprovalDecided,
  sawToolCall,
  sawTaskId,
  sawNativeDenial,
  sawLegacyStatus,
  checks,
  finalResponse: result.finalResponse,
}, null, 2))

for (const c of checks) console.log(`  ${c.ok ? '✓' : '✗'} ${c.name}`)
const bad = checks.filter((c) => !c.ok)
console.log(`[host-run] ${checks.length - bad.length}/${checks.length} 项通过；证据：${evidencePath}`)
if (bad.length > 0) {
  console.error('[host-run] 真宿主证据不完整——见 docs/dsh-host-summary.json')
  process.exit(1)
}
