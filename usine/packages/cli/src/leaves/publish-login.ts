// publish login 叶子：薄适配层——业务全在 @feuille/publish/login。
// 按原样镜像 Python 侧 cli.py 的调用形态 `fn(argv) if argv else fn()`：
// login(names=None) 的 names 参数只在**确有残余 argv**时才传——
// 因此 `feuille publish login --status` 并不会传成 names=['--status']，
// 而是走 login(argv) 把 '--status' 当平台名报「未知平台」。这个怪癖
// 是 Python 侧的既有行为，迁移按原样保留（要改另立议题）。
import { login } from '@feuille/publish'

export async function main(argv: string[]): Promise<number> {
  // Python: return fn(argv) if argv else fn()
  return argv.length ? login.login(argv) : login.login()
}
