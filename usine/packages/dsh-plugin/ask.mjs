// ask.mjs —— feuille 智能体的对话入口：dsh harness 的宿主对话框。
//
// 「说」的地方就是本脚本的标准输入。装配链全部走定义，零机器路径：
//   - dsh 运行时与 SDK 由本包 package.json 的 @deepseek-ai/* 发布版依赖解析；
//   - 插件由 ask.cordis.yml overlay 装配（insert → dist/index.mjs 插件面）；
//   - 凭据只写环境变量名（FUYAO_API_KEY），dsh 从 $DSH_HOME 凭据店解析。
//
// 用法（dist 未产出时先 `pnpm --filter @feuille/dsh-plugin build`）：
//   pnpm --filter @feuille/dsh-plugin ask --preflight   # 零 LLM 预检：产物自足 + 宿主起得来 + 插件真的挂上去了
//   pnpm --filter @feuille/dsh-plugin ask 自检          # 单发一句
//   pnpm --filter @feuille/dsh-plugin ask              # 交互：逐行说，Ctrl-D/Ctrl-C 退出
//
// 红线承载（不是客套话）：ask.cordis.yml 里 approval policy=never——花额度的
// 生成提交结构性停摆（视频生成卡在 dispatch 层的审批门上，工具不会执行）；
// usine_publish 默认不注册。本入口不碰发布、不碰 H3。
import { createInterface } from 'node:readline'
import { readFileSync, rmSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DeepSeekHarness } from '@deepseek-ai/dsh-sdk-client'

import { MINIMAX_KEY_HINT, resolveMinimaxCredentials } from './credentials.mjs'

const here = fileURLToPath(new URL('.', import.meta.url))
const require = createRequire(import.meta.url)

// 凭据：MiniMax 平台 key 注入**进程环境**（dsh 的凭据服务从环境取，key 不进仓库）。
// 显式设了别的 provider/model（FEUILLE_DSH_PROVIDER）就不必找 MiniMax 的 key。
const wantsMiniMax = (process.env.FEUILLE_DSH_PROVIDER ?? 'minimax') === 'minimax'
if (wantsMiniMax && !resolveMinimaxCredentials()) {
  console.error(MINIMAX_KEY_HINT)
  process.exit(1)
}

/** 造一个宿主（入口对话与预检共用同一条装配链）。 */
function makeHarness() {
  return new DeepSeekHarness({
    cwd: resolve(here, '../..'), // usine 工作区根（相对本文件，零机器路径）
    provider: process.env.FEUILLE_DSH_PROVIDER ?? 'minimax',
    model: process.env.FEUILLE_DSH_MODEL ?? 'MiniMax-M3.1-Flash',
    patches: [resolve(here, 'ask.cordis.yml')],
  })
}

/** 预检结论：每条一行，最后给一个总判定。 */
const checks = []
function check(name, ok, detail) {
  checks.push({ name, ok, detail })
  console.log(`${ok ? '  ✓' : '  ✗'} ${name}${detail ? ` —— ${detail}` : ''}`)
}

/** 钉版口径：本包 package.json 钉的 dsh SDK 版本。 */
function pinnedDshVersion() {
  const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'))
  return pkg.dependencies['@deepseek-ai/dsh-sdk-client'] ?? ''
}

/** 宿主实际会跑的 dsh runtime 版本（由 SDK 客户端解析出的那份）。 */
function resolvedDshVersion() {
  try {
    const sdkPkg = require.resolve('@deepseek-ai/dsh-sdk-client/package.json')
    const dshPkg = require.resolve('@deepseek-ai/dsh/package.json', { paths: [sdkPkg] })
    return JSON.parse(readFileSync(dshPkg, 'utf8')).version
  } catch {
    return '(解析不到)'
  }
}

/**
 * 零 LLM 装配预检：四道机械检查，缺一道即非零退出。
 *
 * 为什么不能只「start 一下就 close」：dsh 静默吞 apply 错误——插件没挂上时宿主照常
 * 启动，工具面却全空（2026-10-18 真宿主实录：模型对着零工具面开始乱发 shell）。
 * 所以预检必须核到「插件真的挂上去了」这一层，判据是插件自己写的装配清单
 * （FEUILLE_DSH_MANIFEST 指定的路径），与产物里导出的工具面契约逐字比对。
 */
