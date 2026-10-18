// skills.test.ts — skills/ 的**去歧义**门禁（scripts/verify_skills.py 的 TS 移植）
//
// 仓库里有两个产线（海报驱动 / 实拍驱动），若干 skill 曾各说各话：
// `multilingual-video-poetry` 与 `karaoke-video` 都在 description 里宣称
// 「多语种 + TTS + RTL 排版」却都不说画面从哪来，agent 只能靠猜——
// 于是把「一支铅笔 12 语种视频」路由到了实拍那条线，卡在「母版从哪来」
// 这个**正确路径下根本不该出现**的问题上。
//
// 本套件机检的就是拆掉这些歧义所立的规矩，全部是静态文件检查，**不碰浏览器
// 与成片**（纪律 12：门禁必须能在任何没渲过东西的机器上跑）：
//
// - 每个 SKILL.md 都有 `## 前置输入契约` 与 `## 边界`——缺一条 = 契约丢了
// - 每个 description 都带排除语句（`Not for` / `Do NOT use`）——这是 agent 的路由依据
// - `## 边界` 里转交的 skill 名**必须真实存在**——不许转交幽灵
// - 每个 skill 至少被**另一个 skill 的边界段**引用——不许有孤岛
// - `name:` 字段必须等于目录名——路由表与实现失配
// - 12 语种规范顺序只在 `one-page-poster` 定义——事实源唯一，不许各抄一份
// - 跨 skill 共享的 example 项目数据副本必须逐字节一致——手工同步要有机检兜底
// - README「模块地图」三个小节与 ownership.json 双向对账——手写地图承载账本
//   没有的「谁在用」列，但归属断言必须与账本一致，漂移当场 FAIL
// - ownership.json 记的是 TS 模块（packages/<pkg>/src/**，ID =「包.源文件」），
//   账本 ↔ 磁盘 ↔ SKILL.md「拥有模块：」行三方一致——归属纪律不随语言退役
import { describe, expect, test } from 'vitest'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve4(dirname(fileURLToPath(import.meta.url)))
const SKILLS = join(ROOT, 'skills')
const REQUIRED_SECTIONS = ['## 前置输入契约', '## 边界']
const EXCLUSION_MARKERS = ['not for', 'do not use', '不用', '不适用']

function resolve4(dir: string): string {
  // packages/gate/test → usine 根（pnpm-workspace.yaml 所在层）
  return join(dir, '..', '..', '..')
}

type Row = [boolean, string]

function parseSkill(path: string): [{ name: string; description: string }, string] {
  // 切出 frontmatter 与正文。frontmatter 只解 name/description 两个键。
  // **永远返回两个键**（缺失时为空串）——门禁自己崩溃比门禁 FAIL 更糟：
  // 崩溃会让人以为「环境坏了」而跳过它，FAIL 才会被人修。
  const text = readFileSync(path, 'utf-8')
  const m = text.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/)
  if (!m) return [{ name: '', description: '' }, text]
  const head = m[1]!
  const name = head.match(/^name:\s*(\S+)\s*$/m)
  const dm = head.match(/description:\s*>?\s*\n?([\s\S]*?)(?=\n[a-z_]+:|$)/)
  return [{
    name: name ? name[1]! : '',
    description: dm ? dm[1]!.trim() : '',
  }, m[2]!]
}

function lev(a: string, b: string): number {
  // Levenshtein 距离（拼写比对用，两个短字符串，不讲究性能）。
  if (a.length < b.length) [a, b] = [b, a]
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j)
  for (let i = 1; i <= a.length; i++) {
    const cur = [i]
    for (let j = 1; j <= b.length; j++) {
      cur.push(Math.min(prev[j]! + 1, cur[j - 1]! + 1, prev[j - 1]! + (a[i - 1] !== b[j - 1] ? 1 : 0)))
    }
    prev = cur
  }
  return prev[prev.length - 1]!
}

