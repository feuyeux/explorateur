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
    projects: [
      {
        test: {
          name: 'unit',
          include: ['packages/*/test/**/*.test.ts'],
          exclude: [...EDGE_FILES, '**/node_modules/**', '**/dist/**'],
        },
      },
      {
        test: {
          name: 'edge',
          include: EDGE_FILES,
          pool: 'forks',
          poolOptions: { forks: { singleFork: true } },
        },
      },
    ],
  },
})
