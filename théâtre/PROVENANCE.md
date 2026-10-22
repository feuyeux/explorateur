# PROVENANCE — théâtre fork of RSIAgent

- **Upstream**: <https://github.com/AetherLabsAI/RSIAgent>
- **Paper**: arXiv 2609.15364 (Curriculum/Actor/Verifier 三角色递归自我改进框架)
- **Vendored at commit**: `4d7ef43770dda341fccd9a5743db92407687c615`
- **Upstream license**: Apache License 2.0（保留于本目录 `LICENSE`；本 fork 的改动同样按 Apache-2.0 提供）
- **Fork date**: 2026-10-16
- **Purpose**: 作为 `explorateur/usine`（feuille 多语种视频生产线）的 RSI 执行骨架。
  适配层（`garage/`）负责环境嫁接（v1 于 2026-10-16 建成并假 LLM 干跑
  12/12 全绿；2026-10-18 P9 真作用力改造后，现行运行手册见
  [../docs/self-evolution.md](../docs/self-evolution.md) §2、§5.5）；本目录内代码
  保持可向上游回步。fork 文档集：PROVENANCE（本文件，
  纪律与补丁清单）、PORTING-NOTES（跨平台病根）、ADAPTATION（实现相对设计稿的
  偏离）；**ARCHITECTURE（机制与图表）已于 2026-10-21 并入
  [../docs/self-evolution.md](../docs/self-evolution.md) §2，原处保留为指针存根
  （正文已删，只留「原节号 → 新节号」映射表）**；
  本目录 `docs/` 是 **fork 自建**的（`reference.md` 上游文档合订 + 论文 PDF +
  历史导出哈希清单；原 `guide.md` 人机交互指南已于 2026-10-21 并入
  [../docs/self-evolution.md](../docs/self-evolution.md) §5.5，**2026-10-22 复核时
  发现它仍留着一份陈旧正文，已同样削成指针存根**）——
  上游 `docs/` 的多篇 markdown 在 2026-10-19 的重构（`8baded4`）里已合并进
  `reference.md`，**不是「冻结不动」**（原本文那么写，与磁盘事实相反）。

## 纪律

1. **不回步上游**：本目录是**普通目录**，没有自己的 `.git`——版本一律由外层 `explorateur` 仓库统一管理（见下条）。永不 fetch/pull/force 更新；需要新上游版本时开**新目录**重新 vendor，避免历史漂移。
2. **POSIX 行为逐字节不变**：所有跨平台补丁只允许两种形态——
   - `os.name` 分支：POSIX 侧原样保留，Windows 侧另行处理；
   - 无分支等价替换：在 POSIX 宿主上语义与传参完全一致（如 `os.path.normpath` →
     `posixpath.normpath`、`str(p.relative_to(r))` → `p.relative_to(r).as_posix()`）。
3. **guest 路径按契约是 POSIX 风格**：任何处理 guest（VM 内）路径/键的宿主侧代码一律用
   `posixpath` / `as_posix()`，不用 `os.path` / `str()`。
4. **Windows 专属 API 只允许 `msvcrt`**（且仅作 `fcntl` 的回退）；bash 发现与路径归一是
   仅有的两个平台抽象点。

## 改动清单（相对上游 `4d7ef43`）

生产代码（7 个文件 + 配置样例）：

