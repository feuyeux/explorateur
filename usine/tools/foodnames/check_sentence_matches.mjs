// check_sentence_matches.mjs — **画面句子 == 旁白句**的离线门（纯文本，零浏览器）
//
// 为什么要有这道门
// ----------------
// 2026-10-21 实测的实伤：视频构建器 `build_episode.mjs` 把句子的**第一个 token**
// 无条件替换成词形（为了给菜名上色）。凡���句首不是那个词的语种——冠词、指示词、
// 助词——就被**吃掉**了；如果词本身在句子里还出现一次，就**重复**一遍。
//   法语「Le sushi est un plat japonais」→ 画面渲染成
//   「sushi sushi est un plat japonais」；
//   西语「El sushi es un plato japonés」→ 「sushi es un plato japonés」；
//   希腊语「Το σούσι είναι ιαπωνικό πιάτο」→ 「σούσι είναι…」。
//
// 后果有两条，���者都致命：
//   ① **音画不同步**：配音念的是完整那句，卡拉OK按 token 逐个亮——token 数没变，
//      但每个 token 的**内容**整体错开一词（念「Le」时画面亮的是「sushi」）。
//   ② 画面上的句子语法是坏的，观众看得见。
//
// 为什么必须**离线**：`usine/examples/` 不入库，guest 里没有成片；而且判据要能被
// 合并门禁在**任何**机器上零成本地跑。这道门只做一件事——把场景 HTML 生成出来，
// 把画面上的可见文字抽出来，跟数据里的旁白句逐词比。
//
// 比对口径：去空白 + 去标点。卡拉OK的 token **合法地**丢掉标点（俄语
// 「Суши, японское блюдо」的词边界是「Суши」，见 tools/foodnames/README.md），
// 所以带标点的句子本来就不该逐字相等；比的是**词序与词形**。
//
// 抽可见文字时要去两样不是句子本身的东西：
//   `.annot`        —— 注音层（ㄕㄡ…），挂在字下面
//   `.stack > .top` —— 叠印的上层（辅音蓝/母音透明），**下层 .lay 才是词形**；
//     不去掉的话 ar/he/deva 三个语种的文本会是「词形 ×2」
//
// Usage: node --import tsx tools/foodnames/check_sentence_matches.mjs
//        [--data tools/foodnames/data/ep01-sushi.json] [--all] [--out <临时目录>]
// 退出码：0 全部一致；1 有语种不一致（逐条列出：画面上的 vs 数据里的）。
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const USINE = resolve(here, '..', '..')
const DATA_DIR = join(here, 'data')

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}
const ALL = process.argv.includes('--all')
const ONE = arg('data')

/** 去空白 + 去标点（Unicode 通用标点）。 */
const strip = (s) => (s || '').replace(/[\s\p{P}]/gu, '')

/**
 * 把一段 HTML 的**可见文字**抽出来。
 * 规则：跳过 class 含 'annot' 的元素内容；跳过 class 含 'stack' 的元素里
 * class 含 'top' 的子元素内容（叠印的上层）。其余文本按出现顺序拼接。
 */
function visibleText(html) {
  const tokens = html.match(/<[^>]+>|[^<]+/g) ?? []
  const stack = []
  let out = ''
  for (const t of tokens) {
    if (t.startsWith('</')) {
      stack.pop()
      continue
    }
    if (t.startsWith('<')) {
      const cls = (t.match(/class="([^"]*)"/) ?? [, ''])[1].split(/\s+/).filter(Boolean)
      const skip = cls.includes('annot') || (stack.some((s) => s.cls.includes('stack')) && cls.includes('top'))
      stack.push({ cls, skip })
      continue
    }
    if (stack.some((s) => s.skip)) continue
    out += t
  }
  return out.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
}

/** 从 video_src.html 里抽出每个语种那一句的可见文字。 */
function sentencesFromHtml(html) {
  const out = {}
  const chunks = html.split(/(?=<section class="scene")/)
  for (const chunk of chunks) {
    const m = /data-lang="([^"]+)"/.exec(chunk)
    if (!m) continue
    const locale = m[1]
    const sm = /<div class="stage">([\s\S]*?)<\/div>\s*<\/div>/.exec(chunk)
    if (!sm) continue
    out[locale] = visibleText(sm[1])
  }
  return out
}

const targets = []
if (ONE) {
  targets.push(resolve(ONE))
} else if (ALL) {
  const { readdirSync } = await import('node:fs')
  for (const f of readdirSync(DATA_DIR).filter((x) => /^ep\d+-.*\.json$/.test(x)).sort()) {
    targets.push(join(DATA_DIR, f))
  }
} else {
  console.error('用法：--data <json> 或 --all')
  process.exit(2)
}

const tmp = mkdtempSync(join(tmpdir(), 'foodnames-sent-'))
const failures = []
let checked = 0
try {
  for (const dataPath of targets) {
    const data = JSON.parse(readFileSync(dataPath, 'utf8'))
    const outDir = join(tmp, `ep${String(data.episode).padStart(2, '0')}`)
    // 跑真实的构建器——判据量的是**产物**，不是我们对构建器的猜测
    const r = spawnSync('node', ['--import', 'tsx', join(here, 'build_episode.mjs'), '--data', dataPath, '--out', outDir], {
      cwd: USINE, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
    })
    if (r.status !== 0) {
      failures.push({ file: dataPath, locale: '(build)', screen: `(构建失败 退出码 ${r.status})`, voice: '(未知)' })
      continue
    }
    const html = readFileSync(join(outDir, 'video_src.html'), 'utf8')
    const got = sentencesFromHtml(html)
    for (const w of data.words) {
      checked++
      const voice = strip(w.sentence)
      const screen = strip(got[w.locale] ?? '')
      if (screen !== voice) {
        failures.push({
          file: dataPath.replace(DATA_DIR + '\\', '').replace(DATA_DIR + '/', ''),
          locale: w.locale,
          screen: got[w.locale] ?? '(画面上没有这一句)',
          voice: w.sentence,
        })
      }
    }
  }
} finally {
  rmSync(tmp, { recursive: true, force: true })
}

if (failures.length) {
  console.error(`\n✖ 画面句子与旁白句不一致：${failures.length} 处 / 已查 ${checked} 个语种`)
  for (const f of failures) {
    console.error(`  [${f.file} · ${f.locale}]`)
    console.error(`    画面：${f.screen}`)
    console.error(`    配音：${f.voice}`)
  }
  console.error('\n  典型病因：构建器把句子的第一个 token 无条件替换成了词形——')
  console.error('  句首是冠词/指示词/助词的语种，那个词被吃掉，词本身还会重复一遍。')
  console.error('  修法：给词形上色要落在**句中真正是它的那个 token** 上，不要动 token 序列本身。')
  process.exit(1)
}
console.log(`✓ 画面句子与旁白句逐词一致（已查 ${checked} 个语种 / ${targets.length} 期数据）`)
