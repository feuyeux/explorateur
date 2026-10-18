

`AetherLabsAI/RSIAgent` 的核心是**不更新模型权重（Training-free）**，通过 **Curriculum（出题）\rightarrow Actor（执行与总结）\rightarrow Verifier（独立验证）** 的三体闭环，采用“先广度（BRS）后深度（DRS）”策略探索环境，将经验沉淀为可复用的 **Memory（操作规程、脚本、避坑指南）**；而 `deepseek-ai/deepseek-harness`（简称 `dsh`）基于 **Cordis（Everything is a plugin）** 微内核架构，天然支持通过插件动态接管 **System Prompt 组装（`dsh-system-prompt`）**、**技能注册表（`dsh-skill`）** 和 **无头批量运行（`headless` profile）**。

将两者结合，本质上是**用 `RSIAgent` 作为外层“离线/闲时自进化大脑”，把 `deepseek-harness` 作为被进化的“Actor 运行时宿主”**——进化产出的 Memory 直接转化为 `dsh` 的原生插件、Skill 和 Prompt Section。

## 一、 核心架构映射关系

将 `RSIAgent` 的自进化机制映射到 `deepseek-harness` 的组件体系中，各模块的对应关系如下表：

| RSIAgent 核心组件 / 阶段         | 职责定义                                                     | 在 `deepseek-harness (dsh)` 中的落地载体                     |
| -------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| **Actor Agent（执行与归纳）**    | 与环境交互执行代码/Bash，并在验证后提炼经验合并入库          | `dsh --profile headless --json` 无头实例（负责执行任务）+ 独立的归纳 Prompt 调用 |
| **Curriculum Agent（课程生成）** | 根据已有记忆盲区与历史成败，动态生成探索任务                 | 保持在 `RSIAgent` (Python) 侧运行，读取 `~/.dsh/sessions/` 失败轨迹与当前记忆库出题 |
| **Verifier Agent（独立验证）**   | 独立检查环境状态与任务要求，**不可见** Actor 的推理过程与记忆 | 保持在 `RSIAgent` 沙箱侧，直接检查容器文件系统、Git Diff、测试结果或 UI 状态 |
| **Memory: 避坑准则与约束**       | 环境隐藏限制、高频报错模式（Hidden Constraints & Failure Lessons） | 挂载至 `@deepseek-ai/dsh-system-prompt` 的动态 Section（每轮自动渲染，不膨胀上下文历史） |
| **Memory: 标准化操作流 (SOP)**   | 多步任务处理规程（Procedures）                               | 编译为 `@deepseek-ai/dsh-skill` 的 Markdown 技能包，支持运行时 `invalidate()` 热更新 |
| **Memory: 可复用脚本**           | 验证通过的 Python/Bash 辅助脚本（Reusable Scripts）          | 存入工作区工具目录，并通过 `@deepseek-ai/dsh-tools` 注册为智能体原生可调用的 Tool |

## 二、 具体工程实现方案

推荐采用 **“Python 进化编排层（RSIAgent） + TypeScript 插件宿主层（DeepSeek Harness）”** 的解耦架构，无需魔改两个项目的核心底座即可跑通闭环。

### 1. 改造 RSIAgent：将 `dsh` 封装为 Actor 执行后端

`RSIAgent` 原生使用自带的 Actor 循环执行 Python/Bash。你需要编写一个适配器（`DshActorAdapter`），让 `RSIAgent` 在 Docker/KVM 沙箱中通过 CLI 调用 `dsh --profile headless`：

```python
# rsi_dsh_bridge/actor_adapter.py
import subprocess
import json
from pathlib import Path

class DshActorAdapter:
    def __init__(self, workspace_dir: Path, dsh_home: Path, memory_dir: Path):
        self.workspace_dir = workspace_dir
        self.dsh_home = dsh_home
        self.memory_dir = memory_dir

    def execute_task(self, task_prompt: str, timeout: int = 600) -> dict:
        """
        在沙箱中调用 deepseek-harness headless 模式执行探索任务，
        并收集 NDJSON 事件流供后续经验提炼使用。
        """
        env = {
            "DSH_HOME": str(self.dsh_home),
            "RSI_MEMORY_PATH": str(self.memory_dir),
            # 传入模型 API Key（Headless 模式默认禁用 GUI 凭证库，优先读环境变量）
            "DEEPSEEK_API_KEY": "...", 
        }
        
        cmd = [
            "dsh",
            "--profile", "headless",
            "--patch", str(self.dsh_home / "rsi-evolution.patch.yml"),
            "--json",
            task_prompt
        ]
        
        proc = subprocess.run(
            cmd,
            cwd=str(self.workspace_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        return {
            "exit_code": proc.returncode,
            "events": events,
            "stderr_reasoning": proc.stderr,  # 注意：此字段仅供 Actor 自省，严禁传给 Verifier
        }
```

