export * from "./matte.js"
export * from "./draw.js"
// pildraw 的 RGB 与 draw.ts 的 RGB 同形但各是本地声明——star 混出会歧义，
// 这里按名显式再导出（P5-7d storyteller 包要吃 createPilDraw 画舞台层）。
export { createPilDraw } from "./pildraw.js"
export type { Box, DrawOpts, PilDraw, Pt, RGBA } from "./pildraw.js"
