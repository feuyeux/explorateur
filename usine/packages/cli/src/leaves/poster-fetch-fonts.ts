// poster fetch-fonts 叶子：薄适配层——实现在 @feuille/poster fetch_fonts。
import { fetch_fonts } from '@feuille/poster'

export function main(argv: string[]): Promise<number> | number {
  return fetch_fonts.main(argv)
}
