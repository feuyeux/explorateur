// commands.ts —— 路由表：数据，不是 if/elif（纪律与 Python 侧 cli.py 同源）
//
// 键 = `${组}/${命令}`（组可带省略命令形态 `${组}/`，对应 Python 侧
// (grp, "") 的回退查表）。叶子 = 懒加载 loader：路由层只做查表 + 动态
// import + 把残余 argv 原样交给叶子——叶子拿不到组与命令。

export interface CommandLeaf {
  /** 懒加载叶子模块，须导出 main(argv)（argv = 残余参数，不含组与命令）。 */
  load: () => Promise<{ main: (argv: string[]) => Promise<number> | number }>
  /** 一句话用途（usage 列表用；真实叶子迁入后逐步补全）。 */
  desc: string
}

export const COMMANDS: Record<string, CommandLeaf> = {
  'version': {
    load: () => import('./leaves/version.js'),
    desc: '打印版本',
  },
  // ---- P2 基础层（叶子 = 薄适配层，判据与退出码口径都在 @feuille/core）----
  'ledger/status': {
    load: () => import('./leaves/ledger-status.js'),
    desc: '缓存账本：谁过期了、因为什么（有过期 → 退出码 1）',
  },
  'framehash/save': {
    load: () => import('./leaves/framehash-save.js'),
    desc: '逐帧像素基线：采集（build/ 全量发现 → 分桶落盘 → 回读自证）',
  },
  'framehash/check': {
    load: () => import('./leaves/framehash-check.js'),
    desc: '逐帧像素基线：零漂移门禁（diff/gone → 退出码 1）',
  },
  'cover/make': {
    load: () => import('./leaves/cover-make.js'),
    desc: '封面：整页 HTML → 平台规格整图截图（尺寸/裁齐由 SPECS 保证）',
  },
  'cover/check': {
    load: () => import('./leaves/cover-check.js'),
    desc: '封面：尺寸 + 外圈众数底色检查（有问题 → 退出码 1）',
  },
  // ---- P4 数据与人物场景 ----
  'persona/validate': {
    load: () => import('./leaves/persona-validate.js'),
    desc: '人设契约体检：逐人 validatePersona + 班底不变量（有问题 → 退出码 1）',
  },
  // ---- P5 课件线（lesson 族；解析器 + 校验层先行）----
  'scene/parse': {
    load: () => import('./leaves/scene-parse.js'),
    desc: '场景解析：lessons/<id>/scene.md → scene.json（解析 + 前置校验 + token 自检）',
  },
  'scene/validate': {
    load: () => import('./leaves/scene-validate.js'),
    desc: '场景数据前置校验：scene.json × 注册表 + 选角/班底（不合规 → 退出码 1）',
  },
  'scene/draft': {
    load: () => import('./leaves/scene-draft.js'),
    desc: '教学创意 → lessons/<id>/scene.md 结构草稿（只填结构留 TODO；--gaps 查欠账）',
  },
  'scene/tts': {
    load: () => import('./leaves/scene-tts.js'),
    desc: '场景课 TTS：scene.json × 班底声线 → timeline.json + 逐行 mp3（台账增量）',
  },
  'lesson/new': {
    load: () => import('./leaves/lesson-new.js'),
    desc: '新课开坑：lessons/<id>/brief.json（注册表现取 + 选角当场验 + 空跑草稿自证）',
  },
  'lesson/doctor': {
    load: () => import('./leaves/lesson-doctor.js'),
    desc: '课件就绪度体检：①创意…⑦验收，每条未完成带下一条命令（FAIL → 退出码 1）',
  },
  // ---- P5-7 skills 归流（skills/ 脚本升包后的唯一实现进 @feuille/core）----
  'theme/match': {
    load: () => import('./leaves/theme-match.js'),
    desc: '主题自动匹配：话题/语种 → 5 套垂域主题推荐（skills/match_theme.py 升包）',
  },
  // ---- P5-7b karaoke-video 归流（@feuille/karaoke；edge-tts/ffprobe/浏览器
  // 解析消费 core 唯一实现，包内零重复）----
  'karaoke/tts': {
    load: () => import('./leaves/karaoke-tts.js'),
    desc: '词级卡拉OK TTS：voices.json → 逐语种 mp3 + 词边界/token 时间 json',
  },
  'karaoke/build': {
    load: () => import('./leaves/karaoke-build.js'),
    desc: '状态帧渲染 + 音轨组装成片（video.json 驱动；30fps 网格精确帧数编码）',
  },
  'karaoke/verify-sync': {
    load: () => import('./leaves/karaoke-verify-sync.js'),
    desc: 'AV 同步验收：计算可知时间点抓帧 vs 状态帧像素差（失配 → 退出码 1）',
  },
  'karaoke/scan-blank': {
    load: () => import('./leaves/karaoke-scan-blank.js'),
    desc: '全片白页扫描：唯一独立于状态帧的检查（含白帧 → 退出码 1）',
  },
  // ---- P5-7c poetry 诊断线（multilingual-video-poetry 归流）----
  'poetry/audio-profile': {
    load: () => import('./leaves/poetry-audio-profile.js'),
    desc: '音频拆轨对比：人声段 vs 空档段 LUFS 电平（差 < 8 dB = 人声被盖住）',
  },
  'poetry/color-contrast': {
    load: () => import('./leaves/poetry-color-contrast.js'),
    desc: '文字压实拍量化：背景亮度分布 + 逐季 --gate 二值判据（阈值项目自标定）',
  },
  // ---- P5-7d storyteller 评书线（storyteller-video 归流）----
  'storyteller/render-frames': {
    load: () => import('./leaves/storyteller-render-frames.js'),
    desc: '评书幕帧渲染：舞台 + 人物 + 卷面卡拉OK字卡（acts.json 驱动）',
  },
  'storyteller/assemble': {
    load: () => import('./leaves/storyteller-assemble.js'),
    desc: '评书成片组装：幕帧 → 叠化转场 → 醒木混音（单画幅 mp4）',
  },
  // ---- P5-7e one-page-poster 归流（@feuille/poster；浏览器解析消费 core
  // 唯一实现，零额度——fetch_fonts 只打 Google Fonts css2 免费子集端点）----
  'poster/fetch-fonts': {
    load: () => import('./leaves/poster-fetch-fonts.js'),
    desc: '字体子集抓取：fonts.json → 内嵌 fonts.css（Google Fonts css2 子集）',
  },
  'poster/assemble': {
    load: () => import('./leaves/poster-assemble.js'),
    desc: '海报组装：poster_src.html + fonts.css → index.html（@import 合并内嵌）',
  },
  'poster/render': {
    load: () => import('./leaves/poster-render.js'),
    desc: '整页截图：Edge/Chrome headless 按画幅出图（原 render_poster.sh）',
  },
  'poster/render-page': {
    load: () => import('./leaves/poster-render-page.js'),
    desc: 'DOM/截图双模式：dump 子命令吐渲染后 DOM，render 子命令按 query 出图',
  },
  'poster/audit-charset': {
    load: () => import('./leaves/poster-audit-charset.js'),
    desc: '字符子集门（tofu 防线）+ .ksyl 补丁规则绑定门（A-03 机器形态）',
  },
  'poster/fit-diag': {
    load: () => import('./leaves/poster-fit-diag.js'),
    desc: 'fit 诊断：从 DOM 里捞 DIAG 行对照限值（溢出 → 退出码 1）',
  },
  'poster/verify-colors': {
    load: () => import('./leaves/poster-verify-colors.js'),
    desc: '四色抽样验收：红/蓝/灰/墨逐格对表（色差超限 → 退出码 1）',
  },
  'poster/check-overlay': {
    load: () => import('./leaves/poster-check-overlay.js'),
    desc: '叠印对齐验收：lay 层 vs top 层逐位移求最优对齐（错位/脏色 → FAIL）',
  },
  'poster/make-covers': {
    load: () => import('./leaves/poster-make-covers.js'),
    desc: '全屏封面变体：给 poster_src.html 注入 overlay CSS + 生成 index 母版',
  },
  'poster/measure-korean': {
    load: () => import('./leaves/poster-measure-korean.js'),
    desc: '韩文逐字素几何测量：测墨 → 元/辅音分类 → 生成 .k%04X 补丁规则 + 自验',
  },
  // ---- 平台发布（⑨⑩⑪）----
  // ⚠️ 发布类叶子依赖 playwright（可选依赖）：@feuille/publish 只在函数内
  // 动态 import，没装时报的是「缺 playwright」而不是「未知命令」——
  // 这个区别很重要，前者告诉用户怎么修。publish() 是库函数，douyin/xhs/
  // bilibili 挂 main 适配层；login 无参可调用，按 Python 侧 `fn(argv) if argv
  // else fn()` 形态接线。清单组装（build_manifest）没有叶子——它吃带闭包的
  // plans 契约，只能从项目脚本调用。
  'publish/login': {
    load: () => import('./leaves/publish-login.js'),
    desc: '平台扫码登录：登录态存盘到持久 profile（默认四平台全扫）',
  },
  'publish/check-plan': {
    load: () => import('./leaves/publish-check-plan.js'),
    desc: '发布前清单自检：素材/标题字数/横竖配对/封面比例（零平台流量）',
  },
  'publish/douyin': {
    load: () => import('./leaves/publish-douyin.js'),
    desc: '抖音批量发布（manifest.json 驱动；封面先发后补）',
  },
  'publish/xhs': {
    load: () => import('./leaves/publish-xhs.js'),
    desc: '小红书批量发布（manifest.json 驱动；3:4 封面回退）',
  },
  'publish/bilibili': {
    load: () => import('./leaves/publish-bilibili.js'),
    desc: 'B 站批量投稿（manifest.json 驱动；分区/声明/封面硬闸门 + .txt 字幕）',
  },
}

/** 查表：先精确 `${grp}/${cmd}`，miss 再回退组省略形态 `${grp}/`。 */
export function resolveCommand(grp: string, cmd: string): CommandLeaf | undefined {
  return COMMANDS[`${grp}/${cmd}`] ?? COMMANDS[grp]
}
