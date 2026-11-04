// music/probe 叶子：薄适配层——实现在 @feuille/music probe。
import { probe } from '@feuille/music'

export function main(argv: string[]): Promise<number> | number {
  return probe.main(argv)
}
