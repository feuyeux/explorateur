# dsh-sdk-first-task-20261018 —— **承重夹具，不许删**

**一句话**：2026-10-18 dsh SDK 首次真跑的完整实录，同时是 `garage/smoke_agent_surface.py` **硬编码读取的夹具**。删掉它，那道门禁立刻红。

## 谁在读它（删之前先看这一行）

```python
# garage/smoke_agent_surface.py:48
RUNS = HERE / "runs" / "dsh-sdk-first-task-20261018"
```

该脚本文件头（`:7`）也写明了这件事：「本 smoke 读的是一份**历史实录**（`runs/dsh-sdk-first-task-20261018/`），且路径硬编码到当时的 macOS 家目录」。**它不是"顺手留下的旧跑批"**——它是被代码引用的输入。

## 里面是什么

| 文件 | 是什么 |
|---|---|
| `run.mjs` | 那次真跑的驱动脚本（`garage/README.md:504` 把它当**模板**引用） |
| `preflight.mjs` | 起跑前的就绪检查（`README.md:500` 引用） |
| `feuille-usine-loader.mjs` | 插件加载器（`README.md:497` 引用） |
| `feuille-usine.patch.yml` | 装配补丁声明 |
| `run-log.ndjson` | 281 KB 的事件流（**主证据**） |
| `final-response.txt` | 智能体的终局回答 |
| `run-console.log` | 控制台输出 |
| `attempt1-no-tools/` | **第一次尝试（工具没挂上）的对照实录**——同一批证据里最有价值的一份 |

## 为什么 `attempt1-no-tools/` 单独值得留

它是"工具面全空"那类装配病的**原始样本**：同一次任务、同一个模型、同一份提示，**只有工具面不同**，于是两次的 `final-response.txt` 可以直接对比。这类"控制变量"的实录极难重建——要重建得再烧一次真模型的额度。

## 为什么是「留」而不是「删」

- **删它 = 门禁红。** 这一条就够定案了。
- 它被三处文档当**模板**引用（loader / preflight / run.mjs），删了那三处引用全部悬空。
- 它含一组**成对的控制变量实录**（工具面有 vs 无），这是最贵的那种证据。

## 别拿它当什么用

- **别拿它的路径当真。** 里面的 `/Users/han/coding/personal/feuille/benchmarks/...` 是当时那台 mac 的形态，在本仓库当前布局里不存在。`smoke_agent_surface.py` 读的是**同目录下的这几个文件**，不去解析里面写的绝对路径。
- **别原地改它。** 它是历史实录，改了就失去"原始凭证"的身份。要复用就把 `run.mjs` 拷出去当模板改。

## 同一批的另外两份（可以对照读）

- [`../wave1-blocked-20261018/`](../wave1-blocked-20261018/) —— 死在 184 次 HTTP 401。
- [`../wave1r-lineup-switch-20261018/`](../wave1r-lineup-switch-20261018/) —— 鉴权通了、真调了模型、撞 HTTP 400。
