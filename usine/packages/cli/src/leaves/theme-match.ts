// theme match 叶子：薄适配层——匹配逻辑与 CLI 口径全在 @feuille/core/themes
// （skills/match_theme.py 升包后的唯一实现），这里只把残余 argv 原样交接。
import { themes } from '@feuille/core'

export function main(argv: string[]): number | Promise<number> {
  return themes.main(argv)
}
