# feuille —— 多语种视频生产与发布的可复用层

"""分层能力（对应工作流 ①–⑬，见 docs/workflow.md）：

- ②③ 场景与数据：scene 解析 / schema 校验、能力数据（班底 / 语种注册表）
- ④ 审计：声称 vs 实测（格律计数，NO_CLAIM 留白合法）
- ⑤ 音频：tts（内容寻址缓存 + 词级时间戳）、timeline（时间轴补齐）、audio（compose_track）
- ⑥ 视频：textlayer（Edge headless 渲字 + 双 matte）、compose（母版叠加）、render（程序化逐帧基座 + 人物 rig）
- ⑦ 封面：covers（平台规格表 + 预裁底图 + Edge 叠字）
- ⑧ 清单：manifest（文案稿 → 结构化发布清单 + 逐项核对）
- ⑨ 发布：publish（抖音 / 小红书 / B 站发布器 + 登录）
- ⑩ 合集：collections
- ⑪ 发布后核对：veriflive（三平台只读后台截图核对）
- ⑫ 指标：metrics（回流 + 分组分析）
- ⑬ 验收：framehash（逐帧像素基线，按平台分桶）
- 基座：platform（外部件 resolver，不写死路径）、ledger（产物缓存账本）

铁律见 AGENTS.md（H3 绝不自动调用 / 封面预生成带文字 / 宁可整条不发，也不带病发布）。
统一入口：`uv run feuille <组> <命令>`（cli.py，路由表是数据不是 if/elif）。
"""
