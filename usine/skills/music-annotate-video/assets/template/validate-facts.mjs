#!/usr/bin/env node
// validate-facts.mjs — 事实/许可账本的机检入口（本产线收尾判据）。
//
// 判的是三件事，任意一条不成立即退出 1：
//   1. 每个数字都有 source（不填 0 兜底、不手抄）；
//   2. credit.source_ids 全部能在 sources.json 里找到，且被引用的素材有
//      attribution（CC BY / CC BY-SA / 公有领域条目都要能署名）；
//   3. 交付模式下没有 {{…}} 占位符（"见成片 ffprobe" 之类的话不许流进成片）。
//
// 用法：
//   node validate-facts.mjs --facts <facts.json> --sources <sources.json>
//   node validate-facts.mjs --facts … --sources … --template   # 允许占位符
//   node validate-facts.mjs --self-test                        # 反向自测
//
// 退出码：0 = 全过；1 = 有错；2 = 用法错误。
import { readFileSync } from 'node:fs'

function usage(msg) {
  if (msg) console.error(msg)
  console.error(
    'usage: node validate-facts.mjs --facts <facts.json> --sources <sources.json>'
    + ' [--template] [--json]\n'
    + '       node validate-facts.mjs --self-test',
  )
  process.exit(2)
}

function parse(argv) {
  const out = { template: false, json: false, selfTest: false }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const take = () => {
      const v = argv[++i]
      if (v === undefined) usage(`missing value after ${a}`)
      return v
    }
    if (a === '--facts') out.facts = take()
    else if (a === '--sources') out.sources = take()
    else if (a === '--template') out.template = true
    else if (a === '--json') out.json = true
    else if (a === '--self-test') out.selfTest = true
    else if (a === '-h' || a === '--help') usage()
    else usage(`unknown argument ${a}`)
  }
  if (!out.selfTest && (!out.facts || !out.sources)) usage('--facts and --sources are required')
  return out
}

const nonEmpty = (v) => typeof v === 'string' && v.trim().length > 0

function walkStrings(v, path, out) {
  if (typeof v === 'string') out.push([path, v])
  else if (Array.isArray(v)) v.forEach((x, i) => walkStrings(x, `${path}[${i}]`, out))
  else if (v && typeof v === 'object') {
    // `$schema` / `$comment` 是 schema 说明，不是内容——不参与占位符扫描。
    for (const [k, x] of Object.entries(v)) {
      if (k.startsWith('$')) continue
      walkStrings(x, path ? `${path}.${k}` : k, out)
    }
  }
}

