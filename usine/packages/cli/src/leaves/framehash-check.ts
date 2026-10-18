// framehash check 叶子：薄适配层——零漂移门禁，diff/gone → 退出码 1
// （判据与退出码口径都在 @feuille/core/framehash.mainCheck）。
import { framehash } from '@feuille/core'

export function main(argv: string[]): number {
  return framehash.mainCheck(argv)
}
