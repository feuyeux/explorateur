// music/narrate 叶子：薄适配层——实现在 @feuille/music narrate。
import { narrate } from '@feuille/music'

export function main(argv: string[]): Promise<number> | number {
  return narrate.main(argv)
}
