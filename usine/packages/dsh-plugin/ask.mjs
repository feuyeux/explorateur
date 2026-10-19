// ask.mjs —— feuille 智能体的对话入口：dsh harness 的宿主对话框。
//
// 「说」的地方就是本脚本的标准输入。装配链全部走定义，零机器路径：
//   - dsh 运行时与 SDK 由本包 package.json 的 @deepseek-ai/* 发布版依赖解析；
//   - 插件由 ask.cordis.yml overlay 装配（insert entry-loader.mjs → dist/index.mjs）；
//   - 凭据只写环境变量名（FUYAO_AI_GATEWAY_API_KEY），dsh 从 $DSH_HOME 凭据店解析。
//
// 用法（dist 未产出时先 `pnpm --filter @feuille/dsh-plugin build`）：
//   pnpm --filter @feuille/dsh-plugin ask --preflight   # 零 LLM 预检：宿主起得来、插件加载成功
//   pnpm --filter @feuille/dsh-plugin ask 自检          # 单发一句
//   pnpm --filter @feuille/dsh-plugin ask              # 交互：逐行说，Ctrl-D/Ctrl-C 退出
//
// 红线承载（不是客套话）：ask.cordis.yml 里 approval policy=never——花额度的
// 生成提交结构性停摆；usine_publish 默认不注册。本入口不碰发布、不碰 H3。
import { createInterface } from 'node:readline'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DeepSeekHarness } from '@deepseek-ai/dsh-sdk-client'

const here = fileURLToPath(new URL('.', import.meta.url))
const harness = new DeepSeekHarness({
  cwd: resolve(here, '../..'), // usine 工作区根（相对本文件，零机器路径）
  provider: process.env.FEUILLE_DSH_PROVIDER ?? 'fuyao-ai-gateway',
  model: process.env.FEUILLE_DSH_MODEL ?? 'fuyao-work',
  patches: [resolve(here, 'ask.cordis.yml')],
})

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
  await harness.start()

  if (process.argv[2] === '--preflight') {
    await harness.close()
    console.log('[preflight] harness started & closed clean —— SDK 运行时 + 插件加载 OK（零 LLM）')
    process.exit(0)
  }

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
} catch (err) {
  console.error(`[ask] ${err?.message ?? err}`)
  process.exitCode = 1
  await harness.close().catch(() => {})
}
