// poetry color-contrast 叶子：薄适配层——业务全在 @feuille/poetry/color_contrast。
import { color_contrast } from '@feuille/poetry'

export function main(argv: string[]): Promise<number> {
  return color_contrast.main(argv)
}
