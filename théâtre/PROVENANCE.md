# PROVENANCE — théâtre fork of RSIAgent

- **Upstream**: <https://github.com/AetherLabsAI/RSIAgent>
- **Paper**: arXiv 2609.15364 (Curriculum/Actor/Verifier 三角色递归自我改进框架)
- **Vendored at commit**: `4d7ef43770dda341fccd9a5743db92407687c615`
- **Upstream license**: Apache License 2.0（保留于本目录 `LICENSE`；本 fork 的改动同样按 Apache-2.0 提供）
- **Fork date**: 2026-10-16
- **Purpose**: 作为 `explorateur/usine`（feuille 多语种视频生产线）的 RSI 执行骨架。
  适配层（`benchmarks/usine/`）负责环境嫁接（v1 于 2026-10-16 建成并假 LLM 干跑
  12/12 全绿；2026-10-18 P9 真作用力改造后，现行运行手册见
  [../benchmarks/usine/README.md](../benchmarks/usine/README.md)）；本目录内代码
  保持可向上游回步。fork 文档集：PROVENANCE（本文件，
  纪律与补丁清单）、PORTING-NOTES（跨平台病根）、ADAPTATION（实现相对设计稿的
  偏离）、ARCHITECTURE（机制与图表）；上游 `README.md` 与 `docs/` 冻结不动。

## 纪律

1. **不回步上游**：`.git` 目录保留（HEAD 即上述 commit），但永不 fetch/pull/force 更新；
   需要新上游版本时开**新目录**重新 vendor，避免历史漂移。
2. **POSIX 行为逐字节不变**：所有跨平台补丁只允许两种形态——
   - `os.name` 分支：POSIX 侧原样保留，Windows 侧另行处理；
   - 无分支等价替换：在 POSIX 宿主上语义与传参完全一致（如 `os.path.normpath` →
     `posixpath.normpath`、`str(p.relative_to(r))` → `p.relative_to(r).as_posix()`）。
3. **guest 路径按契约是 POSIX 风格**：任何处理 guest（VM 内）路径/键的宿主侧代码一律用
   `posixpath` / `as_posix()`，不用 `os.path` / `str()`。
4. **Windows 专属 API 只允许 `msvcrt`**（且仅作 `fcntl` 的回退）；bash 发现与路径归一是
   仅有的两个平台抽象点。

## 改动清单（相对上游 `4d7ef43`）

生产代码（4 个文件 + 配置样例）：

| 文件 | 改动 | 形态 |
|---|---|---|
| `core/loop.py` | `_path_within` 改 `posixpath.normpath`（真跨平台 bug：Windows 上 ntpath 把 guest 路径反斜杠化，Actor 私有路径泄漏进 Verifier 上下文） | 无分支等价 |
| `core/loop.py` | Verifier infra-retry 的恢复暂停改为无条件计数（`max(recovery_secs, 0.0)`；Windows 时钟粒度 15.6ms 吞掉微秒级恢复事件；POSIX 传参不变） | 语义修正，POSIX 实际等价 |
| `explore/practice_loop.py` | 新增 `_fsync_directory`（os.name 守卫）；5 处裸目录 fsync 调用点改走它；`_fsync_tree` 文件环 Windows 分支 `O_RDWR`（只读句柄 `_commit` 报 EBADF） | os.name 分支 |
| `explore/practice_loop.py` | `_read_memory_tree` 键改 `as_posix()`（记忆键是 guest 侧 POSIX 路径） | 无分支等价 |
| `tools/recover_phase1_wave.py` | `fcntl` try/except ImportError；锁点 Windows 回退 `msvcrt.locking` | os.name 分支 |
| `llm/client.py` | 端点/密钥可重定向 + 逐模型端点路由：`_api_key()` 认 `RSIAGENT_LLM_API_KEY`→`OPENROUTER_API_KEY`→.env 双名；`_base_url()` 认 `RSIAGENT_LLM_BASE_URL`（缺省恒为 OpenRouter）；新增 `_model_endpoints()`/`_client_for(model)`（`RSIAGENT_LLM_ENDPOINTS_FILE` JSON 逐模型 `{base_url,api_key}`；坏/缺文件 fail-closed 回默认，内容永不进日志），`chat()` 走之 | 新增功能面（非平台补丁）；无环境变量时默认路径逐字节不变 |
| `.env.example` | 文档化 `RSIAGENT_LLM_BASE_URL` / `RSIAGENT_LLM_API_KEY` / `RSIAGENT_LLM_ENDPOINTS_FILE` | 注释 |

测试代码（4 个文件改动 + 2 个新文件；改动件仅影响 Windows 行为）：

| 文件 | 改动 |
|---|---|
| `tests/posix_guest.py`（新） | POSIX guest shell 宿主模拟：POSIX 宿主零变化；Windows 宿主发现 git-bash（不硬编码路径）+ `/usr/bin` 前置 PATH + `python3` shim |
| `tests/test_verifier_isolation.py` | `bash -n` 传 bytes（无 CRLF 翻译）；truncation 测试 `re.sub` 换 lambda（Windows 反斜杠路径触发坏转义）、Windows 中和 `chown /proc/self/fd/1` 守卫、`/dev/stdout` 行 POSIX 条件化、bash 经 `posix_guest` 发现 |
| `tests/test_practice_loop.py` | `LocalCommandVM` 走 `posix_guest.run_guest_command`；三处路径比较 `as_posix()`；`0o600` 权限断言 POSIX 守卫（`mkstemp` 的 owner-only 位形 POSIX 专属） |
| `tests/test_phase1_wave_authoring.py` | `LocalWaveVM` 走 `posix_guest.run_guest_stdout`（WSL bash 在另一文件系统上对 Windows 路径静默 no-op，探测全在说谎） |
| `tests/test_llm_endpoint.py`（新） | 逐模型端点路由 7 测试：无映射→默认 OpenRouter 逐字节不变；坏 JSON/缺文件 fail-closed；映射生效时逐模型独立客户端 |

补丁面合计（对上游 `4d7ef43`）：8 个跟踪文件 ±200/69 行 +
2 个新测试文件（`tests/posix_guest.py` 326 行帮手；`tests/test_llm_endpoint.py` 7 测试）。

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
