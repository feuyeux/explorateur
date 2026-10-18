// karaoke verify-sync 叶子：薄适配层——AV 同步验收全在 @feuille/karaoke verify_sync。
import { verify_sync } from '@feuille/karaoke'

export function main(argv: string[]): Promise<number> {
  return verify_sync.main(argv)
}
