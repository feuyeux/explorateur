// scene draft 叶子：薄适配层——判据与拒绝覆盖口径全在 @feuille/core/scene_draft，
// 这里只把残余 argv 原样交给库入口。
import { scene_draft } from '@feuille/core'

export function main(argv: string[]): number {
  return scene_draft.mainDraft(argv)
}
