// poster verify-colors 叶子：薄适配层——实现在 @feuille/poster verify_colors。
import { verify_colors } from '@feuille/poster'

export function main(argv: string[]): Promise<number> | number {
  return verify_colors.main(argv)
}
