// poster assemble 叶子：薄适配层——实现在 @feuille/poster assemble。
import { assemble } from '@feuille/poster'

export function main(argv: string[]): Promise<number> | number {
  return assemble.main(argv)
}
