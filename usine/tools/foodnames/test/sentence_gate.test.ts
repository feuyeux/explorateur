// sentence_gate.test.ts — **D1 回归闸**（画面句子 == 配音念的那句）
//
// 为什么要有这条测试
// ----------------
// 2026-10-21 实测的实伤：视频构建器把句子的**第一个 token** 无条件替换成词形，
// 于是冠词/助词被吃掉、词本身重复一遍（fr/es/el 各 11–12 期、ko 9 期、ar 6 期、
// ja 3 期、de 1 期，合计 54/144 个语种-期组合画面与配音对不上）。
// 修法（`wordSpan()`：在 token 序列里**定位**词形，只给那一段上色，序列一个不动）
// 是 2026-10-21 由 RSI 波次自己写出来的。
//
// **回归测试必须走真实路径。** 这里不重新实现一遍判定逻辑（重实现的断言只能证明
// 「我重写的那份逻辑自洽」），而是直接跑那道离线门——它跑的是真实构建器，
// 把生成的画面文字抽出来跟数据里的旁白句逐词比：
//
//     node --import tsx tools/foodnames/check_sentence_matches.mjs --data <数据文件>
//
// 为什么只挑三期（不是全 12 期）：一条测试的实测耗时是 6s/期，全跑要 72s——
// 合并门禁每多 30s 就多一份「跑不完」的风险。挑的三期各带一类**不同**的坑：
//
//   · ep01-sushi   —— 12 个语种全在（每一种书写体系都过一遍），且含 fr/es/el 的
//                     冠词形态（词不在 token 0 的典型形态）；
//   · ep04-tomato  —— 韩语**融合音节**（토，走 `.cv` 渐变而不是实测补丁）；
//   · ep06-curry   —— 韩语「카레는」这种**词缀在 token 内部**的形态。
//
// 其余各期的形态在 ep01/ep04/ep06 里都有同构的代表；真的新增一种形态时，
// 这里必须补一期——那正是这条测试存在的理由。
import { describe, expect, test } from 'vitest'
import { spawnSync } from 'node:child_process'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/** tools/foodnames/test → usine 根（pnpm-workspace.yaml 所在层）。 */
const USINE = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
const GATE = join(USINE, 'tools', 'foodnames', 'check_sentence_matches.mjs')

const EPISODES = ['ep01-sushi', 'ep04-tomato', 'ep06-curry']

describe('D1：画面句子与配音句逐词一致（真实构建器 → 离线门）', () => {
  for (const ep of EPISODES) {
    test(
      `${ep}：check_sentence_matches 退出码 0`,
      () => {
        const r = spawnSync(
          process.execPath,
          ['--import', 'tsx', GATE, '--data', join(USINE, 'tools', 'foodnames', 'data', `${ep}.json`)],
          { cwd: USINE, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 },
        )
        expect(
          r.status,
          `画面句子与旁白句不一致：\n${(r.stderr || r.stdout || '').slice(-2000)}`,
        ).toBe(0)
      },
      120_000,
    )
  }
})
