// publish bilibili 叶子：薄适配层——业务全在 @feuille/publish/bilibili，
// 这里只把残余 argv 原样交给 main（manifest 参数解析在 base.manifestArgs）。
import { bilibili } from '@feuille/publish'

export function main(argv: string[]): Promise<number> {
  return bilibili.main(argv)
}
