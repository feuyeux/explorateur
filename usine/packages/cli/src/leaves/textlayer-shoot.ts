// textlayer shoot 叶子：薄适配层——渲染与测量都在 @feuille/core/textlayer，
// 这里只把残余 argv 原样交给库入口。
import { textlayer } from '@feuille/core'

export function main(argv: string[]): Promise<number> {
  return textlayer.mainShoot(argv)
}
