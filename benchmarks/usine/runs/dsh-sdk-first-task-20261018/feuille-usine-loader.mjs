// feuille-usine-loader.mjs — dsh 入口树与 dist 插件之间的 require 互操作垫片。
//
// 为什么需要它：dsh 的入口加载器（vendor/loader internal.import）走 Node 原生
// ESM 通道，ESM 模块作用域里 `typeof require === "undefined"`；而
// dsh-plugin 的 esbuild 产物（dist/index.mjs）内联了 __require shim，运行期
// 要真 require 它未打包的 CJS 依赖（yazl 等）——原生 ESM 下直接抛
// "Dynamic require of ... is not supported"（vitest 里有 CJS interop 所以测试
// 一直是绿的，只有真宿主首次加载才暴露——本文件就是那次实测的产物）。
//
// 垫片本身即插件入口：把 createRequire 挂到 globalThis（以 dist 目录为解析
// 根，让未打包的 CJS 依赖从 usine 的 node_modules 解析），再 re-export dist
// 的插件面。对 dsh 而言这是普通插件模块，patch 条目指本文件而非 dist。
import { createRequire } from 'node:module'

if (typeof globalThis.require === 'undefined') {
  globalThis.require = createRequire(
    '/Users/han/coding/personal/feuille/usine/packages/dsh-plugin/dist/')
}

const plugin = await import(
  'file:///Users/han/coding/personal/feuille/usine/packages/dsh-plugin/dist/index.mjs')

export const name = plugin.name
export const inject = plugin.inject
export const apply = plugin.apply
export const usineRoot = plugin.usineRoot
