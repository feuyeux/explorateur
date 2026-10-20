// video.ts —— 视频生成线的机械契约（纯函数，判定源）。
//
// 单一事实源：审批门（gate.ts）与工具体（tools.ts）都从这里取「这次提交合不合法、
// 要花多少、审批卡上写什么」。门与工具体分开算同一件事就会漂——所以不许任何一处
// 另写一份（纪律 7：属性一律派生，不手抄）。
//
// 积分费率来自 skills/video-generation/SKILL.md 的速查表（1000 积分 = ¥7）；
// Hailuo 走套餐额度不烧积分，H3 / H3-Max 按分辨率每秒计费。parity 测试从 SKILL.md
// 读回这些数值驱动对账，对不上当场红。

export const VIDEO_MODELS = ['MiniMax-Hailuo-2.3', 'MiniMax-H3', 'MiniMax-H3-Max'] as const
export type VideoModel = (typeof VIDEO_MODELS)[number]

/** 一条合法的提交请求（字段已校验过类型与取值）。 */
export interface SubmitRequest {
  model: VideoModel
  prompt: string
  duration: number
  resolution: string
  ratio?: string
  reference_urls?: string[]
}

/** 提交解析结果：要么拿到合法请求，要么拿到一句可直接回给模型的拒绝理由。 */
export type SubmitParse = { ok: true; req: SubmitRequest } | { ok: false; reason: string }

/** 每秒积分；Hailuo 走套餐额度 → null（不烧积分）。 */
export function creditsPerSecond(model: VideoModel, resolution: string): number | null {
  if (model === 'MiniMax-Hailuo-2.3') return null
  if (model === 'MiniMax-H3') return resolution === '2K' ? 114 : 71
  return 47 // H3-Max（480P）
}

/** 选线合法性（SKILL 前置输入契约的机械面）：不合规格当场拒绝，不进审批。 */
export function validateRequest(
  model: VideoModel,
  duration: number,
  resolution: string,
  ratio: string | undefined,
  prompt: string,
): string | null {
  if (model === 'MiniMax-Hailuo-2.3') {
    if (!['768P', '1080P'].includes(resolution)) return 'Hailuo-2.3 只支持 768P / 1080P'
    if (resolution === '1080P' && duration !== 6) return 'Hailuo-2.3 1080P 只有 6s'
    if (resolution === '768P' && ![6, 10].includes(duration)) return 'Hailuo-2.3 768P 只有 6s / 10s'
  } else if (model === 'MiniMax-H3') {
    if (!['768P', '2K'].includes(resolution)) return 'H3 只支持 768P / 2K'
    if (!Number.isInteger(duration) || duration < 4 || duration > 15) return 'H3 时长是 4–15s 整数'
    if (!ratio) return 'H3 文本生视频要显式给 ratio（画幅）'
  } else {
    if (!['480P', '768P'].includes(resolution)) return 'H3-Max 只支持 480P / 768P'
    if (!Number.isInteger(duration) || duration < 5 || duration > 15) return 'H3-Max 时长是 5–15s 整数'
  }
  if (prompt.length > 7000) return `prompt 上限 7000 字符（当前 ${prompt.length}）`
  return null
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/**
 * 解析一次 submit 调用：字段齐、类型对、规格合，才算一条合法请求。
 * 不合法 → 给理由（模型该改参再调），不合法就不该占用一次人工审批。
 */
export function parseSubmit(args: unknown): SubmitParse {
  if (!isRecord(args)) return { ok: false, reason: 'submit 参数不是对象' }
  const { model, prompt, duration, resolution, ratio, reference_urls } = args
  if (typeof model !== 'string' || !(VIDEO_MODELS as readonly string[]).includes(model)) {
    return { ok: false, reason: `model 必须是 ${VIDEO_MODELS.join(' / ')} 之一` }
  }
  if (typeof prompt !== 'string' || !prompt) return { ok: false, reason: 'submit 需要 prompt' }
  if (typeof duration !== 'number' || !Number.isFinite(duration)) {
    return { ok: false, reason: 'submit 需要 duration（秒，整数）' }
  }
  if (typeof resolution !== 'string' || !resolution) return { ok: false, reason: 'submit 需要 resolution' }
  if (ratio !== undefined && typeof ratio !== 'string') return { ok: false, reason: 'ratio 必须是字符串' }
  if (reference_urls !== undefined && !Array.isArray(reference_urls)) {
    return { ok: false, reason: 'reference_urls 必须是数组' }
  }
  const req: SubmitRequest = {
    model: model as VideoModel,
    prompt,
    duration,
    resolution,
    ...(typeof ratio === 'string' ? { ratio } : {}),
    ...(Array.isArray(reference_urls) ? { reference_urls: reference_urls.map(String) } : {}),
  }
  const invalid = validateRequest(req.model, req.duration, req.resolution, req.ratio, req.prompt)
  if (invalid) return { ok: false, reason: invalid }
  return { ok: true, req }
}

/** 预估消耗的一行文案（审批卡与工具输出共用）。 */
export function submitCost(req: SubmitRequest): string {
  const rate = creditsPerSecond(req.model, req.resolution)
  const nRefs = req.reference_urls?.length ?? 0
  if (rate === null) return '套餐额度（不烧积分）'
  const credits = rate * req.duration
  const yuan = ((credits * 7) / 1000).toFixed(2)
  return `约 ${credits} 积分（≈¥${yuan}）${nRefs ? '；含参考视频则按同价另计一份时长费' : ''}`
}

/** 审批卡正文（中文，给操作员看；模型侧的英文版见 submitReasonEn）。 */
export function submitReason(req: SubmitRequest): string {
  const rate = creditsPerSecond(req.model, req.resolution)
  const nRefs = req.reference_urls?.length ?? 0
  return [
    '[视频生成提交审批] 母版生产，一次生成后冻结',
    `模型：${req.model}${rate === null ? '（走 Token/M Plan 套餐额度，不烧积分）' : '（只扣积分，不吃套餐额度）'}`,
    `提示词：${req.prompt}`,
    `画幅：${req.ratio ?? '（未给，Hailuo 不需要）'}｜时长：${req.duration} 秒｜分辨率：${req.resolution}`,
    nRefs ? `参考素材：${nRefs} 件` : '参考素材：无',
    `预估消耗：${submitCost(req)}`,
  ].join('\n')
}

/** 审批卡正文的英文版（displayReason.en；宿主按 locale 取，缺 en 会回退到空）。 */
export function submitReasonEn(req: SubmitRequest): string {
  const rate = creditsPerSecond(req.model, req.resolution)
  const nRefs = req.reference_urls?.length ?? 0
  return [
    '[Video generation approval] Master asset — generated once, then frozen.',
    `Model: ${req.model}${rate === null ? ' (plan quota, no credits burned)' : ' (credits only)'}`,
    `Prompt: ${req.prompt}`,
    `Ratio: ${req.ratio ?? '(not given, Hailuo does not need it)'} | Duration: ${req.duration}s | Resolution: ${req.resolution}`,
    nRefs ? `References: ${nRefs}` : 'References: none',
    `Estimated cost: ${submitCost(req)}`,
  ].join('\n')
}
