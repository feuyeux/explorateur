// playwright.d.ts — playwright 可选依赖的 ambient 声明。
//
// 发布包**不把 playwright 写进静态依赖**（lazy 契约：主环境没装也能 import 本包，
// 报「缺 playwright」而不是「未知命令」），所以这里没有真实类型可引——
// 全包 page/ctx 一律 any，运行时经函数内 `await import('playwright')` 动态加载，
// 未安装时该动态 import 抛错（显式报缺）。
declare module 'playwright'
