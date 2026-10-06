# feuille

> feuille（法语：叶 / 一页）——多语种视频生产与发布的**可复用层**。
> TTS / 渲字 / 合成 / 封面 / 四平台发布 / 发布后核对，工作流 ①–⑬ 全覆盖。
>
> ### une usine avec des machines rugissantes
>
> 一座轰鸣着机器的工厂

## 目录

| 文件/目录 | 内容 |
|---|---|
| [AGENTS.md](AGENTS.md) | ★ 活规则：22 条纪律 + 工程约定（跨平台 + uv 统一）+ H3 铁律 |
| [pyproject.toml](pyproject.toml) + `uv.lock` | uv 工程（Python 3.12；publish 组 = Playwright） |
| `src/feuille/` | 终态代码：35 模块 / 10,369 行，按工作流①–⑬全覆盖 |
| `scripts/` | 17 个反向验证脚本（`uv run feuille verify` 一条命令全量跑，250 项断言） |
| `languages/` | 语种注册表：14 语种 manifest（字体栈 / 国旗 / 书写方向 / 引号对） |
| `personas/` | 人设目录：28 人班底 + schema / 声库 / 视觉 / 选角文档 |
| [docs/](docs/) | 全部文档（工作流/工具链 + playbook 系列） |
| `examples/yiyezhiqiu/` | 示例项目内容包（诗稿 / 文案 / 数据 / 设计稿 / H3 母版——母版不可再生） |

## 使用

```bash
cd feuille
uv sync                     # 安装主依赖
uv sync --group publish    # 加装 Playwright（发布器用）
uv run feuille verify       # 全量反向验证（16 套 250 项断言）
uv run feuille verify --list       # 列出所有验证套件
uv run feuille verify --only rig   # 单跑一套
```

## docs/ 一览

| 文件 | 内容 |
|---|---|
| [workflow.md](docs/workflow.md) | 工作流运行手册（①–⑬：内容创作→合集收录，每段输入/步骤/产物/检查） |
| [toolchain.md](docs/toolchain.md) | 工具链：①–⑬ 每段用什么工具 + 工具明细 + 平台后台 |
| [publish-lessons.md](docs/publish-lessons.md) | 发布踩坑与经验教训总账（270 行，按平台分节） |
| [publish-playbook.md](docs/publish-playbook.md) | 多平台发布手册（881 行，32 条坑 + 三条元规则） |
| [zhihu-publish-playbook.md](docs/zhihu-publish-playbook.md) | 知乎发布手册（409 行，20 条坑） |
| [metrics-playbook.md](docs/metrics-playbook.md) | 数据取数手册（220 行） |
| [render-handbook.md](docs/render-handbook.md) | 渲染工程手册（1301 行，踩坑实录 §5） |
| [lessons-learned.md](docs/lessons-learned.md) | 经验总纲（入口式，只写最终成立的结论） |
