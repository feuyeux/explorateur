import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['packages/*/test/**/*.test.ts'],
    environment: 'node',
    // 反向验证纪律：一个断言炸了不许静默吞——failFast 关闭但 reporter 列全量
    reporters: ['default'],
    passWithNoTests: false,
  },
})
