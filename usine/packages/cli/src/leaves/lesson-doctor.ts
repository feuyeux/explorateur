// lesson doctor 叶子：薄适配层——七层体检与下一条命令全在
// @feuille/core/lesson，这里只把残余 argv 原样交给库入口。
import { lesson } from '@feuille/core'

export function main(argv: string[]): number | Promise<number> {
  return lesson.mainDoctor(argv)
}
