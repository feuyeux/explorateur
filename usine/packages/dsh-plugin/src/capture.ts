// capture.ts —— 进程内 main 调用的输出捕获。
//
// 各包的 main(argv) 沿 CLI 口径把人类可读输出打到 console.log/console.error、
// 把退出码当返回值。dsh 工具要把两者都变成结构化结果（exit_code + output）
// 返回给模型，所以这里在调用期间拦截 console 四个出口（log/error 与
// stdout/stderr.write 双保险——子模块口径不一，两个都要盖）。
//
// 全局拦截天然与并行工具调用竞态，所以 main 调用串行化：一次只有一个
// main 在捕获窗口内跑。产线 main 本来就是重 IO 单线程步骤，串行无损。

type MainFn = (argv: string[]) => Promise<number> | number

let lock: Promise<unknown> = Promise.resolve()

/** 串行 + 捕获地跑一个包内 main；退出码口径与 CLI 一致（0/1/2），异常按叶子层惯例折成 1 + 报错文本。 */
export async function runMain(fn: MainFn, argv: string[]): Promise<{ exit_code: number; output: string }> {
  const prev = lock
  let release: () => void = () => {}
  lock = new Promise<void>((r) => (release = r))
  await prev

  const chunks: string[] = []
  const put = (s: string) => {
    chunks.push(s)
    return true
  }
  const cap = (...a: unknown[]) => put(a.length === 1 && typeof a[0] === 'string' ? a[0] : a.join(' ') + '\n')
  const oLog = console.log
  const oErr = console.error
  const oOut = process.stdout.write.bind(process.stdout)
  const oErrW = process.stderr.write.bind(process.stderr)
  console.log = cap as typeof console.log
  console.error = cap as typeof console.error
  process.stdout.write = put as unknown as typeof process.stdout.write
  process.stderr.write = put as unknown as typeof process.stderr.write
  try {
    let exit_code: number
    try {
      const rc = await fn(argv)
      exit_code = typeof rc === 'number' ? rc : 1
    } catch (e) {
      // 叶子层惯例：FeuilleError 等异常在 CLI 入口折成 stderr + rc 1，
      // 这里同一口径——报错文本进 output，不往 dsh 抛（工具结果要能被模型读到）。
      const msg = e instanceof Error ? e.message : String(e)
      put(msg.endsWith('\n') ? msg : msg + '\n')
      exit_code = 1
    }
    return { exit_code, output: chunks.join('') }
  } finally {
    console.log = oLog
    console.error = oErr
    process.stdout.write = oOut
    process.stderr.write = oErrW
    release()
  }
}
