// cover check 叶子：薄适配层——判据与退出码口径（有问题 → 1）都在
// @feuille/core/covers，这里只把残余 argv 原样交给库入口。
import { covers } from '@feuille/core'

export function main(argv: string[]): Promise<number> {
  return covers.mainCheck(argv)
}
