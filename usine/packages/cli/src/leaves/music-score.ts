// music/score 叶子：薄适配层——实现在 @feuille/music score。
import { score } from '@feuille/music'

export function main(argv: string[]): Promise<number> | number {
  return score.main(argv)
}
