// persona validate 叶子：薄适配层——判据全在 @feuille/core/persona，
// 这里只把残余 argv 原样交给库入口，退出码口径（有问题 → 1）由库定义。
import { persona } from '@feuille/core'

export function main(argv: string[]): number {
  return persona.mainValidate(argv)
}
