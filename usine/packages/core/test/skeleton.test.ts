import { describe, expect, it } from 'vitest'
import { VERSION } from '../src/index.js'

describe('@feuille/core 骨架', () => {
  it('入口可导入，版本号非空', () => {
    expect(VERSION).toMatch(/^\d+\.\d+\.\d+$/)
  })
})
