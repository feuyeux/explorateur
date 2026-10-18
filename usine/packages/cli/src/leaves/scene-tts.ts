// scene tts 叶子：薄适配层——缓存键、台账 extra、落盘键序全在
// @feuille/core/scene_audio，这里只把残余 argv 原样交给库入口。
import { scene_audio } from '@feuille/core'

export function main(argv: string[]): number | Promise<number> {
  return scene_audio.mainTts(argv)
}
