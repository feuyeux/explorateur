// llm_relay.mjs —— 本地中继：把 dsh 的 anthropic 请求转发到**统一配置**里的端点。
//
// 为什么需要它：dsh 走 pi-ai 的 anthropic-messages 适配器，落到
// `<relay>/v1/messages`；上游网关要的是 `<base>/messages` + 自己的凭据。
// 凭据只在**这个进程的内存**里——落盘的 dsh patch 里只有本机 URL 与占位 key。
//
// 端点从**统一配置**（`config/.env`）按 slug 解析，规则与 RSI 侧
// （`garage/run_usine.py::_resolve_endpoints`）一致：
//   slug `fuyao-coding` → 先找 `LLM_FUYAO_CODING_BASE_URL`/`_API_KEY`，
//   找不到就退到组级 `LLM_FUYAO_BASE_URL`/`_API_KEY`（最长前缀优先）。
// 缺任何一个 → **起不来**（fail-closed），不静默用别的端点。
//
// 用法：node llm_relay.mjs --port 0 --slug fuyao-coding --config <path>
// 打印 {"port": N, ...} 到 stdout，然后服务直到 SIGTERM。
//
// ── 推理税（2026-10-20 实测后加的）──────────────────────────────
// 上游是 **带 thinking 的推理模型**。同一条 rollout 里，**19 次慢调用贡献了
// 23.2 分钟里的绝大部分**——每次的 reasoning 块 9.6k–24.1k 字符，而**可见输出
// 只有几百字符**。也就是说：实际耗时的大头花在「模型自己想」上，不在它交付的东西上。
//
// 实测（同一硬任务、同一端点）：
//   默认              94.3s   reasoning 9709 字符
//   budget_tokens=1024 72.8s  reasoning 3537 字符（网关只认 1024/4096，4096 直接 400）
//   thinking: disabled 13.1s  reasoning 0，答案 3548 字符（比默认的 3776 还完整）
//
// ⚠️ **后来实测推翻了这条**：同一个硬任务、同一端点，`thinking:disabled`
// 连测两次是 49.0s / 46.0s，而**不注入**那次是 24.9s——网关只是**不稳定**认这个
// 参数，之前那次「13.1s / reasoning=0」是运气。**默认不注入**（请求体一个字节不改），
// 要试就显式加 `--thinking-off`。真正把实际耗时压下来的是**换协议**（见下）。

import { readFileSync } from 'node:fs'
import { createServer } from 'node:http'

function arg(name, fallback = '') {
  const i = process.argv.indexOf(`--${name}`)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback
}

