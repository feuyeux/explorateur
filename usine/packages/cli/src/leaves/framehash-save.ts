// framehash save 叶子：薄适配层——发现产物 → 逐支采像素哈希 → 分桶落盘，
// 采完回读自证（坑㉞ 纪律内建在 @feuille/core/framehash.mainSave）。
import { framehash } from '@feuille/core'

export function main(argv: string[]): number {
  return framehash.mainSave(argv)
}
