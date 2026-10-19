// make_covers.ts — 从 poster_src.html 派生全屏封面变体（横版 1920x1080 4x3 网格、
// 竖版 1080x1920 3x4 网格）：同格子、同自适应 JS、不同页面几何。绝不旋转——
// 两个方向各自原生排版才能铺满全屏（旋转/垫衬会留死带）。
// （promoted from skills/one-page-poster/scripts/make_covers.py，P5-7e 归流）
//
// Usage: make-covers [poster_src.html [cover_src.html]]
//   缺省读写源文件同目录（跨项目跑时把两个路径都传进来）。
import { readFileSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const OVERRIDES = `
/* ---------- fullscreen cover variants (make_covers.py) ---------- */
.poster.lc { width: 1920px; height: 1080px; padding: 44px 64px 36px; }
.poster.lc .grid { grid-template-columns: repeat(4, 1fr); grid-template-rows: repeat(3, 1fr); margin-top: 22px; min-height: 0; }
.poster.lc .title-zh { font-size: 96px; }
.poster.lc .title-sub { font-size: 21px; margin-top: 12px; }
.poster.lc .legend { gap: 10px; padding-bottom: 8px; }
.poster.lc .legend .li { font-size: 17px; }
.poster.lc .legend .li b { font-size: 18px; }
.poster.lc .lang { font-size: 20px; }
.poster.lc .lang small { font-size: 15px; }
.poster.lc .natv { font-size: 19px; }
.poster.lc .translit { font-size: 30px; }
.poster.lc .annot { font-size: 38px; }
.poster.lc .jpat { font-size: 24px; }
.poster.pt { width: 1080px; height: 1920px; padding: 60px 52px 48px; }
.poster.pt .grid { grid-template-columns: repeat(3, 1fr); grid-template-rows: repeat(4, 1fr); margin-top: 28px; min-height: 0; }
.poster.pt .title-zh { font-size: 92px; }
.poster.pt .title-sub { font-size: 19px; }
.poster.pt .translit { font-size: 28px; }
.poster.pt .annot { font-size: 38px; }
.poster.pt .jpat { font-size: 24px; }

/* 3:4（1080×1440）——竖版平台信息流封面的**原生比例**。
   9:16 全屏封面（.pt）被小红书/抖音的信息流按 3:4 居中裁切时，
   顶部 12.5% 与底部 12.5% 会掉（标题在顶部 → 被切掉）。
   所以竖版平台投 3:4 版，视频本体仍是 9:16 全屏。 */
.poster.t34 { width: 1080px; height: 1440px; padding: 44px 48px 38px; }
.poster.t34 .grid { grid-template-columns: repeat(3, 1fr); grid-template-rows: repeat(4, 1fr); margin-top: 20px; min-height: 0; }
.poster.t34 .title-zh { font-size: 78px; }
.poster.t34 .title-sub { font-size: 16px; margin-top: 10px; }
.poster.t34 .legend { gap: 6px; padding-bottom: 4px; }
.poster.t34 .legend .li { font-size: 13px; gap: 8px; }
.poster.t34 .legend .li b { font-size: 13.5px; }
.poster.t34 .dot { width: 13px; height: 13px; }
.poster.t34 .lang { font-size: 15px; }
.poster.t34 .lang small { font-size: 12px; }
.poster.t34 .natv { font-size: 14px; }
.poster.t34 .translit { font-size: 24px; }
.poster.t34 .annot { font-size: 30px; }
.poster.t34 .jpat { font-size: 20px; }
`

const BOOT = `
<script>
// cover variant: ?fmt=P portrait (3x4 grid, 9:16 page) | ?fmt=T 3:4 page
// (1080x1440 — 竖版平台信息流封面的原生比例) | else landscape (4x3)
const FMT = new URLSearchParams(location.search).get("fmt");
document.querySelector(".poster").classList.add(
  FMT === "P" ? "pt" : FMT === "T" ? "t34" : "lc");
</script>
`

export function main(argv: string[]): number {
  // 缺省在模块旁读写（原 .py 是 __file__ 旁；跨项目跑时把两个路径都传进来）
  const srcPath = argv[0] !== undefined ? resolve(argv[0]) : join(dirname(fileURLToPath(import.meta.url)), 'poster_src.html')
  const outPath = argv[1] !== undefined ? resolve(argv[1]) : join(dirname(srcPath), 'cover_src.html')

  let s = readFileSync(srcPath, 'utf-8')

  // 把变体覆盖插到 </style> 前（Python str.replace 换所有出现处 → split/join；
  // 标记不在 → 原样不动，不报错——按原样镜像）
  s = s.split('ruby rt { font-weight: 500; }\n</style>')
    .join(`ruby rt { font-weight: 500; }\n${OVERRIDES}</style>`)

  // fmt 切换 + 封面标题 id：在自适应脚本前加一段 boot 脚本
  s = s.split('<script>\n// per-cell auto-fit')
    .join(`${BOOT}\n<script>\n// per-cell auto-fit`)

  writeFileSync(outPath, s, 'utf-8')
  console.log(`wrote ${outPath} (${Math.floor(statSync(outPath).size / 1024)} KB)`)
  return 0
}
