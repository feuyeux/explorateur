// music/align 叶子：薄适配层——实现在 @feuille/music align。
import { align } from '@feuille/music'

export function main(argv: string[]): Promise<number> | number {
  return align.main(argv)
}
