// credentials.mjs —— 本机凭据解析（key 不进仓库、不落日志、不打印）。
//
// dsh 的 apiKeyEnv 解析顺序是「凭据店 → 进程环境 → .env」（dsh-credentials 的
// CredentialProvider 语义）。所以只要把 key 放进**宿主进程的环境变量**就能用，
// 不必改用户的 dsh 凭据店。
//
// 本机 MiniMax 平台 key 的出处是 mmx CLI 自己的凭据店（`~/.mmx/config.json`，
// 或 $MMX_CONFIG_DIR 指定的目录）——那本来就是这台机器上调用 MiniMax 的入口，
// 仓库里的 `usine_quota` 工具走的也是同一个 mmx。
//
// 优先级：① 已有环境变量 MINIMAX_API_KEY → ② mmx 凭据店 → ③ 失败（说清怎么配）。
import { existsSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

/** MiniMax 平台按区域分端点：cn → api.minimaxi.com，global → api.minimax.io。 */
const REGION_BASE = {
  cn: 'https://api.minimaxi.com',
  global: 'https://api.minimax.io',
}

/** mmx CLI 的凭据目录（与 mmx 自身约定一致：$MMX_CONFIG_DIR 或 ~/.mmx）。 */
function mmxConfigPath() {
  const dir = process.env.MMX_CONFIG_DIR ?? join(homedir(), '.mmx')
  return join(dir, 'config.json')
}

/** 读 mmx 凭据店（只取需要的字段，不打印）。 */
function readMmxCredentials() {
  const p = mmxConfigPath()
  if (!existsSync(p)) return null
  try {
    const d = JSON.parse(readFileSync(p, 'utf8'))
    if (typeof d.api_key === 'string' && d.api_key) {
      return { apiKey: d.api_key, region: typeof d.region === 'string' ? d.region : 'global' }
    }
  } catch {
    // 凭据店坏了就当没有——上层会给出可执行的修法。
  }
  return null
}

/**
 * 解析 MiniMax key 并注入宿主环境。
 * @returns {{apiKey: string, baseUrl: string}|null} null = 没找到 key。
 */
export function resolveMinimaxCredentials() {
  const envKey = process.env.MINIMAX_API_KEY
  const fromMmx = envKey ? null : readMmxCredentials()
  const apiKey = envKey ?? fromMmx?.apiKey
  if (!apiKey) return null
  const region = fromMmx?.region ?? process.env.MINIMAX_REGION ?? 'global'
  const base = REGION_BASE[region] ?? REGION_BASE.global
  const baseUrl = `${base}/v1`
  // 宿主子进程继承环境——dsh 的凭据服务会从进程环境里取到。
  process.env.MINIMAX_API_KEY = apiKey
  process.env.FEUILLE_DSH_MINIMAX_BASE_URL = baseUrl
  return { apiKey, baseUrl }
}

/** 没找到 key 时给操作员看的修法（不含任何密钥内容）。 */
export const MINIMAX_KEY_HINT = [
  '没找到 MiniMax 凭据。两条路（任选其一）：',
  '  1) 导出环境变量：export MINIMAX_API_KEY=<你的平台 key>（dsh 的凭据服务会从进程环境取）',
  '  2) 用 mmx CLI 登录一次（凭据落在 ~/.mmx/config.json，本脚本会从那里读）：mmx auth login',
].join('\n')
