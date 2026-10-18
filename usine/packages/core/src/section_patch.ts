// section_patch.ts — 按 `### NN · 语种` 边界整节替换发布文案（幂等）
// （section_patch.py 的 TS 移植）
//
// 路径参数化；节头时长字段可选——与 manifest._SEC 同口径，两版文案体例都吃。
//
// 为什么不用行号区间（三个真实事故换来的）：
//  · RTL 文本（阿拉伯语/希伯来语）从终端/编辑器复制会被双向算法重排，
//    字符串匹配必然失配；
//  · 前面多轮编辑会让行号漂移；
//  · 「从 .bak 恢复」曾把上一轮的改动整个冲掉。
// 按节标题定位与行号无关，整节写死，重复执行结果一致（幂等）。
import { readFileSync, writeFileSync } from "node:fs"

import { FeuilleError } from "./errors.js"

const SEC = /^### (\d+) · (\S+) `([^`]+)`(?: · (\d\d):(\d\d))?\s*$/

/** 返回 {order: 该节完整文本（不含下一节的标题行）}。 */
export function splitSections(text: string): Record<string, string> {
  const lines = text.split("\n")
  const starts: { i: number; order: string }[] = []
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i]!.match(SEC)
    if (m) starts.push({ i, order: m[1]! })
  }
  const out: Record<string, string> = {}
  for (let n = 0; n < starts.length; n++) {
    const end = n + 1 < starts.length ? starts[n + 1]!.i : lines.length
    out[starts[n]!.order] = lines.slice(starts[n]!.i, end).join("\n").replace(/\n+$/, "")
  }
  return out
}

/** 整节替换（幂等：重复执行结果一致）。找不到节 = 当场报错。 */
export function replace(path: string, newSections: Record<string, string>): void {
  const text = readFileSync(path, "utf8")
  const name = path.split("/").pop() ?? path
  const secs = splitSections(text)
  for (const [order, body] of Object.entries(newSections)) {
    if (!(order in secs)) throw new FeuilleError(`${name} 找不到第 ${order} 节`)
    secs[order] = body.replace(/\n+$/, "")
  }
  const orders = Object.keys(secs).sort((a, b) => Number(a) - Number(b))
  if (!text.split("\n").some((l) => SEC.test(l))) {
    throw new FeuilleError(`${name} 里没有任何节头（体例被改了？）`)
  }
  // Python 侧 head_end 取 `SEC.match(line).start()`——^ 锚定恒为 0，即首节
  // 之前的前言实际被丢弃（实测行为：输出以 \n\n 开头，历史产物皆然）。
  // 按原样镜像，不「顺手修正」——行为漂移本身就是 parity 破坏。
  const body = orders.map((o) => secs[o]).join("\n\n") + "\n"
  writeFileSync(path, "\n\n" + body, "utf8")
}
