// patch_publish.mjs — 修 worker 交来的发布词里的两类硬伤（一次性修补脚本）
//
// ① 文件名注释与实际产物不符：写的是「茶_vertical.mp4」，产线出的是 tea_portrait.mp4
//    —— 视频名写错，发布时会照着不存在的文件名去贴素材。
// ② 封面贴士口径与产线实际产物不符：写「用视频首帧，不用另做」，但产线会出
//    cover_t34 / cover_lc / cover_pt 三版封面，发布清单里引用的就是这些。
//
// 跑法：node tools/foodnames/patch_publish.mjs
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const EX = 'D:/coding/personal/explorateur/usine/examples'

/** 期目录 → [slug, 中文名] */
const EPS = [
  ['foodnames-ep03-tea', 'tea', '茶'],
  ['foodnames-ep04-tomato', 'tomato', '番茄'],
  ['foodnames-ep05-chocolate', 'chocolate', '巧克力'],
  ['foodnames-ep06-curry', 'curry', '咖喱'],
  ['foodnames-ep07-beer', 'beer', '啤酒'],
  ['foodnames-ep08-dumpling', 'dumpling', '饺子'],
  ['foodnames-ep09-ramen', 'ramen', '拉面'],
  ['foodnames-ep10-pizza', 'pizza', '披萨'],
  ['foodnames-ep11-hamburger', 'hamburger', '汉堡包'],
  ['foodnames-ep12-fries', 'fries', '薯条'],
]

const TIP_34 = '- 封面用 3:4 信息流版（cover_t34.png，1080×1440）——9:16 版被信息流居中裁掉上下各 12.5%，标题会跟着丢；视频本体照旧 9:16 全屏；'
const TIP_16_9 = '- 横屏 1920×1080，封面用 16:9 全屏版（cover_lc.png），片头自带金色封面，首帧即可用；'

let patched = 0
for (const [dir, slug, zh] of EPS) {
  const pub = join(EX, dir, 'publish')
  if (!existsSync(pub)) continue
  for (const f of ['xiaohongshu.md', 'douyin.md', 'bilibili.md']) {
    const p = join(pub, f)
    if (!existsSync(p)) continue
    const before = readFileSync(p, 'utf8')
    let t = before
    // ① 文件名注释
    t = t.split(`${zh}_vertical.mp4`).join(`${slug}_portrait.mp4`)
    t = t.split(`${zh}_landscape.mp4`).join(`${slug}_landscape.mp4`)
    t = t.split(`${zh}_portrait.mp4`).join(`${slug}_portrait.mp4`)
    // ② 封面贴士
    t = t.split('\n').map((l) => {
      if (/^- 封面用视频首帧/.test(l)) return TIP_34
      if (/^- 竖屏 1080×1920 直接全屏发布，片头自带金色/.test(l)) {
        return '- 竖屏 1080×1920 直接全屏发布，片头自带金色封面；封面另用 3:4 版（cover_t34.png）——9:16 那张被信息流裁掉上下各 12.5%，标题会跟着丢；'
      }
      return l
    }).join('\n')
    if (t !== before) {
      writeFileSync(p, t, 'utf8')
      patched += 1
      console.log(`patched ${dir}/publish/${f}`)
    }
  }
}
console.log(`\npatched ${patched} files`)
// 剩余「用视频首帧」句式自检
const left = []
for (const d of readdirSync(EX)) {
  const pub = join(EX, d, 'publish')
  if (!existsSync(pub)) continue
  for (const f of ['xiaohongshu.md', 'douyin.md', 'bilibili.md']) {
    const p = join(pub, f)
    if (!existsSync(p)) continue
    const t = readFileSync(p, 'utf8')
    if (/用视频首帧/.test(t)) left.push(`${d}/${f}`)
  }
}
console.log(left.length ? `⚠️ 仍有「用视频首帧」：${left.join(', ')}` : '✅ 无残留「用视频首帧」')