### 2. 开发 `deepseek-harness` 侧的记忆挂载插件（`dsh-plugin-rsi-memory`）

`RSIAgent` 的精髓在于将探索经验结构化为持久化 Memory。如果在 `dsh` 中通过普通对话消息或 MCP 工具注入记忆，会导致多轮对话 Context 持续膨胀或模型漏调工具。

利用 `deepseek-harness` 的 **Cordis 依赖注入机制**，直接将 `RSIAgent` 生成的记忆分流到 `systemPrompt`（写死核心红线）和 `skills`（按需检索 SOP）：

```typescript
// packages/dsh-plugin-rsi-memory/src/index.ts
import { Context } from 'cordis'
import * as fs from 'node:fs'
import * as path from 'node:path'

export const name = 'dsh-plugin-rsi-memory'
// 必须显式声明依赖注入，否则 Cordis 访问属性时会直接抛异常
export const inject = ['systemPrompt', 'skills']

export interface Config {
  memoryRoot: string
}

export function apply(ctx: Context, config: Config) {
  const constraintsFile = path.join(config.memoryRoot, 'constraints_and_lessons.md')
  const skillsDir = path.join(config.memoryRoot, 'procedures')

  // 1. 挂载全局核心避坑指南到 System Prompt Section
  // 优势：每轮重新渲染（替换而非追加），100轮对话也不会撑爆上下文，且无需工具调用
  ctx.systemPrompt.registerSection({
    id: 'rsi-core-constraints',
    order: 8500, // 放在基础指令之后、环境后缀之前
    text: () => {
      if (!fs.existsSync(constraintsFile)) return ''
      const content = fs.readFileSync(constraintsFile, 'utf-8').trim()
      return content ? `## Verified Environment Constraints & Failure Lessons\n${content}` : ''
    }
  })

  // 2. 将 RSIAgent 沉淀的操作流（Procedures）注册为动态 Skill Provider
  const registration = ctx.skills.registerProvider({
    name: 'rsi-evolved-procedures',
    async list() {
      if (!fs.existsSync(skillsDir)) return []
      const files = fs.readdirSync(skillsDir).filter(f => f.endsWith('.json'))
      return files.map(file => {
        const meta = JSON.parse(fs.readFileSync(path.join(skillsDir, file), 'utf-8'))
        return {
          name: meta.name,
          description: meta.description, // 模型根据此描述决定是否加载该 SOP
          source: 'runtime',
          modelInvocable: true,
          userInvocable: true,
        }
      })
    },
    async get(skillName: string) {
      const filePath = path.join(skillsDir, `${skillName}.json`)
      const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'))
      return {
        name: data.name,
        description: data.description,
        source: 'runtime',
        content: data.markdownBody, // 包含验证过的具体步骤与脚本调用方式
      }
    }
  })

  // 监听记忆目录变更（DRS 阶段每轮进化后自动触发 invalidate 清空缓存）
  if (fs.existsSync(skillsDir)) {
    fs.watch(skillsDir, () => registration.invalidate())
  }
}
```

### 3. 设计三阶段持续进化流水线（BRS \rightarrow DRS \rightarrow 冻结部署）

按照 `RSIAgent` 的三阶段范式，构建针对你的 `deepseek-harness` 智能体工程的持续进化闭环：

- **第一阶段：广度递归自探索（Phase 1: BRS - 批量探路）**
  - **触发时机**：智能体接入新代码库、新工具链或新业务环境时。
  - **执行流程**：
    1. `Curriculum Agent` 扫描目标环境（如项目目录结构、MCP 工具列表、依赖配置），并发生成 N 个不同维度的探索任务（例如：“构建并运行单测”、“修复某类 Lint 报错”、“调用内部 API 查询数据”）。
    2. 并发启动 N 个隔离的 Docker 容器，每个容器运行 `dsh --profile headless --json` 挂载当前的共享初始记忆目录 `memory_v0`。
    3. `Verifier Agent` 独立进入容器检查执行结果（测试是否真通过、产物是否合规）。
    4. 一波并发结束后，`RSIAgent` 的 `Memory Consolidator` 依次读取各容器的成败轨迹，去重并合并生成 `memory_v1`（提取通用环境约束写入 `constraints_and_lessons.md`，提取成功操作序列写入 `procedures/`）。
- **第二阶段：深度递归自探索（Phase 2: DRS - 专攻盲区与线上错题集）**
  - **触发时机**：BRS 结束后的强化阶段，或**每日定时从生产环境回流失败会话**。
  - **结合 `dsh` 会话落盘机制的增强做法**：
    1. `deepseek-harness` 会将所有生产会话压缩落盘在 `~/.dsh/sessions/.../session.jsonl.zstd`。
    2. 编写定时采集脚本，筛选出用户打断、报错退出或重试次数过多的 Session 日志，喂给 `Curriculum Agent`。
    3. `Curriculum Agent` 针对这些脆弱环节（Fragile Successes）和边界条件（Boundary Conditions），串行生成难度递增的变体任务。
    4. 每完成一个深度任务并通过 `Verifier Agent` 独立校验后，**立即更新** `memory` 目录，触发 `dsh-plugin-rsi-memory` 的 `registration.invalidate()`，让下一个递进任务立刻用上刚刚学到的经验。
- **第三阶段：生产测试时记忆冻结与复用（Phase 3: Test-time Memory Reuse）**
  - **触发时机**：日常生产服务（Web UI / CI 自动化 / IM 机器人）。
  - **执行流程**：关闭 `Curriculum Agent` 和记忆写入通道，将验收达标的 `memory_vX` 目录以只读（Frozen）方式挂载到生产环境的 `dsh` 实例中。此时可以考虑保留一个轻量级的 `Verifier` 作为 `dsh` 提交最终结果前的自检 Hook。

## 三、 关键工程避坑指南（基于两个项目的底层机制）

在将两者对接时，有 4 个底层技术细节直接决定成败：

1. **修复 `dsh --profile headless` 下后台子代理（Subagent）结果静默丢失问题**
   - **底层隐患**：`deepseek-harness` 的 `dsh-base` 默认将 `tool-subagent` 配置为 `backgroundMode: continuable`（异步通知驱动续轮）。但在 `headless` 模式下，主 Agent 在当前轮次调用 `await agent.whenIdle()` 后会立即退出销毁运行时，导致尚未跑完的后台子代理结果被直接丢弃，输出残缺结果。
   - **解决方案**：在供 `RSIAgent` 调用的 `rsi-evolution.patch.yml` 中，必须将子代理强制改为**阻塞模式（Blocking）**，或者引入前台子代理插件（如 `@tintinweb/pi-subagents` 并设置 `run_in_background: false`），确保 `RSIAgent` 拿到完整的执行轨迹。
2. **严格隔离 Verifier Agent 的信息视野（防止“自欺欺人”）**
   - **底层隐患**：`RSIAgent` 论文明确指出，一旦 `Verifier` 看到 `Actor` 的私有推理过程，极易被 `Actor` 的幻觉说服，从而将错误规则写入持久化记忆（Memory Poisoning）。
   - **解决方案**：`dsh --profile headless` 运行时会将推理过程输出到 `stderr`（带 `dsh: reasoning:` 前缀）。在桥接层中，**严禁将 `stderr`、会话内部的思维链或 `memory` 目录展示给 `Verifier Agent`**。`Verifier` 只能接收：`[原始任务要求] + [沙箱环境的客观状态快照（如 pytest 报告、git diff、截图）]`。
3. **保护 `deepseek-harness` 的 System Prompt KV Cache 命中率**
   - **底层隐患**：`dsh-system-prompt` 的设计高度重视前缀稳定性（Prefix-stability）——只要前面的 System Prompt Token 不变，就能最大化复用大模型 API 的 KV Cache。
   - **解决方案**：不要把所有进化出来的经验都塞进 `ctx.systemPrompt`。只将全局高频、极简的核心红线（控制在 1000 Tokens 以内）放在 System Prompt Section 的靠后位置（如 `order: 8500`）；而将具体场景的 SOP、长代码模板全部放入 `@deepseek-ai/dsh-skill`，由模型在需要时通过 Tool 动态加载。
4. **建立 Memory 的 Git 版本控制与回归门禁（Regression Gate）**
   - **底层隐患**：`RSIAgent` 的失败分析指出，不完善的验证可能导致某次进化写入一条“过度泛化的错误规则”，导致原本能做对的任务反而退化。
   - **解决方案**：将 `memory/` 目录（包含 `constraints_and_lessons.md` 和 `procedures/*.json`）纳入 Git 管理。每次 DRS 阶段产出新版本记忆后，先在黄金基准测试集（Golden Benchmark）上跑一遍 Phase 3 评估，只有成功率不降反升时，才自动合并到生产分支。