// toolnames.ts —— 工具面的**外部契约**：智能体应当能调用的工具名单。
//
// 为什么是字面量而不是从代码派生：派生的话「少了一个工具」这件事永远查不出来
// （名单和实现同源，一起漂）。这里写死 17 个名字，门禁拿它对账：
// - 插件 apply 期自检：实际注册的名单必须与这里逐字相同，少一个就抛（宿主启动即红）；
// - preflight：真宿主起得来后读插件写的清单，比对这里 + 比对新鲜度；
// - parity 测试：tools.ts 的 action 枚举 ↔ @feuille/cli 的 COMMANDS 路由表 ↔ 本名单。
//
// usine_publish 不在名单里：它默认**不注册**（config.publish === true 才挂）——
// 发布不可达是有意设计，名单里出现它就等于宣称「智能体随时能发布」。
export const TOOL_NAMES = [
  'usine_version',
  'usine_scene',
  'usine_lesson',
  'usine_persona',
  'usine_cover',
  'usine_framehash',
  'usine_ledger',
  'usine_theme',
  'usine_copy',
  'usine_bgm',
  'usine_karaoke',
  'usine_poetry',
  'usine_poster',
  'usine_storyteller',
  'usine_verify',
  'usine_quota',
  'usine_video_generation',
] as const

export type ToolName = (typeof TOOL_NAMES)[number]