/** 纯函数：返回错误串数组。反向自测直接喂伪输入。 */
export function check(facts, sources, opt = {}) {
  const errors = []
  if (facts?.$schema !== 'music-facts/v1') errors.push('facts.$schema 必须是 music-facts/v1')
  if (sources?.$schema !== 'music-sources/v1') errors.push('sources.$schema 必须是 music-sources/v1')

  const items = Array.isArray(sources?.items) ? sources.items : []
  if (!items.length) errors.push('sources.items 为空——没有登记任何录音/乐谱')
  const byId = new Map()
  for (const it of items) {
    if (!nonEmpty(it?.id)) { errors.push('sources.items[] 缺 id'); continue }
    if (byId.has(it.id)) errors.push(`sources.items 的 id 重复：${it.id}`)
    byId.set(it.id, it)
    for (const k of ['kind', 'title', 'url', 'license', 'license_url', 'attribution', 'retrieved', 'sha256']) {
      if (!nonEmpty(it[k])) errors.push(`sources.items[${it.id}] 缺 ${k}`)
    }
    if (it.kind === 'image') {
      for (const k of ['creator', 'date', 'file_url']) {
        if (!nonEmpty(it[k])) errors.push(`sources.items[${it.id}] 是图片，缺 ${k}`)
      }
      const w = Number(it.width), h = Number(it.height)
      if (!Number.isFinite(w) || !Number.isFinite(h) || w < 0 || h < 0) {
        errors.push(`sources.items[${it.id}] 的 width/height 必须是非负数字`)
      } else if (!opt.template && (!w || !h)) {
        errors.push(`sources.items[${it.id}] 交付模式必须有实测 width/height`)
      }
    }
  }

  const work = facts?.work ?? {}
  for (const k of ['title', 'composer', 'catalog']) {
    if (!nonEmpty(work[k])) errors.push(`facts.work 缺 ${k}`)
  }

  const nums = Array.isArray(facts?.numbers) ? facts.numbers : []
  if (!nums.length) errors.push('facts.numbers 为空——制作信息页没有实测数字')
  const keys = new Set()
  for (const [i, n] of nums.entries()) {
    const at = `facts.numbers[${i}]`
    if (!nonEmpty(n?.key)) errors.push(`${at} 缺 key`)
    else if (keys.has(n.key)) errors.push(`${at} 的 key 重复：${n.key}`)
    else keys.add(n.key)
    if (typeof n?.value !== 'number' || !Number.isFinite(n.value)) errors.push(`${at}.value 必须是数字`)
    if (!nonEmpty(n?.unit)) errors.push(`${at} 缺 unit`)
    if (!nonEmpty(n?.source)) errors.push(`${at} 缺 source——数字没有出处`)
    if (!nonEmpty(n?.measured_at)) errors.push(`${at} 缺 measured_at`)
  }

  const credit = facts?.credit ?? {}
  const ids = Array.isArray(credit.source_ids) ? credit.source_ids : []
  if (!ids.length) errors.push('facts.credit.source_ids 为空——制作信息页没有来源')
  for (const id of ids) {
    const it = byId.get(id)
    if (!it) errors.push(`facts.credit.source_ids 引用了不存在的 ${id}`)
    else if (!nonEmpty(it.attribution)) errors.push(`sources.items[${id}] 没有 attribution，不能署名`)
  }
  for (const k of ['work', 'performer', 'recording_license', 'score_license']) {
    if (!nonEmpty(credit[k])) errors.push(`facts.credit 缺 ${k}`)
  }
  if (!Array.isArray(credit.attribution_lines) || !credit.attribution_lines.length) {
    errors.push('facts.credit.attribution_lines 为空')
  }

  // ---- 视觉资料：每张史料图必须绑定到 image 来源，且长边够用 ----
  const visuals = Array.isArray(facts?.visuals) ? facts.visuals : []
  const visualKeys = new Set()
  const MIN_EDGE = { 'full-bleed': 1600, inset: 900, background: 1600 }
  for (const [i, v] of visuals.entries()) {
    const at = `facts.visuals[${i}]`
    if (!nonEmpty(v?.key)) errors.push(`${at} 缺 key`)
    else if (visualKeys.has(v.key)) errors.push(`${at} 的 key 重复：${v.key}`)
    else visualKeys.add(v.key)
    if (!nonEmpty(v?.caption)) errors.push(`${at} 缺 caption（年代/作者/来源）`)
    if (!Object.hasOwn(MIN_EDGE, v?.usage)) {
      errors.push(`${at}.usage 必须是 full-bleed / inset / background`)
      continue
    }
    const it = byId.get(v.source_id)
    if (!it) { errors.push(`${at} 引用了不存在的 ${v.source_id}`); continue }
    if (it.kind !== 'image') { errors.push(`${at} 的 ${v.source_id} 不是 image 来源`); continue }
    const w = Number(it.width), h = Number(it.height)
    if (!opt.template && Math.max(w, h) < MIN_EDGE[v.usage]) {
      errors.push(`${at} ${v.usage} 需要长边 ≥${MIN_EDGE[v.usage]}px，实得 ${w}×${h}`)
    }
  }

  if (!opt.template) {
    const ph = Array.isArray(facts?.placeholders) ? facts.placeholders : []
    if (ph.length) errors.push(`交付模式仍有 ${ph.length} 个登记占位符：${ph.join(', ')}`)
    const strings = []
    walkStrings(facts, 'facts', strings)
    walkStrings(sources, 'sources', strings)
    const left = strings.filter(([, s]) => s.includes('{{'))
    if (left.length) {
      errors.push(`交付模式仍有 {{…}} 占位符：${left.slice(0, 6).map(([p]) => p).join(', ')}`)
    }
  }
  return errors
}

