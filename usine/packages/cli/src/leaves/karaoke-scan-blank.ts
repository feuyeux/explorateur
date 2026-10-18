// karaoke scan-blank 叶子：薄适配层——全片白页扫描全在 @feuille/karaoke scan_blank。
import { scan_blank } from '@feuille/karaoke'

export function main(argv: string[]): Promise<number> {
  return scan_blank.main(argv)
}
