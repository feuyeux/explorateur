// lesson new 叶子：薄适配层——注册表现取、选角校验、空跑草稿全在
// @feuille/core/lesson，这里只把残余 argv 原样交给库入口。
import { lesson } from '@feuille/core'

export function main(argv: string[]): number | Promise<number> {
  return lesson.mainNew(argv)
}
