// poster render-page 叶子：薄适配层——实现在 @feuille/poster render_page。
// dump/render 两活都在 render_page（叶子透传子命令）。
import { render_page } from '@feuille/poster'

export function main(argv: string[]): Promise<number> | number {
  return render_page.main(argv)
}
