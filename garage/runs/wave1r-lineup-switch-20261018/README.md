# wave1r-lineup-switch-20261018 —— 为什么留在这里（不是可删的垃圾）

**一句话**：2026-10-18 晚「换阵容」那一次 Phase-1 波次的实录。它是三份历史归档里**唯一一份真把模型调起来过**的——上一步 `wave1-blocked-*` 死在 401，这一份能走到 `iter 1/2`、能看到真实 token 账单，然后撞在 HTTP 400 上。

## 里面是什么

| 文件 | 是什么 |
|---|---|
| `run.log` | 234 KB 的完整运行日志（**这批的主证据**） |
| `events.jsonl` | 波次事件流，只有两条：`PHASE1_WAVE_STARTED`（7 个项目）与一条 `PHASE1_BRANCH_EXCEPTION` |

## 这一轮走到了哪一步

日志开头是**装配全过**的形态（逐条可复算）：

```
verifier adapter installed: WorktreeVerifierExecutor + substrate-true
actor system prompt patched for the usine substrate (core.actor + core.loop)
distribution fence clear: 712 shingle(s) disjoint from 707 audited source(s)
usine corpus built: 712 shingles from 1 text(s)
worktree guest up: posix -> /Users/han/.cache/rsi-usine-vm/guest-2e143be3172
usine harness link anchor staged into the guest disk root: 1 root(s)
```

然后**模型真的答了**，而且不止一次：

```
POST https://fuyao-ai-gateway.xiaopeng.link/v1/chat/completions "HTTP/1.1 200 OK"
fuyao-work usage: in=4770 out=2151
iter 1: program (python, 3100 chars)   →  exit=0 secs=1
iter 2: program (python, 1617 chars)   →  exit=0 secs=0
```

**这两行是重点**：`iter 1`、`iter 2` 说明引擎的"读—写程序—跑—看结果"那圈**真的转了两圈**，不是卡在装配或鉴权上。

## 为什么停

`events.jsonl` 的那条异常：

```
"classification": "infra",
"error": "MiniMax-M3 transport failure HTTP 400: {'type': 'bad_request', ...}"
```

**HTTP 400**（不是 401）——换阵容之后鉴权通了，撞的是**请求格式**。这类失败与智能体能力无关，属于基础设施/协议层。

## 为什么这是「留」而不是「删」

- **它是「引擎真能转起来」的最早证据。** 想证明这套东西不是纸上谈兵，`iter 1` / `iter 2` / 真实 `usage` 这三样比任何总结都硬。
- **它记录了一次协议层的真实报错。** 后来所有「提案通道不稳」的排查都建立在"400 / 502 / 截断"这些具体现象上，而这一份是最早的 400 样本。
- **它是 macOS 主机的实录**（路径 `/Users/han/...`）。本仓库的跑批现在主要在 Windows 上，**跨平台形态的原始凭证只有这一份**。

## 别拿它当什么用

- **别拿它当「分数」。** 这一轮没跑到判分阶段，`events.jsonl` 里没有任何 criteria 读数。
- **别拿它当「引擎有缺陷」的证据。** 失败在协议层。
- **别拿它的路径当真。** 日志里的 `/Users/han/...` 与 `.venv/theatre-mac/` 是当时那台 mac 的形态，在本仓库当前布局里已不存在——照着它找文件会找不到。

## 同一批的另外两份

- [`../wave1-blocked-20261018/`](../wave1-blocked-20261018/) —— 更早一次，死在 184 次 HTTP 401。
- [`../dsh-sdk-first-task-20261018/`](../dsh-sdk-first-task-20261018/) —— **跑成功的那份**，是 `smoke_agent_surface.py` 等门禁读的**承重夹具**，**不许删**。
