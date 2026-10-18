// poetry audio-profile 叶子：薄适配层——业务全在 @feuille/poetry/audio_profile。
import { audio_profile } from '@feuille/poetry'

export function main(argv: string[]): number {
  return audio_profile.main(argv)
}
