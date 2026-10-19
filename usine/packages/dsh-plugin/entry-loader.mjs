// entry-loader.mjs —— dsh 入口通道与 dist 插件之间的 require 互操作垫片（机器无关）。
//
// 为什么需要它：dsh 的入口加载器走 Node 原生 ESM 通道，ESM 模块作用域里
// `typeof require === "undefined"`；而 dsh-plugin 的 esbuild 产物（dist/index.mjs）
// 内联了 __require shim，运行期要真 require 它未打包的 CJS 依赖（yazl 等）——
// 原生 ESM 下直接抛 "Dynamic require of ... is not supported"（vitest 里有
// CJS interop，测试一直是绿的，只有真宿主首次加载才暴露）。
//
// 垫片即插件入口：以本文件旁的 dist/ 为解析根挂 globalThis.require（未打包的
// CJS 依赖从 usine 工作区 node_modules 解析），再 re-export 插件面。对 dsh 而言
// 这是普通插件模块，overlay 的 insert 指本文件而非 dist。
import { createRequire } from 'node:module'

if (typeof globalThis.require === 'undefined') {
  globalThis.require = createRequire(new URL('./dist/', import.meta.url))
}

const plugin = await import(new URL('./dist/index.mjs', import.meta.url).href)

export const name = plugin.name
export const inject = plugin.inject
export const apply = plugin.apply
export const usineRoot = plugin.usineRoot
