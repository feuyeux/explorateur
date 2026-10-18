// karaoke build 叶子：薄适配层——状态帧渲染与成片组装全在 @feuille/karaoke build_video。
import { build_video } from '@feuille/karaoke'

export function main(argv: string[]): Promise<number> {
  return build_video.main(argv)
}