/** 统一配置：扁平 KEY=VALUE。 */
function entries(path) {
  const out = {}
  for (const raw of readFileSync(path, 'utf-8').split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#') || !line.includes('=')) continue
    const i = line.indexOf('=')
    const k = line.slice(0, i).trim()
    const v = line.slice(i + 1).trim().replace(/^["']|["']$/g, '')
    if (k && v) out[k] = v
  }
  return out
}

/** slug → 端点对（最长前缀优先，组级兜底）。 */
function resolve(slug, cfg) {
  const parts = slug.replace(/[^A-Za-z0-9]/g, '_').toUpperCase().split('_')
  for (let i = parts.length; i > 0; i -= 1) {
    const stem = parts.slice(0, i).join('_')
    const base = cfg[`LLM_${stem}_BASE_URL`]
    const key = cfg[`LLM_${stem}_API_KEY`]
    if (base && key) return { base, key, stem }
  }
  throw new Error(
    `no endpoint for slug ${slug}: fill LLM_${slug.replace(/[^A-Za-z0-9]/g, '_').toUpperCase()}_BASE_URL/_API_KEY ` +
      `or the group pair LLM_${parts[0]}_BASE_URL/_API_KEY`,
  )
}

const CONFIG = arg('config')
const SLUG = arg('slug')
if (!CONFIG || !SLUG) {
  console.error('usage: node llm_relay.mjs --port 0 --slug <slug> --config <path>')
  process.exit(2)
}
const { base, key, stem } = resolve(SLUG, entries(CONFIG))
const UPSTREAM = base.replace(/\/+$/, '')

/**
 * 是否给上游注入 `thinking: {type:'disabled'}`（默认**不注入**）。
 *
 * 实测（同一硬任务、同一端点、同一参数，连测三次）：`thinking:disabled` 那两次
 * 是 49.0s / 46.0s，而**不注入**那次是 24.9s——**网关并不稳定认这个参数**，
 * 之前那次「13.1s / reasoning=0」是运气不是效果。所以默认不动请求体；
 * 要试这个参数就显式加 `--thinking-off`。
 */
const THINKING_OFF = arg('thinking-off') !== ''

/**
 * 给发往上游的 `/messages` 请求体注入 `thinking: {type:'disabled'}`。
 *
 * 只动 `/messages` 的 JSON 体，别的一律原样转发（`/models` 等）。
 * 已经有 `thinking` 字段的请求**不覆盖**——那是显式指定，别人的决定。
 */
function withThinkingOff(path, body, method) {
  if (!THINKING_OFF) return body
  if (method !== 'POST') return body
  if (!/\/messages\/?$/.test(path)) return body
  let payload
  try {
    payload = JSON.parse(body.toString('utf-8'))
  } catch {
    return body
  }
  if (!payload || typeof payload !== 'object') return body
  if (payload.thinking !== undefined) return body
  payload.thinking = { type: 'disabled' }
  return Buffer.from(JSON.stringify(payload), 'utf-8')
}

/**
 * 一次上游请求。**凭据只在内存里**：请求头在发出去的那一刻才拼。
 *
 * 网关两种鉴权都认（`x-api-key` 与 `Authorization: Bearer`），这里发 Bearer。
 */
async function forward(target, req, body, method) {
  return fetch(target, {
    method,
    headers: {
      'content-type': req.headers['content-type'] ?? 'application/json',
      authorization: `Bearer ${key}`,
    },
    body: method === 'GET' || method === 'HEAD' ? undefined : body,
  })
}

const server = createServer((req, res) => {
  const chunks = []
  req.on('data', (c) => chunks.push(c))
  req.on('end', async () => {
    const body = Buffer.concat(chunks)
    // /v1/messages → 上游的 /messages（base 本身以 /v1 结尾，落点就是 /v1/messages）
    const path = (req.url || '/').replace(/^\/v1\//, '/')
    const target = `${UPSTREAM}${path.startsWith('/') ? path : `/${path}`}`
    const outBody = withThinkingOff(path, body, req.method)
    if (process.env.RELAY_DEBUG) {
      console.error(
        `[relay] ${req.method} ${req.url} → ${target} 注入thinking=${outBody !== body}`,
      )
    }
    try {
      const upstream = await forward(target, req, outBody, req.method)
      const ctype = upstream.headers.get('content-type') ?? 'application/json'
      // **流式必须透传**：网关的 `/chat/completions` 走 SSE（实测 200 + 增量 chunk）。
      // 把整个 body 缓冲下来再吐出去，客户端就拿不到「边生成边拿」的语义——
      // 长回答会一直等到生成完才动，实际耗时反而更差。
      if (upstream.body && /text\/event-stream/i.test(ctype)) {
        res.writeHead(upstream.status, { 'content-type': ctype })
        const reader = upstream.body.getReader()
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          res.write(Buffer.from(value))
        }
        res.end()
        return
      }
      const text = await upstream.text()
      res.writeHead(upstream.status, {
        'content-type': ctype,
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
  // **不打印凭据**，只打印端口与端点形状。
  process.stdout.write(JSON.stringify({ port, slug: SLUG, stem, upstream: UPSTREAM }) + '\n')
})
