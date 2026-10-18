// poster make-covers 叶子：薄适配层——实现在 @feuille/poster make_covers。
import { make_covers } from '@feuille/poster'

export function main(argv: string[]): Promise<number> | number {
  return make_covers.main(argv)
}
