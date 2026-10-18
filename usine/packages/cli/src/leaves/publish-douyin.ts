// publish douyin 叶子：薄适配层——业务全在 @feuille/publish/douyin，
// 这里只把残余 argv 原样交给 main（manifest 参数解析在 base.manifestArgs）。
import { douyin } from '@feuille/publish'

export function main(argv: string[]): Promise<number> {
  return douyin.main(argv)
}
