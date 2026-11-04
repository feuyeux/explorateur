// music/source 叶子：薄适配层——实现在 @feuille/music source。
import { source } from '@feuille/music'

export function main(argv: string[]): Promise<number> | number {
  return source.main(argv)
}
