// karaoke check-edges 叶子：薄适配层——帧边缘溢出判定全在 @feuille/karaoke check_edges。
import { check_edges } from '@feuille/karaoke'

export function main(argv: string[]): Promise<number> {
  return check_edges.main(argv)
}