| 文件 | 改动 | 形态 |
|---|---|---|
| `core/loop.py` | `_path_within` 改 `posixpath.normpath`（真跨平台 bug：Windows 上 ntpath 把 guest 路径反斜杠化，Actor 私有路径泄漏进 Verifier 上下文） | 无分支等价 |
| `core/loop.py` | Verifier infra-retry 的恢复暂停改为无条件计数（`max(recovery_secs, 0.0)`；Windows 时钟粒度 15.6ms 吞掉微秒级恢复事件；POSIX 传参不变） | 语义修正，POSIX 实际等价 |
| `core/loop.py` | `_call_with_transport_pause` 加连续暂停上限 `llm_infra_max_pauses`（默认 10）。暂停**故意不计入** active-work 预算（`on_pause` 把原点前移），所以时间上限永远终止不了这个循环：provider 持续 402/429/5xx 时原实现无限 sleep、没有任何预算会触发。超限后升级为终态 infra 错误（状态落盘可恢复、infra 受损的候选拿不到分数）；设 0 = 保留旧的无限等待 | 语义修正（修的是两端共有的无限循环，非平台专属） |
| `config/settings.py` | 新增 `llm_infra_max_pauses` 旋钮（默认 10；0 = 保留旧的无限等待），供上一行的暂停上限读取 | 新增功能面；不配置时默认值生效 |
| `llm/client.py` | `_recoverable_transport` 移除 401：端点/密钥映射是进程级缓存（启动时一次加载），同一进程内重发同一请求不可能自愈 401——实测 2026-10-16 起占位 key 连打三天无效暂停循环。401 改为非恢复终态（fail-fast）；402/403/429 保持可恢复（服务端状态可自愈），仍受 `llm_infra_max_pauses` 上界约束 | 语义修正（两端共有：认证错在 POSIX 上同样不该无限暂停） |
| `core/checks.py` | `_BODY_WRITE_OPEN` 捕获 `open()` 的**目标参数**，`_nonscratch_mutations` 的 scratch 豁免从「整段 body 是否含 `/tmp/`」改为**逐写入目标**判定。旧判据是 body 级子串测试，body 里只要出现任何 `/tmp/` 字样，一次针对受评交付物的覆写就整段放行（实测复现） | 语义修正（门禁 fail-open 修复） |
| `explore/provisioning.py` | 新增 `_guest_file_size()`：`stat -c`（GNU）与 `stat -f %z`（BSD）双方言探测，任一不成返回 `None`（未知）而非 `0`。两处 `stat -c` 调用点改走它——BSD/macOS guest 上 `-c` 直接失败，旧代码把失败折成 `sz=0`，`if sz:` 于是**静默跳过**整个分块兜底（纪律 8：未知 ≠ 零） | 无分支等价（GNU 路径逐字节不变；BSD 路径由静默失败变为可用） |
| `llm/client.py` | OpenAI 客户端显式带 `timeout=_sdk_timeout()`（默认 120s，`RSIAGENT_LLM_TIMEOUT_SECS` 可覆盖，0 表示沿用 SDK 默认）与 `max_retries=0`（重试由本模块自己有界的循环负责）。openai 的 `DEFAULT_TIMEOUT` 是 read=600s + 2 次内部重试，一个「连上就卡住」的 provider 会伪装成「慢」而不是「down」，暂停/上限机制根本看不到 | 新增功能面；SDK 默认值下行为不变（仅更快失败） |
| `llm/client.py` | `_PROVIDER_COUNTS` 增量加 `_PROVIDER_LOCK` 守卫（`setdefault/get/+1/store` 非原子，模块自述支持并发；provider 归因是审计数据，丢计数即审计失真） | 无分支等价 |
| `explore/practice_loop.py` | 新增 `_fsync_directory`（os.name 守卫）；5 处裸目录 fsync 调用点改走它；`_fsync_tree` 文件环 Windows 分支 `O_RDWR`（只读句柄 `_commit` 报 EBADF） | os.name 分支 |
| `explore/practice_loop.py` | `_read_memory_tree` 键改 `as_posix()`（记忆键是 guest 侧 POSIX 路径） | 无分支等价 |
| `tools/recover_phase1_wave.py` | `fcntl` try/except ImportError；锁点 Windows 回退 `msvcrt.locking` | os.name 分支 |
| `llm/client.py` | 端点/密钥可重定向 + 逐模型端点路由：`_api_key()` 认 `RSIAGENT_LLM_API_KEY`→`OPENROUTER_API_KEY`→.env 双名；`_base_url()` 认 `RSIAGENT_LLM_BASE_URL`（缺省恒为 OpenRouter）；新增 `_model_endpoints()`/`_client_for(model)`（`RSIAGENT_LLM_ENDPOINTS_FILE` JSON 逐模型 `{base_url,api_key}`；坏/缺文件 fail-closed 回默认，内容永不进日志），`chat()` 走之 | 新增功能面（非平台补丁）；无环境变量时默认路径逐字节不变 |
| `.env.example` | 文档化 `RSIAGENT_LLM_BASE_URL` / `RSIAGENT_LLM_API_KEY` / `RSIAGENT_LLM_ENDPOINTS_FILE` | 注释 |

