// clock.ts — time.sleep / time.time 的落点（发布包内唯一睡眠实现）
//
// 单独成模块而不是散在各函数里直接 setTimeout：verify 门禁要断言「发布 → 歇
// between_s → 发布」的事件序列（缺陷①：节流必须写在循环内），vi.mock 整模块
// 即可记录事件，不必给业务函数加测试专用的注入参数。
export function sleep(seconds: number): Promise<void> {
  return new Promise((r) => setTimeout(r, seconds * 1000))
}

/** time.time() 口径：Unix 秒（浮点）。 */
export function now(): number {
  return Date.now() / 1000
}
