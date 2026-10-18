// scene parse 叶子：薄适配层——判据与落盘口径（pyJsonDump，字节级 parity）全在
// @feuille/core/parse_scene，这里只把残余 argv 原样交给库入口。
import { parse_scene } from '@feuille/core'

export function main(argv: string[]): number {
  return parse_scene.mainParse(argv)
}