function skillDirs(): string[] {
  return readdirSync(SKILLS)
    .filter((d) => statSync(join(SKILLS, d)).isDirectory() && existsSync(join(SKILLS, d, 'SKILL.md')))
    .sort()
}

// ---------------------------------------------------------------- 模块宇宙（TS 包）

/** packages/<pkg>/src 下每个源码文件 → 模块 ID「包.相对路径」（桶文件 index.ts 与 *.d.ts 除外）。 */
function actualModules(): Set<string> {
  const out = new Set<string>()
  const pkgsDir = join(ROOT, 'packages')
  const walk = (pkg: string, dir: string) => {
    for (const ent of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, ent.name)
      if (ent.isDirectory()) walk(pkg, p)
      else if (ent.isFile() && ent.name.endsWith('.ts') && !ent.name.endsWith('.d.ts') && ent.name !== 'index.ts') {
        const rel = relative(join(pkgsDir, pkg, 'src'), p).replace(/\.ts$/, '').replaceAll('/', '.')
        out.add(`${pkg}.${rel}`)
      }
    }
  }
  for (const pkg of readdirSync(pkgsDir)) {
    const src = join(pkgsDir, pkg, 'src')
    if (existsSync(src)) walk(pkg, src)
  }
  return out
}

// ---------------------------------------------------------------- 主检查链

