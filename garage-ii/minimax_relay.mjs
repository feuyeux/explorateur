// minimax_relay.mjs —— 本地中继：把 dsh 的 anthropic 请求转成 MiniMax 运行时认的那一路。
//
// 为什么需要它（实测出来的，不是猜的）：
//
//   - MiniMax 运行时那个端点**只认** `Authorization: Bearer <oauth token>`；只发
//     `x-api-key` 会得到 401「token is required」。
//   - 但 pi-ai 的 anthropic 适配器**只**在 key 形如 `sk-ant-oat*` 时才走 Bearer，
//     否则一律当 apiKey 发成 `x-api-key`。
//   - 于是「dsh 直连」怎么摆都不对：走 apiKeyEnv → 401；只挂 header → pi-ai 报
//     「Provider is not configured」。
//   - 把两样都带上（apiKey + Bearer header）能过鉴权，但平台**按 x-api-key 的有无
//     选路**，于是落到没配的 direct route 上：503 `direct_route_not_configured`。
//
// 所以这一层做的是最笨也最可靠的事：**把 x-api-key 摘掉，把 Authorization 换上**。
//
// 它顺带解决了一个安全问题：token 只活在**这个进程的内存**里，
// 落盘的 dsh patch 里只有一个本地 URL 与一个占位 key——**凭据不进磁盘**。
//
// 用法：
//   node minimax_relay.mjs --port 0 --print-port
//   # 打印 {"port": N} 到 stdout，然后服务直到 SIGTERM。

import { readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { homedir } from 'node:os'
import { join } from 'node:path'

const AUTH = join(homedir(), '.minimax', 'auth', 'prod', 'cn', 'mcode-public', 'auth.json')
const CONFIG = join(homedir(), '.minimax', 'config.yaml')

function arg(name, fallback = '') {
  const i = process.argv.indexOf(`--${name}`)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback
}

/** 每次请求现读一次 token：运行时会自己刷新它，刷新后的新 token 立刻生效。 */
function accessToken() {
  const data = JSON.parse(readFileSync(AUTH, 'utf-8'))
  for (const rec of Object.values(data.records ?? {})) {
    if (rec?.accessToken) return String(rec.accessToken)
  }
  throw new Error('no accessToken in the MiniMax auth store')
}

function upstreamBase() {
  const m = readFileSync(CONFIG, 'utf-8').match(/baseURL:\s*(\S+)/)
  if (!m) throw new Error('no baseURL in the MiniMax config')
  return m[1].trim().replace(/^["']|["']$/g, '')
}

const UPSTREAM = upstreamBase()

/**
 * 一次上游请求。**遇到 401 会重读 token 再试**。
 *
 * 为什么：运行时会自己刷新 OAuth token，而刷新会让**旧 token 立刻作废**。
 * 中继每次请求现读文件，但在「应用刚刷新完、平台还没放行新 token」那个窗口里，
 * 会读到一枚已经被作废的旧值——上游回 401。2026-10-20 实测：在一次 sweep 的
 * 合成阶段撞上过，整轮演化因此静默退化成「用基准树当最终结果」。
 *
 * 所以 401 不是致命错误：等一下、重读、重试。重试仍失败才把错误交给调用方。
 */
async function forward(target, req, body, method) {
  let last = null
  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (attempt > 0) await new Promise((r) => setTimeout(r, 1500 * attempt))
    const upstream = await fetch(target, {
      method,
      headers: {
        'content-type': req.headers['content-type'] ?? 'application/json',
        // 只留这一种凭据形式——平台按 x-api-key 的有无选路
        authorization: `Bearer ${accessToken()}`,
      },
      body: method === 'GET' || method === 'HEAD' ? undefined : body,
    })
    if (upstream.status !== 401) return upstream
    last = upstream
    // 401：吃掉响应体，重读 token 再试
    await upstream.text()
  }
  return last
}

const server = createServer((req, res) => {
  const chunks = []
  req.on('data', (c) => chunks.push(c))
  req.on('end', async () => {
    const body = Buffer.concat(chunks)
    // /v1/messages → 上游的 /messages
    const path = (req.url || '/').replace(/^\/v1\//, '/')
    const target = `${UPSTREAM}${path.startsWith('/') ? path : `/${path}`}`
    try {
      const upstream = await forward(target, req, body, req.method)
      const text = await upstream.text()
      res.writeHead(upstream.status, {
        'content-type': upstream.headers.get('content-type') ?? 'application/json',
      })
      res.end(text)
    } catch (err) {
      res.writeHead(502, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ error: { message: `relay: ${err.message}` } }))
    }
  })
})

server.listen(Number(arg('port', '0')), '127.0.0.1', () => {
  const { port } = server.address()
  process.stdout.write(JSON.stringify({ port, upstream: UPSTREAM }) + '\n')
})
