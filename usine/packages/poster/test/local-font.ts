// local-font.ts — 门禁用「本机真字体」夹具（不是 mock 字体）。
//
// 为什么需要它：poster 的两条 e2e（fetch_fonts 联网取子集 / measure-korean 用
// 该子集量字形）原先都真打 fonts.googleapis.com。结果 `pnpm verify` 的健康度
// 取决于「今天 Google Fonts 通不通」——2026-11-06 实测同一个提交在 10s 超时下
// 直接 ConnectTimeout，整条门禁变红，而代码一行没改。纪律 12 明写这属禁止：
// 验收入口不许长得像环境可用性测试。
//
// 解法不是把这两条删掉（它们覆盖的是真能力），而是**把「取字体」与「量字形」
// 拆成两条独立的轴**：
// - `fetch_fonts` 加 fetch 接缝 → 门禁注入假 fetch 覆盖 url 构造/解析/base64/
//   改名这套真逻辑；真网络另有一条 `FEUILLE_LIVE=1` 的 LIVE 用例。
// - `measure_korean` 只吃一份 fonts.css，根本不联网 → 门禁直接喂**本机真 TTF**
//   的 data URI。渲字、取墨、连通域、classify、emitRule、verify 全是真跑，
//   一个字都没打折；换的只是字形来源。
//
// 为什么用系统字体而不是 repo 内捆绑：一个能覆盖谚文音节的 TTF 在 4–17 MB，
// 绑进仓库是给每个克隆加一份二进制；而本夹具只要求「一个真能渲 차 的字体」，
// 系统上必然有（macOS AppleSDGothicNeo / Linux NotoSansCJK / Windows malgun）。
// 一台都没有 = 这台机器渲不出谚文，那 measure-korean 本来就该跳过。
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 已知的、能渲染谚文的系统字体路径，按平台排优先级。
 *
 * 只放**确定存在过的**路径；找不到就返回 null 让调用方跳过（不猜、不退化到
 * 「随便一个字体」——渲不出韩文的字体量出来的字形是错的，而错字形照样能生成
 * 一条语法正确的 CSS 规则，那是最坏的一种通过）。
 */
export const KOREAN_FONT_CANDIDATES: readonly string[] = [
  // Windows
  'C:/Windows/Fonts/malgun.ttf',
  // macOS
  '/System/Library/Fonts/AppleSDGothicNeo.ttc',
  '/Library/Fonts/AppleGothic.ttf',
  // Linux（Debian/Ubuntu 的 noto-cjk、Arch 的 noto-fonts-cjk）
  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
  '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
  '/usr/share/fonts/opentype/noto/NotoSansKR-Regular.otf',
]

/** 找到第一个真实存在的谚文字体；没有 → null（调用方据此跳过，不许兜底）。 */
export function koreanFontPath(): string | null {
  for (const p of KOREAN_FONT_CANDIDATES) {
    if (existsSync(p)) return p
  }
  return null
}

/** 按扩展名推 CSS format() 关键字（ttc/otf 都是 OpenType 容器，浏览器按 truetype/opentype 认）。 */
function cssFormatOf(path: string): string {
  const ext = path.slice(path.lastIndexOf('.') + 1).toLowerCase()
  if (ext === 'woff2') return 'woff2'
  if (ext === 'woff') return 'woff'
  if (ext === 'otf' || ext === 'ttc') return 'opentype'
  return 'truetype'
}

/**
 * 把本机字体写成一份 `@font-face` 的 fonts.css（data URI 内嵌，浏览器可直接读）。
 *
 * 返回 family 名与 css 路径；没有可用字体时返回 null。
 */
export function writeLocalFontCss(
  dir: string,
  family = 'LOCAL KR',
): { family: string; cssPath: string; fontPath: string } | null {
  const fontPath = koreanFontPath()
  if (fontPath === null) return null
  const b64 = readFileSync(fontPath).toString('base64')
  const fmt = cssFormatOf(fontPath)
  const css = `@font-face {
  font-family: '${family}';
  font-style: normal;
  font-weight: 400;
  src: url(data:font/${fmt};base64,${b64}) format('${fmt}');
}
`
  const cssPath = join(dir, 'fonts.css')
  writeFileSync(cssPath, css, 'utf-8')
  return { family, cssPath, fontPath }
}
