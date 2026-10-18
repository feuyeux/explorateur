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
