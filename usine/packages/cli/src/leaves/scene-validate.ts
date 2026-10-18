// scene validate 叶子：薄适配层——判据全在 @feuille/core/scene_schema，
// 退出码口径（不合规 → 1）由库定义。
import { scene_schema } from '@feuille/core'

export function main(argv: string[]): number {
  return scene_schema.mainValidate(argv)
}
