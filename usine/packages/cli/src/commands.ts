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
}

/** 查表：先精确 `${grp}/${cmd}`，miss 再回退组省略形态 `${grp}/`。 */
export function resolveCommand(grp: string, cmd: string): CommandLeaf | undefined {
  return COMMANDS[`${grp}/${cmd}`] ?? COMMANDS[grp]
}