function fixture() {
  const sources = {
    $schema: 'music-sources/v1',
    items: [
      {
        id: 'src-001', kind: 'recording', title: 'Symphony No. 9 — II',
        performer: 'Public Domain Orchestra', url: 'https://example.org/a.ogg',
        license: 'CC0-1.0', license_url: 'https://example.org/cc0',
        attribution: 'Public Domain Orchestra, CC0', retrieved: '2026-11-01', sha256: '0'.repeat(64),
      },
      {
        id: 'src-003', kind: 'image', title: 'Antonín Dvořák, c. 1890',
        creator: 'Unknown photographer', date: 'c. 1890',
        url: 'https://example.org/wiki/File:Dvorak.jpg',
        file_url: 'https://example.org/wiki/File:Dvorak.jpg?download',
        license: 'PD-old-70', license_url: 'https://example.org/pd',
        attribution: 'Public domain, via Wikimedia Commons',
        retrieved: '2026-11-01', sha256: '1'.repeat(64), width: 2100, height: 2600,
      },
    ],
  }
  // 注意：这一串单独成行——门禁的硬编码检查只剥每行第一个引号串。
  const probeSource = 'ffprobe out.mp4'
  const facts = {
    $schema: 'music-facts/v1',
    work: { title: 'Symphony No. 9', composer: 'A. Dvořák', catalog: 'Op. 95' },
    numbers: [
      { key: 'final_duration_s', value: 902.4, unit: 's', source: probeSource, measured_at: '2026-11-01T20:00:00+08:00' },
    ],
    visuals: [
      { key: 'composer-portrait', source_id: 'src-003', usage: 'inset', placement: 'bio-timeline', caption: 'Dvořák, c. 1890 · Wikimedia Commons' },
    ],
    credit: {
      work: 'Symphony No. 9', performer: 'Public Domain Orchestra',
      recording_license: 'CC0-1.0', score_license: 'CC0-1.0',
      source_ids: ['src-001', 'src-003'], attribution_lines: ['Public Domain Orchestra, CC0'],
    },
    placeholders: [],
  }
  return { facts, sources }
}

function selfTest() {
  const { facts, sources } = fixture()
  const base = check(facts, sources, { template: false })

  const ph = structuredClone(facts)
  ph.work.title = '{{WORK_TITLE}}'
  ph.placeholders = ['{{WORK_TITLE}}']
  const phErrs = check(ph, sources, { template: false })
  const phCaught = phErrs.some((e) => e.includes('占位符'))

  const badId = structuredClone(facts)
  badId.credit.source_ids = ['src-404']
  const idCaught = check(badId, sources, { template: false }).some((e) => e.includes('不存在'))

  const noSource = structuredClone(facts)
  noSource.numbers[0].source = ''
  const srcCaught = check(noSource, sources, { template: false }).some((e) => e.includes('缺 source'))

  // 小幅面图当 full-bleed：长边 2600 够，但改成 800×1000 就必须被抓。
  const smallSources = structuredClone(sources)
  smallSources.items[1].width = 800
  smallSources.items[1].height = 1000
  const v = structuredClone(facts)
  v.visuals[0].usage = 'full-bleed'
  const sizeCaught = check(v, smallSources, { template: false }).some((e) => e.includes('长边'))

  // 视觉条目绑到录音来源（kind=recording）必须被抓。
  const wrongKind = structuredClone(facts)
  wrongKind.visuals[0].source_id = 'src-001'
  const kindCaught = check(wrongKind, sources, { template: false }).some((e) => e.includes('不是 image'))

  const ok = base.length === 0 && phCaught && idCaught && srcCaught && sizeCaught && kindCaught
  console.log(
    `self-test: good=${base.length === 0 ? 'pass' : 'FALSE-FAIL'}`
    + ` placeholder=${phCaught ? 'caught' : 'MISSED'}`
    + ` unknown-source=${idCaught ? 'caught' : 'MISSED'}`
    + ` missing-number-source=${srcCaught ? 'caught' : 'MISSED'}`
    + ` small-image=${sizeCaught ? 'caught' : 'MISSED'}`
    + ` wrong-kind=${kindCaught ? 'caught' : 'MISSED'}`
    + `  [${ok ? 'PASS' : 'FAIL'}]`,
  )
  if (base.length) console.log(base.join('\n'))
  return ok
}

const opt = parse(process.argv.slice(2))
if (opt.selfTest) process.exit(selfTest() ? 0 : 1)

let facts, sources
try {
  facts = JSON.parse(readFileSync(opt.facts, 'utf8'))
  sources = JSON.parse(readFileSync(opt.sources, 'utf8'))
} catch (e) {
  console.error(`cannot read input: ${e.message}`)
  process.exit(2)
}

const errors = check(facts, sources, { template: opt.template })
if (opt.json) console.log(JSON.stringify({ ok: !errors.length, errors }, null, 2))
else if (errors.length) {
  console.error(`validate-facts FAIL (${errors.length})`)
  for (const e of errors) console.error(`  - ${e}`)
} else {
  console.log(`validate-facts ok${opt.template ? ' (template mode)' : ''}`)
}
process.exit(errors.length ? 1 : 0)
