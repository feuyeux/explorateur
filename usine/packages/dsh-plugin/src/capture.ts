// capture.ts —— 进程内 main 调用的输出捕获（上下文作用域，不是时间窗）。
//
// 各包的 main(argv) 沿 CLI 口径把人类可读输出打到 console/stdout、把退出码当返回值。
// 工具要把两者变成结构化结果返回给模型，所以这里把一次 main 调用的输出收走。
//
// 为什么不用「猴补 + 时间窗」：dsh 宿主进程里除了工具还有宿主自己的写——会话事件、
// JSON-RPC 帧、日志、UI 帧。时间窗捕获会把宿主的噪声一起吞进工具输出，模型读到
// 不属于它的文本；而 JSON-RPC 帧被吞会直接挂死 SDK 客户端（stdout 是它的独占通道）。
//
// 现在用 AsyncLocalStorage 把捕获窗口绑到「本次 main 调用的异步上下文」：窗口内只有
// 这条调用链的写被收走，宿主并发写原样透传。带来三个直接好处：
// 1. 并发安全——两个工具同时跑不会互相截断，串行锁可以删（那把锁当初只是为了挡
//    「两个捕获窗口重叠」，现在窗口按上下文划分，不重叠）；
// 2. 宿主噪声不进工具输出；
// 3. stdout.write 的猴补只装一次（模块级、幂等），不再是「装上→跑→卸下」的窗口期
//    全局改写——宿主的写永远走原路径。
//
// 捕获口径不变：CLI 口径的 main 打 console/stdout，退出码当返回值；异常按叶子层惯例
// 折成 1 + 报错文本（不往 dsh 抛——工具结果要能被模型读到）。
import { AsyncLocalStorage } from 'node:async_hooks'
import { format } from 'node:util'

type MainFn = (argv: string[]) => Promise<number> | number

/** 一次捕获窗口的收集器（挂在异步上下文上，不在模块全局）。 */
interface Sink {
  chunks: string[]
}

/** 当前捕获窗口；不在窗口内 = undefined（宿主的写原样透传）。 */
const sink = new AsyncLocalStorage<Sink>()

let installed = false

/**
 * 把 console 与 stdout/stderr 的写改道：有窗口就收进窗口，没有就原样写出去
 * （只装一次）。console 与 stream 两个出口都要盖——console.log 走的是
 * process.stdout.write，但在测试宿主（vitest）里 console 被测试框架接管，
 * 压根不经过 stdout.write，只盖一个出口会漏。
 */
function install(): void {
  if (installed) return
  installed = true
  const origOut = process.stdout.write.bind(process.stdout)
  const origErr = process.stderr.write.bind(process.stderr)
  const wrapStream = (orig: typeof origOut) =>
    (chunk: string | Uint8Array, encoding?: BufferEncoding, cb?: (err?: Error | null) => void): boolean => {
      const s = sink.getStore()
      if (!s) return orig(chunk, encoding, cb)
      s.chunks.push(typeof chunk === 'string' ? chunk : Buffer.from(chunk).toString('utf8'))
      if (cb) cb()
      return true
    }
  const wrapConsole = (orig: (...a: unknown[]) => void) =>
    (...a: unknown[]): void => {
      const s = sink.getStore()
      if (!s) { orig(...a); return }
      // 窗口内直接收，不再往下传（否则会被 stream 出口二次收走）。
      s.chunks.push(format(...a) + '\n')
    }
  process.stdout.write = wrapStream(origOut) as typeof process.stdout.write
  process.stderr.write = wrapStream(origErr) as typeof process.stderr.write
  console.log = wrapConsole(console.log.bind(console))
  console.error = wrapConsole(console.error.bind(console))
  // **工具面里没有可用的 stdin**：叶子读到的是**宿主自己的 fd 0**——一根永远不关的
  // 管道。于是「没给文件参数就去读 stdin」的叶子会**永久阻塞**：2026-10-22 实测，
  // `poster fit-diag` 空参调用把 B 线 4 条 rollout 的时间预算全烧在这一个挂起的
  // 工具调用上（最后被上限掐死，量到的全是「工具面挂死」）。
  // 边界层把这件事说清楚：FEUILLE_STDIN=off ⇒ 叶子不许碰 stdin，缺参数就报用法错。
  // **CLI 那条路不变**（管道用法照旧能读 stdin），掐掉的只是工具面这一侧。
  process.env['FEUILLE_STDIN'] = 'off'
}

/**
 * 捕获地跑一个包内 main；退出码口径与 CLI 一致（0/1/2），异常按叶子层惯例折成
 * 1 + 报错文本。返回 {exit_code, output}，由调用方折成统一结果契约。
 */
export async function runMain(fn: MainFn, argv: string[]): Promise<{ exit_code: number; output: string }> {
  install()
  const s: Sink = { chunks: [] }
  return sink.run(s, async () => {
    let exit_code: number
    try {
      const rc = await fn(argv)
      exit_code = typeof rc === 'number' ? rc : 1
    } catch (e) {
      // 叶子层惯例：FeuilleError 等异常在 CLI 入口折成 stderr + rc 1，
      // 这里同一口径——报错文本进 output，不往 dsh 抛（工具结果要能被模型读到）。
      const msg = e instanceof Error ? e.message : String(e)
      s.chunks.push(msg.endsWith('\n') ? msg : msg + '\n')
      exit_code = 1
    }
    return { exit_code, output: s.chunks.join('') }
  })
}
