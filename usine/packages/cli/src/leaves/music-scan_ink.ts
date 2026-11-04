// music/scan_ink 叶子：薄适配层——实现在 @feuille/music scan_ink。
import { scan_ink } from '@feuille/music'

export function main(argv: string[]): Promise<number> | number {
  return scan_ink.main(argv)
}
