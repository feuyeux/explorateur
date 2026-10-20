// dsh_run.mjs —— garage-ii 的 dsh 执行器桥：跑一次 rollout，把证据落盘。
//
// 为什么走 **SDK 客户端**而不是 `dsh --profile headless`：
//
//  1. **工具面**。headless 剖面只装 `@deepseek-ai/dsh-base` + `dsh-headless`，**没有**
//     feuille-usine 插件——智能体会对着零工具面发 shell（2026-10-18 真宿主首测实录）。
//     SDK 走 `patches:` 装配，插件面是显式声明的。
//  2. **轨迹**。`--json` 事件流是后加的（PATH 上的 dsh 0.1.5-rc.3 就没有），而 SDK 的
//     `session.event` 通知在**所有版本**上都有，且带 `tool/call` 与 `tool/result`。
//     harness2 的行为对比要的就是这个。
//  3. **装配证据**。插件 apply 成功后写装配清单（`FEUILLE_DSH_MANIFEST`）——
//     「插件真的挂上了」是可机检的事实，不是散文。
//
// 用法（机器无关；路径全从参数来）：
//   node dsh_run.mjs --cwd <工作区> --task-file <题面文件> --out <产物目录> \
//                    --patch <patch.yml> --provider <p> --model <m>
//
// 退出码：0=会话正常收尾；1=装配或运行失败（诊断在 stderr 与 out/diagnostics.json）。

import { mkdirSync, readFileSync, writeFileSync, existsSync, rmSync, createWriteStream } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '..')
const PLUGIN_PKG = join(REPO, 'usine', 'packages', 'dsh-plugin', 'package.json')

/** 从 dsh-plugin 包解析 dsh SDK —— 钉版跟插件走，不跟 PATH 上的全局 dsh 走。 */
const requireFromPlugin = createRequire(PLUGIN_PKG)
const SDK_ENTRY = requireFromPlugin.resolve('@deepseek-ai/dsh-sdk-client')
const PLUGIN_DIST = join(REPO, 'usine', 'packages', 'dsh-plugin', 'dist', 'index.mjs')

function arg(name, fallback = '') {
  const i = process.argv.indexOf(`--${name}`)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback
}

const cwd = resolve(arg('cwd'))
const taskFile = resolve(arg('task-file'))
const out = resolve(arg('out'))
const patchFile = resolve(arg('patch'))
const provider = arg('provider')
const model = arg('model')

mkdirSync(out, { recursive: true })

if (!existsSync(PLUGIN_DIST)) {
  console.error(
    `[dsh_run] 插件产物不在 ${PLUGIN_DIST}：先跑 ` +
      `pnpm --filter @feuille/dsh-plugin build`,
  )
  process.exit(1)
}

const manifestPath = join(out, 'assembly-manifest.json')
process.env.FEUILLE_DSH_MANIFEST = manifestPath

const { DeepSeekHarness } = await import(SDK_ENTRY)

const events = []
const notifications = []
let harness
// 事件流**边跑边落盘**：跑批的 rollout 可能跑十几分钟，一旦超时被杀，
// 「跑完才写」就等于零证据（2026-10-20 实测：一次 900s 超时的 smoke 只剩 exit 124，
// 连轨迹都没有）。改成 append 之后，超时也留得住已经发生的事。
const eventsPath = join(out, 'events.jsonl')
const eventsStream = createWriteStream(eventsPath, { flags: 'w' })
try {
  harness = new DeepSeekHarness({
    cwd,
    provider,
    model,
    patches: [patchFile],
  })
  const task = readFileSync(taskFile, 'utf-8')
  const result = await harness.run(task, {
    onNotification: (n) => {
      notifications.push(n)
      if (n.method !== 'session.event') return
      const ev = n.params?.event ?? n.params
      if (ev) {
        events.push(ev)
        eventsStream.write(JSON.stringify(ev) + '\n')
      }
    },
  })
  await new Promise((resolve) => eventsStream.end(resolve))

  writeFileSync(join(out, 'final.txt'), result.finalResponse ?? '')
  writeFileSync(
    join(out, 'run-meta.json'),
    JSON.stringify(
      {
        sessionId: result.sessionId,
        provider,
        model,
        nEvents: events.length,
        nNotifications: notifications.length,
        finalResponse: result.finalResponse ?? '',
      },
      null,
      2,
    ),
  )
  let manifest = null
  try {
    manifest = JSON.parse(readFileSync(manifestPath, 'utf-8'))
  } catch {
    manifest = null
  }
  writeFileSync(
    join(out, 'assembly.json'),
    JSON.stringify(
      {
        mounted: !!manifest,
        tools: Array.isArray(manifest?.tools) ? manifest.tools : [],
        skills: Array.isArray(manifest?.skills) ? manifest.skills : [],
      },
      null,
      2,
    ),
  )
  console.log(
    `[dsh_run] ok session=${result.sessionId} events=${events.length} ` +
      `tools=${Array.isArray(manifest?.tools) ? manifest.tools.length : 0}`,
  )
  process.exitCode = 0
} catch (err) {
  const diag = {
    error: err?.message ?? String(err),
    stack: err?.stack ? String(err.stack).slice(0, 2000) : '',
    provider,
    model,
  }
  writeFileSync(join(out, 'diagnostics.json'), JSON.stringify(diag, null, 2))
  // 事件流已经在跑的过程中增量落盘了——这里只把流关掉，**不重写**（重写会丢掉
  // 失败时刻之前已经发生的事，那正是超时/崩溃场景里最值钱的证据）。
  await new Promise((resolve) => eventsStream.end(resolve))
  console.error(`[dsh_run] 失败：${diag.error}`)
  process.exitCode = 1
} finally {
  try {
    await harness?.close()
  } catch {
    /* 关不掉也要把证据落盘 */
  }
  try {
    eventsStream.destroy()
  } catch {
    /* 已经关了 */
  }
  rmSync(manifestPath, { force: true })
  delete process.env.FEUILLE_DSH_MANIFEST
}
