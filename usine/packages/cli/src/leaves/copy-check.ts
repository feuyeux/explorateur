// copy/check 叶子：薄适配层——实现在 @feuille/copy checkPublishCopy。
import { checkPublishCopy } from '@feuille/copy'

export function main(argv: string[]): Promise<number> | number {
  return checkPublishCopy.main(argv)
}