async function preflight() {
  console.log('[preflight] 零 LLM 装配预检')
  let failed = false

  // 1. 产物自足：dist/index.mjs 在纯 node 下能独立 import（不靠 globalThis 垫片）。
  let contract = []
  try {
    const mod = await import(new URL('./dist/index.mjs', import.meta.url).href)
    contract = Array.isArray(mod.toolNames) ? mod.toolNames : []
    check('构建产物自足加载（纯 node，无需 require 垫片）', contract.length > 0,
      `工具面契约 ${contract.length} 个`)
  } catch (e) {
    check('构建产物自足加载（纯 node，无需 require 垫片）', false, e?.message ?? String(e))
  }

  // 2. 钉版：宿主实际跑的 dsh runtime 版本 == package.json 钉的版本。
  const pinned = pinnedDshVersion()
  const resolved = resolvedDshVersion()
  check('dsh 钉版一致（宿主 runtime 版本 == package.json 钉版）', !!pinned && resolved === pinned,
    `钉 ${pinned} / 实际 ${resolved}`)

  // 3. 宿主起得来 + 4. 插件真的挂上去了（装配清单新鲜且名单逐字相符）。
  const manifestPath = join(tmpdir(), `feuille-usine-dsh-manifest-${process.pid}.json`)
  process.env.FEUILLE_DSH_MANIFEST = manifestPath
  const harness = makeHarness()
  try {
    await harness.start()
    check('宿主起得来（harness start）', true)
  } catch (e) {
    check('宿主起得来（harness start）', false, e?.message ?? String(e))
    failed = true
  }

  let manifest = null
  try {
    manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
  } catch {
    // 清单缺失 = 插件没挂上（或写清单那步炸了）
  }
  const got = Array.isArray(manifest?.tools) ? manifest.tools : []
  const same = contract.length > 0 && got.length === contract.length
    && [...got].sort().every((n, i) => n === [...contract].sort()[i])
  check('插件真的挂上去了（装配清单新鲜且工具面逐字相符）', same,
    manifest ? `已注册 ${got.length} 个：${got.join(' / ')}` : '没有装配清单——插件没挂上')

  await harness.close().catch(() => {})
  rmSync(manifestPath, { force: true })
  delete process.env.FEUILLE_DSH_MANIFEST

  const bad = checks.filter((c) => !c.ok)
  if (bad.length > 0) {
    console.error(`[preflight] 装配预检未过：${bad.length}/${checks.length} 项红`)
    process.exit(1)
  }
  console.log(`[preflight] 全部 ${checks.length} 项通过 —— 产物自足 + 钉版一致 + 宿主起得来 + 插件挂上（零 LLM）`)
}

const harness = makeHarness()

// 事件流精简转写：工具调用一行一条（assistant 文本收尾时由 finalResponse 打出）。
// 形状按 2026-10-18 dsh 真跑 wire 实录：method `session.event`，
// event.type `assistant/message`，content 块 `{type:"tool-call",name,...}`。
const onNotification = (n) => {
  if (n.method !== 'session.event') return
  const event = n.params?.event
  if (event?.type !== 'assistant/message') return
  for (const block of event.data?.message?.content ?? []) {
    if (block?.type === 'tool-call') process.stdout.write(`  [工具] ${block.name}\n`)
  }
}

try {
  if (process.argv[2] === '--preflight') {
    await preflight()
  } else {
    await harness.start()

    const session = harness.session()
    const say = async (text) => {
      const r = await session.run(text, { onNotification })
      console.log(r.finalResponse || '(本轮无回复文本)')
    }

    const words = process.argv.slice(2)
    if (words.length) {
      await say(words.join(' '))
    } else {
      console.log('feuille @ dsh —— 逐行输入，Ctrl-D / Ctrl-C 退出')
      const rl = createInterface({ input: process.stdin })
      for await (const line of rl) {
        if (!line.trim()) continue
        await say(line)
      }
    }
    await harness.close()
  }
} catch (err) {
  console.error(`[ask] ${err?.message ?? err}`)
  process.exitCode = 1
  await harness.close().catch(() => {})
}
