// bgm/gen 叶子：薄适配层——实现在 @feuille/bgm gen_bgm。
import { gen_bgm } from '@feuille/bgm'

export function main(argv: string[]): Promise<number> | number {
  return gen_bgm.main(argv)
}