function check(): Row[] {
  const rows: Row[] = []
  const dirs = skillDirs()
  const names = new Set(dirs.map((d) => basename(d)))
  const parsed = new Map<string, [{ name: string; description: string }, string]>(
    dirs.map((d) => [basename(d), parseSkill(join(SKILLS, d, 'SKILL.md'))]),
  )

  // ---- 0. 路由表存在，且列出全部 skill ----
  const index = join(SKILLS, 'README.md')
  if (!existsSync(index)) {
    rows.push([false, 'skills/README.md 缺失——没有总路由表，agent 只能靠猜'])
  } else {
    const idx = readFileSync(index, 'utf-8')
    const missing = [...names].filter((n) => !idx.includes(n)).sort()
    rows.push([!missing.length,
      `README.md 路由表覆盖全部 ${names.size} 个 skill`
      + (missing.length ? `　**漏 ${missing}**` : '')])
    // ---- 8. 完成定义：README 有「完整产线」段，四层齐全 ----
    // 没有这张表，“完成”就退化为任务请求的字面边界——碎片任务会静默停在半路。
    const seg = idx.split('## 完整产线')
    const layers = ['画面层', '音频层', '混后验收', '收尾层', '发布执行']
    if (seg.length === 2) {
      const table = seg[1]!.split('\n## ')[0]!
      const miss = layers.filter((l) => !table.includes(l))
      rows.push([!miss.length,
        'README.md 完整产线段四层齐全（完成定义）'
        + (miss.length ? `　**缺 ${miss}**` : '')])
    } else {
      rows.push([false, 'README.md 缺「完整产线」段——没有完成定义，流程会静默截断'])
    }
  }

  // ---- 1. frontmatter 必须可解析（name + description 都非空）----
  for (const name of [...names].sort()) {
    const fm = parsed.get(name)![0]
    const ok = !!fm.name && !!fm.description
    rows.push([ok,
      `${name} 的 frontmatter 可解析（name 与 description 都在）`
      + (ok ? '' : '　**frontmatter 缺字段或分隔符坏了**')])
  }

  // ---- 2. 每个 skill 都有前置输入契约 + 边界 ----
  for (const name of [...names].sort()) {
    const body = parsed.get(name)![1]
    const miss = REQUIRED_SECTIONS.filter((s) => !body.includes(s))
    rows.push([!miss.length,
      `${name} 有「前置输入契约」与「边界」`
      + (miss.length ? `　**缺 ${miss}**` : '')])
  }

  // ---- 3. description 必须带排除语句 ----
  for (const name of [...names].sort()) {
    const desc = parsed.get(name)![0].description.toLowerCase()
    const has = EXCLUSION_MARKERS.some((mk) => desc.includes(mk))
    rows.push([has,
      `${name} 的 description 写明了「不做什么」`
      + (has ? '' : '　**缺排除语句，agent 无从排除**')])
  }

  // ---- 4. 边界里转交的 skill 必须真实存在 ----
  // 只筛 `-video`/`-poster` 等后缀会漏掉 `bgm-bed`、`lesson-scene` 这类
  // 名字的拼错（后缀不在白名单里就静默放行）。改成：反引号里任何
  // 「长得像 skill 名」的 token，与真实名只差 ≤2 个字符就是幽灵。
  for (const name of [...names].sort()) {
    const body = parsed.get(name)![1]
    const seg = body.split('## 边界')
    const ghosts: string[] = []
    if (seg.length === 2) {
      const tail = seg[1]!.split('\n## ')[0]!
      for (const tok of new Set(tail.match(/`([a-z][a-z0-9-]{3,})`/g)?.map((t) => t.slice(1, -1)) ?? [])) {
        if (tok === name || names.has(tok)) continue
        if ([...names].some((n) => lev(tok, n) <= 2)) ghosts.push(tok)
      }
    }
    const g = [...new Set(ghosts)].sort()
    rows.push([!g.length,
      `${name} 边界段里转交的 skill 名没有拼错`
      + (g.length ? `　**疑似幽灵 ${g}（真实名里没有它们）**` : '')])
  }

  // ---- 5. 没有孤岛：每个 skill 都被另一个 skill 的边界段引用 ----
  // 方向必须是「被引用」：只做单向计数。双向对称会把「只提别人、
  // 从没人往它转交」的 skill 也算成有关联——孤岛就测不出来了。
  const referenced = new Map<string, Set<string>>([...names].map((n) => [n, new Set<string>()]))
  for (const src of names) {
    const body = parsed.get(src)![1]
    if (!body.includes('## 边界')) continue
    const tail = body.split('## 边界')[1]!.split('\n## ')[0]!
    for (const tgt of names) {
      if (tgt !== src && tail.includes(tgt)) referenced.get(tgt)!.add(src)
    }
  }
  for (const name of [...names].sort()) {
    const ok = referenced.get(name)!.size > 0
    rows.push([ok,
      `${name} 至少被一个 skill 的边界段引用（来自 ${[...referenced.get(name)!].sort()}）`
      + (ok ? '' : '　**孤岛：谁都不往它转交**')])
  }

  // ---- 6. name 必须等于目录名 ----
  for (const name of [...names].sort()) {
    const declared = parsed.get(name)![0].name
    rows.push([declared === name,
      `${name} 的 frontmatter name 与目录名一致`
      + (declared === name ? '' : `　**声明的是 ${JSON.stringify(declared)}**`)])
  }

  // ---- 7. 12 语种规范顺序只有一个事实源 ----
  const canon = '中 zh'
  const holders = [...names].filter((n) => readFileSync(join(SKILLS, n, 'SKILL.md'), 'utf-8').includes(canon)).sort()
  if (holders.length === 1 && holders[0] === 'one-page-poster') {
    rows.push([true, '12 语种规范顺序只在 one-page-poster 定义'])
  } else if (!holders.length) {
    rows.push([false, '12 语种规范顺序的事实源丢了（one-page-poster 里也没了）'])
  } else {
    rows.push([false, `12 语种规范顺序只在 one-page-poster 定义　**重复定义于 ${holders}**`])
  }

  // ---- 9. 两条成片线的边界必须转交音频层与收尾层 ----
  // 边界段少了这两个转交，链路就断在成片：床和发布词都变成“没人认领的下一步”。
  for (const name of ['karaoke-video', 'multilingual-video-poetry']) {
    if (!names.has(name)) continue
    const seg = parsed.get(name)![1].split('## 边界')
    const tail = seg.length === 2 ? seg[1]!.split('\n## ')[0]! : ''
    const miss = ['bgm-bed', 'publish-copy'].filter((t) => !tail.includes(t))
    rows.push([!miss.length,
      `${name} 边界段转交音频层（bgm-bed）与收尾层（publish-copy）`
      + (miss.length ? `　**缺 ${miss}**` : '')])
  }

  rows.push(...checkSharedExampleAssets())
  rows.push(...checkNoHardcodedBins())
  rows.push(...checkOwnership(names))
  rows.push(...checkReadmeMap())
  return rows
}

