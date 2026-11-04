// music/source-batch 叶子：薄适配层——实现在 @feuille/music source.batchMain。
import { source } from '@feuille/music'

export function main(argv: string[]): Promise<number> | number {
  return source.batchMain(argv)
}
