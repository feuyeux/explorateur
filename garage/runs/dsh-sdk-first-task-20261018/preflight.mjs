// 零 LLM 成本预检：只把 harness 拉起来（boot 期完成 profile 加载、patch 叠加、
// 插件 import、17 工具注册）再关掉。插件 import 若炸（require 互操作问题）在这里
// 就能看到，不烧任何 token。
const { DeepSeekHarness } = await import(
  '/Users/han/coding/deepseek-harness/packages/sdk/client/lib/index.js')
const h = new DeepSeekHarness({
  provider: 'fuyao',
  model: 'fuyao-work',
  patches: ['/Users/han/coding/personal/feuille/benchmarks/usine/runs/dsh-sdk-first-task-20261018/feuille-usine.patch.yml'],
  cwd: '/Users/han/coding/personal/feuille/usine',
})
await h.start()
console.log('[preflight] harness started — profile + patch + plugin import OK')
await h.close()
console.log('[preflight] closed clean')
