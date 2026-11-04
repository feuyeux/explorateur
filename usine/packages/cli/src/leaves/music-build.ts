// music/build 叶子：薄适配层——实现在 @feuille/music build。
import { build } from '@feuille/music'

export function main(argv: string[]): Promise<number> | number {
  return build.main(argv)
}
