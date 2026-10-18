// poster render 叶子：薄适配层——实现在 @feuille/poster render_poster。
import { render_poster } from '@feuille/poster'

export function main(argv: string[]): Promise<number> | number {
  return render_poster.main(argv)
}