// ---------------------------------------------------------------- 归档一致性

function checkSharedExampleAssets(): Row[] {
  // 跨 skill 共享的 example 项目数据副本必须逐字节一致。
  // 手工约定没有机检兜底，改了漏了不会被发现，就成了
  // 「同一事实写在两处各自漂移」。README.md 豁免：各 skill 的 example
  // 目录各说各的事，本来就不该一致。
  const byName = new Map<string, string[]>()
  const walk = (dir: string) => {
    for (const ent of readdirSync(dir, { withFileTypes: true })) {
      if (ent.isDirectory()) {
        if (ent.name !== 'example') walk(join(dir, ent.name))
      } else if (ent.isFile() && ent.name !== 'README.md') {
        const list = byName.get(ent.name) ?? []
        list.push(join(dir, ent.name))
        byName.set(ent.name, list)
      }
    }
  }
  for (const d of skillDirs()) {
    const ex = join(SKILLS, basename(d), 'assets', 'example')
    if (existsSync(ex)) walk(ex)
  }
  const shared = [...byName.entries()].filter(([, ps]) => ps.length > 1)
  const drifted: string[] = []
  for (const [fname, paths] of shared) {
    const first = readFileSync(paths[0]!)
    for (const p of paths.slice(1)) {
      if (Buffer.compare(readFileSync(p), first) !== 0) {
        drifted.push(`${fname}: ${relative(SKILLS, p)} 与 ${relative(SKILLS, paths[0]!)} 不一致`)
      }
    }
  }
  return [[!drifted.length,
    `跨 skill 共享的 example 副本逐字节一致（${shared.length} 组共享文件）`
    + (drifted.length ? `　**漂移 ${drifted}**` : '')]]
}

function checkNoHardcodedBins(): Row[] {
  // skill 的持久脚本不得硬编码外部可执行文件名。
  // 这不是洁癖：`render_poster.sh` 曾写死 `google-chrome`，而 SKILL.md 却写着
  // 「可用 $CHROME_BIN 覆盖」——文档说谎 + 在只有 Edge 的机器上直接失败。
  // 外部可执行文件（浏览器 / ffmpeg / ffprobe / magick）的解析是
  // @feuille/core `platform` 的唯一事实源（AGENTS.md 跨平台硬约定 1），skill
  // 脚本只许调它。`assets/example/` 豁免：那是历史项目的只读归档。
  const hard = /(?<![\w/.-])(google-chrome|chromium|msedge|ffmpeg|ffprobe|magick)(?![\w-])/
  const quoted = /'[^']*'|"[^"]*"/
  const suffixes = new Set(['.sh', '.ts', '.mjs', '.py'])
  const offenders: string[] = []
  const walk = (dir: string) => {
    for (const ent of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, ent.name)
      if (ent.isDirectory()) {
        if (ent.name !== 'example') walk(p)        // assets/example = 历史归档，豁免
      } else if (ent.isFile() && suffixes.has(ent.name.slice(ent.name.lastIndexOf('.')))) {
        const lines = readFileSync(p, 'utf-8').split('\n')
        lines.forEach((ln, i) => {
          const code = ln.trim()
          if (!code || code.startsWith('#') || code.startsWith('//')) return
          // 剥掉引号内的内容：报错文案里提一嘴可执行名不算硬编码
          if (hard.test(quoted[Symbol.replace](code, ''))) {
            offenders.push(`${relative(SKILLS, p)}:${i + 1}`)
          }
        })
      }
    }
  }
  for (const d of skillDirs()) walk(join(SKILLS, basename(d)))
  return [[!offenders.length,
    'skill 持久脚本不硬编码浏览器/ffmpeg/ffprobe/magick 名'
    + '（走 @feuille/core 的 platform resolver；assets/example 归档豁免）'
    + (offenders.length ? `　**硬编码于 ${offenders}**` : '')]]
}