测试代码（7 个文件改动 + 3 个新文件；除 `test_llm_transport_pause.py` 外，改动件仅影响 Windows 行为）：

| 文件 | 改动 |
|---|---|
| `tests/posix_guest.py`（新） | POSIX guest shell 宿主模拟：POSIX 宿主零变化；Windows 宿主发现 git-bash（不硬编码路径）+ `/usr/bin` 前置 PATH + `python3` shim |
| `tests/test_verifier_isolation.py` | `bash -n` 传 bytes（无 CRLF 翻译）；truncation 测试 `re.sub` 换 lambda（Windows 反斜杠路径触发坏转义）、Windows 中和 `chown /proc/self/fd/1` 守卫、`/dev/stdout` 行 POSIX 条件化、bash 经 `posix_guest` 发现 |
| `tests/test_practice_loop.py` | `LocalCommandVM` 走 `posix_guest.run_guest_command`；三处路径比较 `as_posix()`；`0o600` 权限断言 POSIX 守卫（`mkstemp` 的 owner-only 位形 POSIX 专属） |
| `tests/test_phase1_wave_authoring.py` | `LocalWaveVM` 走 `posix_guest.run_guest_stdout`（WSL bash 在另一文件系统上对 Windows 路径静默 no-op，探测全在说谎） |
| `tests/test_llm_endpoint.py`（新） | 逐模型端点路由 7 测试：无映射→默认 OpenRouter 逐字节不变；坏 JSON/缺文件 fail-closed；映射生效时逐模型独立客户端 |
| `tests/test_llm_transport_pause.py` | 上游文件增补 5 测试：持久 outage 超限升级为终态（不再无限暂停）；`llm_infra_max_pauses=0` 保留旧的无限等待；SDK timeout 显式有界；并发下 provider 计数不丢；401 为终态不可恢复（对照 402 可恢复）——平台无关 |

补丁面合计（对上游 `4d7ef43`）：**24 个跟踪文件 ±798/648 行**（含 README/docs 链接重排与上游文档合订进 `reference.md`）+ 3 个新测试文件（`tests/posix_guest.py` **129 行**帮手；`tests/test_llm_endpoint.py` 112 行 / 7 测试；`tests/test_llm_transport_pause.py` 398 行 / 增补 5 测试）。

> **这两个数现在没法在本仓复算，读的时候要知道**：上游 `4d7ef43` 是 vendored 快照的基线，而本目录**没有自己的 `.git`**（纪律 1），所以 `git diff 4d7ef43` 在这里不成立。`±798/648` 是 fork 当时量下并记录在此的数，之后每次改 fork 文件它只会更旧。**要更新它，唯一的办法是拿一份干净的 `4d7ef43` 出来做 diff**——不要凭感觉改数字。（`posix_guest.py` 原写 326 行，实测 129 行，2026-10-21 更正；行数变了而没人改这一行，正是「手抄派生的数」的典型下场。）

## 已知的 POSIX-only 面（刻意不移植）

以下测试测的是**被适配层整体替换的机器**（QEMU/OSWorld guest 传输、provisioning、
release wrapper 等），Windows 便携范围将其排除，属预期：

`tests/test_ale_public_text.py`、`test_ale_rsi.py`、`test_ale_checkpoint_timeout.py`、
`test_usersim_runtime.py`、`test_vm_lifecycle_and_wave_recovery.py`、
`test_provisioning.py`、`test_provisioning_venv.py`、
`test_verifier_scratch_permissions.py`、`test_verifier_scratch_export.py`、
`test_target_isolation.py`、`test_rollback_passive_browser_probe.py`、
`test_public_batch.py`、`test_actor_boundary.py`、`test_controller_oom.py`、
`test_guest_transport.py`、`test_guest_signal_response.py`、`test_release_wrapper.py`、
`scripts/run_rsi.sh`（POSIX-only 发布包装器；usine 编排器是纯 Python，见 `run_usine.py`）。

排除清单如新增适配层后发生变化，更新本节与 `PORTING-NOTES.md`。
