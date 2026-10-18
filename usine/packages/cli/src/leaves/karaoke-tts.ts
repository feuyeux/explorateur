// karaoke tts 叶子：薄适配层——词级时间线生成全在 @feuille/karaoke gen_tts。
import { gen_tts } from '@feuille/karaoke'

export function main(argv: string[]): Promise<number> {
  return gen_tts.main(argv)
}
