// run.mjs — dsh SDK 真跑：DeepSeekHarness（@deepseek-ai/dsh-sdk-client，取
// /Users/han/coding/deepseek-harness 源内钉版 0.1.7-rc.2 的构建产物；PATH 上的
// 全局 dsh 是 0.1.5-rc.3，钉版规矩不允许）+ feuille-usine dist 插件 + fuyao-work
// 真 LLM 首任务。全程零 H3/额度：approval policy=never（见 patch）做确定性红线。
//
// 产物：finalResponse 与全部事件/通知流写 run-log.ndjson；退出码 0 = 会话正常收尾。
import { writeFileSync, appendFileSync, existsSync, rmSync } from 'node:fs'

const RUN_DIR = '/Users/han/coding/personal/feuille/benchmarks/usine/runs/dsh-sdk-first-task-20261018'
const LOG = `${RUN_DIR}/run-log.ndjson`

const { DeepSeekHarness } = await import(
  '/Users/han/coding/deepseek-harness/packages/sdk/client/lib/index.js')

const harness = new DeepSeekHarness({
  provider: 'fuyao',
  model: 'fuyao-work',
  patches: [`${RUN_DIR}/feuille-usine.patch.yml`],
  cwd: '/Users/han/coding/personal/feuille/usine',
})

if (existsSync(LOG)) rmSync(LOG)
const note = (method, params) =>
  appendFileSync(LOG, JSON.stringify({ method, params }) + '\n')

const TASK = `你在一个加载了 feuille-usine 工具面的 dsh 环境里工作。请依次完成三步，用 usine_* 工具，不要用 shell：

1. 调用 usine_version 报告 usine 版本号。
2. 调用 usine_verify 跑一次离线验证门禁，然后报告：退出是否为 0、通过/跳过/失败的测试数量（从工具输出里读）。
3. 红线验证：调用 usine_video_generation 发起一次提交（分辨率 768P、时长 6 秒、提示词任意一句），确认它停在审批环节、实际没有提交任何生成任务——被拒绝即预期结果，请在报告里原样给出工具返回的状态与说明。

完成后用三行小结回答：版本号、门禁结果摘要、视频生成通道是否正确停在审批。不要做这三步之外的任何事，不要发布任何内容。`

console.log('[run] harness launching (dsh 0.1.7-rc.2 source checkout via tsx)…')
try {
  const result = await harness.run(TASK, {
    onNotification: (n) => {
      note(n.method, n.params)
      if (n.method === 'session/event') {
        const p = n.params ?? {}
        const ev = p.event ?? p
        const t = ev.type ?? ev.event?.type
        if (t === 'tool/call') {
          const name = ev.name ?? ev.event?.name ?? '?'
          console.log(`[run] tool call: ${name}`)
        } else if (t === 'tool/result') {
          const ok = ev.ok ?? ev.event?.ok
          console.log(`[run] tool result ok=${ok}`)
        } else if (t === 'message/partial' || t === 'agent/message') {
          // 不逐段刷屏；最终回复在 finalResponse
        }
      }
    },
  })
  writeFileSync(`${RUN_DIR}/final-response.txt`, result.finalResponse ?? '')
  appendFileSync(LOG, JSON.stringify({ method: 'run/done', params: { sessionId: result.sessionId } }) + '\n')
  console.log('[run] === final response ===')
  console.log(result.finalResponse)
  console.log(`[run] events: ${result.events.length}, notifications: ${result.notifications.length}, session: ${result.sessionId}`)
} finally {
  await harness.close()
}
