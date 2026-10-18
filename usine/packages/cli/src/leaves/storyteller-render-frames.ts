// storyteller render-frames 叶子：薄适配层——幕帧渲染全在 @feuille/storyteller render_act_frames。
import { render_act_frames } from '@feuille/storyteller'

export function main(argv: string[]): Promise<number> {
  return render_act_frames.main(argv)
}