// ---------------------------------------------------------------- ownership 三方对账

type Own = Record<string, unknown>

function ownedLine(skill: string): string | null {
  // 取 SKILL.md「## 代码归属」段里的 `拥有模块：…` 那一行。
  const p = join(SKILLS, skill, 'SKILL.md')
  if (!existsSync(p)) return null
  const body = readFileSync(p, 'utf-8')
  if (!body.includes('## 代码归属')) return null
  const seg = body.split('## 代码归属')[1]!.split('\n## ')[0]!
  for (const ln of seg.split('\n')) {
    if (ln.trim().startsWith('拥有模块：')) return ln.trim()
  }
  return null
}

function checkOwnership(names: Set<string>): Row[] {
  // `ownership.json` 与磁盘、与 SKILL.md 三方一致。
  // 这是「skill 之外不该有业务代码」的机检形态：不是说文件必须搬走，而是
  // **每个模块的归属必须唯一、显式、可查**——搬不搬是第二步，歧义先除掉。
  const rows: Row[] = []
  const opath = join(ROOT, 'ownership.json')
  if (!existsSync(opath)) {
    return [[false, 'ownership.json 缺失——模块归属无事实源，等于没声明']]
  }
  let own: Own
  try {
    own = JSON.parse(readFileSync(opath, 'utf-8')) as Own
  } catch (e) {
    // 门禁自己崩溃比 FAIL 更糟（见 parseSkill 的说明）——坏 JSON 也要出 FAIL 行
    return [[false, `ownership.json 无法解析：${String(e)}`]]
  }
  const skillMap = (own.skills ?? {}) as Record<string, Record<string, string>>
  const library = (own.library ?? {}) as Record<string, string>
  const infra = (own.infrastructure ?? {}) as Record<string, string>
  const unclaimed = (own.unclaimed ?? {}) as Record<string, string>

  // ---- 8. 归属清单里的 owner 必须都是真 skill ----
  const ghosts = Object.keys(skillMap).filter((s) => !names.has(s)).sort()
  rows.push([!ghosts.length,
    `ownership.json 里 ${Object.keys(skillMap).length} 个 owner 都是真 skill`
    + (ghosts.length ? `　**幽灵 ${ghosts}**` : '')])

  // ---- 8b. 存量必须消化完：unclaimed 为空 ----
  rows.push([!Object.keys(unclaimed).length,
    '存量代码全部消化完（unclaimed 为空）'
    + (Object.keys(unclaimed).length
      ? `　**仍有 ${Object.keys(unclaimed).length} 个无主：${Object.keys(unclaimed).sort()}**`
      : '')])

  // ---- 9. 每个真实模块都能归到唯一归属（子模块随声明走，最长前缀唯一）----
  const modOwned = new Set(Object.values(skillMap).flatMap((mods) => Object.keys(mods)))
  const declared = new Set([...modOwned, ...Object.keys(library), ...Object.keys(infra), ...Object.keys(unclaimed)])
  const actual = actualModules()
  const orphans: string[] = []
  const ambiguous: [string, string[]][] = []
  for (const m of [...actual].sort()) {
    const cands = [...declared].filter((d) => m === d || m.startsWith(d + '.'))
    if (!cands.length) orphans.push(m)
    else if (new Set(cands.map((c) => c.length)).size > 1) ambiguous.push([m, cands.sort()])
  }
  rows.push([!orphans.length,
    `${actual.size} 个模块全部有归属声明`
    + (orphans.length ? `　**无主 ${orphans}**` : '')])
  rows.push([!ambiguous.length,
    '没有模块同时落进两个归属（最长前缀唯一）'
    + (ambiguous.length ? `　**撞车 ${ambiguous}**` : '')])

  // ---- 10. 声明的必须真实存在（不许幽灵归属）----
  const phantom = [...declared].filter(
    (d) => ![...actual].some((a) => a === d || a.startsWith(d + '.')),
  ).sort()
  rows.push([!phantom.length,
    `${declared.size} 条归属声明都能在磁盘上找到模块`
    + (phantom.length ? `　**幽灵 ${phantom}**` : '')])

  // ---- 11. unclaimed 必须写明原因，否则等于没声明 ----
  const noReason = Object.keys(unclaimed).filter((k) => !String(unclaimed[k]).trim()).sort()
  rows.push([!noReason.length,
    `${Object.keys(unclaimed).length} 个 unclaimed 模块都写了原因`
    + (noReason.length ? `　**缺原因 ${noReason}**` : '')])

  // ---- 12. 每个 skill 的 SKILL.md 必须声明它拥有的模块（双向）----
  // 约定：`拥有模块：a, b` 这一行是机检读的那一份，正文其余部分随便写
  // （否则散文里出现的跨用模块名会被误判成归属）。
  const mism: [string, string][] = []
  for (const [sk, mods] of Object.entries(skillMap)) {
    const line = ownedLine(sk)
    if (line === null) {
      mism.push([sk, '没有「拥有模块：」行'])
      continue
    }
    // 「（无）」必须是整行载荷；「（无）, audio」这种混写要报格式错
    const payload = line.includes('：') ? line.split('：')[1]!.trim() : ''
    let listed: Set<string>
    if (payload === '（无）') listed = new Set()
    else {
      listed = new Set(payload.split(',').map((x) => x.trim().replace(/[` ]/g, '')).filter(Boolean))
      // 畸形行必须当场报错，而不是和清单对出困惑的 diff
      const bad = [...listed].filter((x) => !/^[a-z][a-z0-9_]*(?:[.-][a-z0-9_-]+)*$/.test(x)).sort()
      if (bad.length) {
        mism.push([sk, `「拥有模块」行格式非法 ${bad}`])
        continue
      }
    }
    const want = new Set(Object.keys(mods))
    if (listed.size !== want.size || ![...listed].every((x) => want.has(x))) {
      mism.push([sk, `文档 ${[...listed].sort()} ≠ 清单 ${[...want].sort()}`])
    }
  }
  rows.push([!mism.length,
    '每个 skill 的「拥有模块」行与 ownership.json 一致'
    + (mism.length ? `　**不一致 ${mism}**` : '')])

  // ---- 13. 代码归属段的散文不许做归属断言（防 prose 说谎）----
  // 机检行「拥有模块：a, b」是**唯一**合法的归属断言处。真实事故：曾同时有
  // 四份 SKILL.md 的散文写着「本 skill 拥有 X」「X 的归属虽记在本 skill」，
  // 而 ownership.json 里 X 全在 library——机检行是对的、散文是反的，检查 12
  // 只读机检行所以全绿。散文要说归属，只能引用 ownership.json。
  // 判据（段内、机检行以外）：
  // - 非否定式的「拥有」或「归属…本 skill」→ 断言，FAIL；
  // - 「Y 的 X」紧邻对（Y ∈ skill 名/library/infrastructure，X ∈ 已声明模块
  //   ——全 ID 或短名（去包前缀），间隔 ≤8 个非反引号字符）→ X 必须真的
  //   在 Y 名下；远距提及不判，避免误伤。
  const assertRe = /(?<!不)拥有|归属[^\n]{0,10}本\s*skill/
  const owners = new Map<string, Set<string>>([...names].map((n) => [n, new Set(Object.keys(skillMap[n] ?? {}))]))
  owners.set('library', new Set(Object.keys(library)))
  owners.set('infrastructure', new Set(Object.keys(infra)))
  const bad: string[] = []
  for (const sk of [...names].sort()) {
    const body = readFileSync(join(SKILLS, sk, 'SKILL.md'), 'utf-8')
    if (!body.includes('## 代码归属')) continue    // 缺段由检查 2/12 报，不重复
    const seg = body.split('## 代码归属')[1]!.split('\n## ')[0]!
    for (const ln of seg.split('\n')) {
      const s = ln.trim()
      if (!s || s.startsWith('拥有模块：')) continue
      const plain = s.replaceAll('*', '')
      if (assertRe.test(plain)) {
        bad.push(`${sk}: 散文断言归属（要说归属只能引用 ownership.json）：${s.slice(0, 40)}`)
        continue
      }
      for (const [other, owned] of owners) {
        if (other === sk) continue
        for (const m of declared) {
          if (owned.has(m)) continue
          // 短名（去包前缀）与全 ID 都算提及；「core.tts」的短名是「tts」
          const tokens = new Set([m, m.split('.').at(-1) ?? m])
          for (const tok of tokens) {
            const re = new RegExp(
              escapeRe(other) + '`?[^\\n`]{0,8}`' + escapeRe(tok) + '`')
            if (re.test(plain)) {
              bad.push(`${sk}: 散文把 ${m} 记在 ${other} 名下：${s.slice(0, 40)}`)
            }
          }
        }
      }
    }
  }
  rows.push([!bad.length,
    '代码归属段散文不做虚假归属断言'
    + (bad.length ? `　**${bad}**` : '')])
  return rows
}

// ---------------------------------------------------------------- README 模块地图对账

const MAP_TIERS = ['### library', '### infrastructure', '### skill 专属'] as const

function readmeMapMismatches(readmeText: string, own: Own): string[] {
  // usine/README.md「模块地图」三个小节的模块清单 ↔ ownership.json 双向对账。
  // 地图是**手写的**——它承载账本没有的「谁在用」列；手写副本必须有对账机检
  // 兜底，这正是检查 12 对 SKILL.md「拥有模块」行做的事。纯函数：吃文本与
  // 账本，反向验证可直接喂伪造输入。只读**表格行**（| 开头）里的反引号
  // 标识符——散文与节引言不判，带 . / - 的 token 天然不匹配。
  const library = (own.library ?? {}) as Record<string, string>
  const infra = (own.infrastructure ?? {}) as Record<string, string>
  const skillsOwn = (own.skills ?? {}) as Record<string, Record<string, string>>
  const tiers: Record<string, Set<string>> = {
    '### library': new Set(Object.keys(library)),
    '### infrastructure': new Set(Object.keys(infra)),
    '### skill 专属': new Set(Object.values(skillsOwn).flatMap((m) => Object.keys(m))),
  }
  const home = (m: string): string => {
    if (m in library) return 'library'
    if (m in infra) return 'infrastructure'
    for (const [sk, mods] of Object.entries(skillsOwn)) {
      if (m in mods) return `skills.${sk}`
    }
    return 'unclaimed（无主）'
  }
  const tokRe = /`([a-z][a-z0-9_.-]*)`/g
  let cur: string | null = null
  const claimed: Record<string, Set<string>> = Object.fromEntries(MAP_TIERS.map((t) => [t, new Set<string>()]))
  for (const ln of readmeText.split('\n')) {
    for (const head of MAP_TIERS) {
      if (ln.startsWith(head)) cur = head
    }
    if (ln.startsWith('## ') && !ln.startsWith('### ')) cur = null  // 出了地图章节
    if (cur !== null && ln.trimStart().startsWith('|')) {
      for (const t of ln.matchAll(tokRe)) claimed[cur]!.add(t[1]!)
    }
  }
  const out: string[] = []
  for (const head of MAP_TIERS) {
    const tierName = head.slice(4)
    const want = tiers[head]!
    for (const m of [...want].filter((m) => !claimed[head]!.has(m)).sort()) {
      out.push(`地图缺 ${m}（账本记在 ${tierName}）——新入层/翻转的模块要同步画进地图`)
    }
    for (const m of [...claimed[head]!].filter((m) => !want.has(m)).sort()) {
      out.push(`地图把 ${m} 画在 ${tierName}，账本记在 ${home(m)}——归属翻转了地图没跟上`)
    }
  }
  return out
}

function checkReadmeMap(): Row[] {
  // 检查 14：README 模块地图三个小节与 ownership.json 双向一致。
  // 门禁自己崩溃比 FAIL 更糟（见 parseSkill 的说明）：README/账本读不了、
  // 解析不了，都出 FAIL 行而不是崩溃。
  const readmeP = join(ROOT, 'README.md')
  const opath = join(ROOT, 'ownership.json')
  if (!existsSync(readmeP) || !existsSync(opath)) {
    return [[false, 'README.md 或 ownership.json 缺失——模块地图无从对账']]
  }
  let own: Own
  try {
    own = JSON.parse(readFileSync(opath, 'utf-8')) as Own
  } catch (e) {
    return [[false, `ownership.json 读不了：${String(e)}`]]
  }
  const bad = readmeMapMismatches(readFileSync(readmeP, 'utf-8'), own)
  const nLib = Object.keys(own.library ?? {}).length
  const nInfra = Object.keys(own.infrastructure ?? {}).length
  const nSkill = Object.values(own.skills ?? {}).reduce((n, m) => n + Object.keys(m as object).length, 0)
  return [[!bad.length,
    `README 模块地图与账本双向一致（library ${nLib} / infrastructure ${nInfra} / skill 专属 ${nSkill}）`
    + (bad.length ? `　**${bad.slice(0, 3)}**` : '')]]
}

// ---------------------------------------------------------------- 小工具

function basename(p: string): string {
  return p.slice(p.lastIndexOf('/') + 1)
}
function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// ---------------------------------------------------------------- 测试

describe('skills/ 去歧义门禁（verify_skills.py 移植）', () => {
  test('全部检查行 PASS（缺一即 FAIL，SKIP 不是 PASS）', () => {
    const rows = check()
    const fails = rows.filter(([ok]) => !ok)
    const npass = rows.length - fails.length
    expect(fails, `FAIL：${npass}/${rows.length} 项\n${fails.map(([, why]) => why).join('\n')}`).toEqual([])
  })

  test('地图对账凿洞：地图多画 bogus → 被抓；账本有 audio 地图没画 → 被抓', () => {
    // 反向验证（纪律 2：凿洞必被抓；喂伪造输入，不动真实文件）
    const fakeOwn: Own = {
      library: { tts: 'x', audio: 'x' },
      infrastructure: { cli: 'x' },
      skills: { s1: { publish: 'x' } },
      unclaimed: {},
    }
    const holed = readmeMapMismatches(
      '### library —— 1 个\n\n| `tts` | a |\n| `bogus` | b |\n\n'
      + '### infrastructure —— 1 个\n\n| `cli` | a |\n\n'
      + '### skill 专属 —— 1 个\n\n| `publish` | a |\n', fakeOwn)
    expect(holed.some((m) => m.includes('bogus 画在 library')), `实得 ${holed}`).toBe(true)
    expect(holed.some((m) => m.includes('缺 audio')), `实得 ${holed}`).toBe(true)
  })

  test('地图对账凿洞：模块画错层 → 报出真实归属', () => {
    const fakeOwn: Own = {
      library: { tts: 'x', audio: 'x' },
      infrastructure: { cli: 'x' },
      skills: { s1: { publish: 'x' } },
      unclaimed: {},
    }
    const flipped = readmeMapMismatches(
      '### library —— 1 个\n\n| `cli` | a |\n\n'
      + '### infrastructure —— 1 个\n\n| `tts` | a |\n\n'
      + '### skill 专属 —— 0 个\n\n（空）\n', fakeOwn)
    expect(flipped.some((m) => m.includes('cli 画在 library') && !m.includes('skills')), `实得 ${flipped}`).toBe(true)
    expect(flipped.some((m) => m.includes('tts 画在 infrastructure')), `实得 ${flipped}`).toBe(true)
  })
})
