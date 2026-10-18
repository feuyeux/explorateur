// ledger status 叶子：薄适配层——判据全在 @feuille/core/ledger，
// 这里只把残余 argv 原样交给库入口，退出码口径（有过期 → 1）由库定义。
import { ledger } from '@feuille/core'

export function main(argv: string[]): number {
  return ledger.mainStatus(argv)
}
