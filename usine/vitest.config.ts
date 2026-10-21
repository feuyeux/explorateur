import { defineConfig } from 'vitest/config'

// Edge 并行隔离（P7 落地）：真实驱动浏览器的测试文件单独成 edge project、
// 文件间串行（singleFork：vitest 3.x 的 fileParallelism 是根级选项不可按 project 设，
// 单 fork 池等效实现文件串行）。Edge 并行抖动四批三现——covers / textlayer 超时，
// 加 120s 显式超时后仍偶发，多实例并发抢浏览器进程是已证实的根因；串行化浏览器系
// 文件是根治，其余纯单元文件照常并行、不付串行代价。
// 新增会起浏览器的测试文件必须加进 EDGE_FILES——漏加不报错，但回退到并行抖动。
const EDGE_FILES = [
  'packages/core/test/covers.test.ts',
  'packages/core/test/textlayer.test.ts',
  'packages/karaoke/test/karaoke.test.ts',
  'packages/poster/test/measure_korean.test.ts',
  'packages/poster/test/poster.test.ts',
  'packages/publish/test/publish.test.ts',
  'packages/storyteller/test/storyteller.test.ts',
]

export default defineConfig({
  test: {
    environment: 'node',
    // 反向验证纪律：一个断言炸了不许静默吞——failFast 关闭但 reporter 列全量
    reporters: ['default'],
    passWithNoTests: false,
    // **默认 5000ms 对「按需加载大模块」的用例太紧。**
    //
    // 2026-10-21 实测：`pnpm verify` 全量并行时，同一批测试里
    // `plugin.test.ts`（动态 import `dist/index.mjs`，esbuild 打的 12 包 bundle）
    // 与 `scene_audio.test.ts`（`leaf.load()` 拉整棵 CLI 命令树）**轮流**超时；
    // 单独隔离跑同一个文件 2.9s 全过（24/24）。同一段代码、同一个断言，
    // 差别只在机器当时在同时跑另外 43 个测试文件。
    //
    // 30s 的依据：实测最慢的那条在并行负载下 6.6s，给约 4.5 倍余量。
    // 为什么不再大：超时是**挂死**的兜底，不是性能断言——真挂死的用例
    // 是整进程不返回，30s 足够暴露它，再大只会拖慢失败反馈。
    // 为什么要全局而不是逐条：这是同一类病（按需加载），逐条加会漏——
    // 这次就是修好一处、下一处再犯，两轮才看清是同一个根因。
    testTimeout: 30_000,
    // **`projects[].test` 会覆盖根级配置**——根上的 `testTimeout` 对 project 内的
    // 用例不生效（vitest 3.x 的 project 是独立配置单元，不是根配置的补丁）。
    // 2026-10-21 实测：根级设了 30s，两条动态加载大模块的用例照样在 5000ms 超时。
    // 所以每个 project 都要显式给一次。
    projects: [
      {
        test: {
          name: 'unit',
          include: ['packages/*/test/**/*.test.ts'],
          exclude: [...EDGE_FILES, '**/node_modules/**', '**/dist/**'],
          testTimeout: 30_000,
        },
      },
      {
        test: {
          name: 'edge',
          include: EDGE_FILES,
          pool: 'forks',
          poolOptions: { forks: { singleFork: true } },
          testTimeout: 30_000,
        },
      },
    ],
  },
})
