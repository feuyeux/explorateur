# PORTING NOTES — théâtre 的 Windows 便携化跨平台补丁

记录 2026-10-16 这轮 Windows 便携化跨平台补丁的病根与修法。
纪律与改动总清单见 `PROVENANCE.md`；本文只讲「为什么」。
这些教训的**生产消费方**是适配层传输层 `garage/guest_env.py`
（worktree guest 的 bash 发现 / PATH 自管 / MSYS_NO_PATHCONV / python3 shim
全部按本文病根 4–6 落地；机制见 `ARCHITECTURE.md` §5）。

## 原则

**两个工程（théâtre、usine）都跨平台开发**：Windows 只是当前开发机。
所以所有补丁是「跨平台 bug 修复」而非「Windows 特化」——
要么 POSIX 上语义逐字节不变，要么把 POSIX 专属语义显式标成 POSIX-only。

运行方式：`uv run python -m pytest tests/ ...`。
注意必须是 `python -m`：本仓库测试以顶层包名导入（`core.*`、`explore.*`），
裸 `pytest` 不把仓库根放进 `sys.path`，收集即失败（上游同此）。

## 病根 1：Windows 上没有可 fsync 的目录句柄

`os.open(dir, os.O_RDONLY)` 在 Windows 抛 `PermissionError`（打开目录需要
`FILE_FLAG_BACKUP_SEMANTICS`，Python 不透传）。RSIAgent 的崩溃一致性习惯
（rename 后 fsync 父目录）共 5 处裸调用点。修法：收敛进 `_fsync_directory`
（`os.name` 守卫），POSIX 侧逐字节保留。

同族：`_fsync_tree` 文件环在 Windows 上对**只读**句柄 `_commit` 报 EBADF——
POSIX 允许只读 fd fsync，Windows 不允许；Windows 分支改 `O_RDWR`。

## 病根 2：guest 路径进了宿主路径语义

两处真·跨平台 bug（任何非 POSIX 宿主都会咬，Windows 只是先撞上）：

1. `core/loop.py _path_within` 用 `os.path.normpath`（Windows=ntpath）处理
   guest 传回的 `/home/user/...` 路径 → 反斜杠化后 `startswith("/home/user/")`
   恒假 → **Actor 私有路径泄漏进 Verifier 上下文**（被
   `test_unified_surface_delta_hides_actor_private_path_names` 抓到）。
2. `_read_memory_tree` 用 `str(relative_to)` 生成记忆键 → Windows 得
   `office\layout.md`，而记忆键按契约是 guest 侧 POSIX 路径（要推到
   `~/.memory` 里被 guest 程序按 `/` 引用）。

修法统一：处理 guest 路径一律 `posixpath` / `as_posix()`，POSIX 宿主零差异。

## 病根 3：Windows 时钟粒度吞掉审计事件

Python 3.12 的 `time.time()` 在 Windows 用 `GetSystemTimeAsFileTime`
（粒度 ~15.6ms；3.13 才换 precise 变体）。Verifier infra-retry 的恢复
（`detach_executor`）只花微秒 → 两次 `time.time()` 同 tick → `recovery_secs == 0.0`
→ 旧代码 `if recovery_secs > 0` 直接不记暂停事件 → `infra_pauses` 漏计。
POSIX 时钟 ns 粒度所以从未暴露。修法：事件计数与观测时长解耦
（`_record_transport_pause(max(recovery_secs, 0.0), 1)` 无条件调用；
POSIX 上传参与旧代码完全一致）。

## 病根 4：PATH 上的 bash 是 WSL，活在另一个文件系统上

Windows 上 `subprocess.run(["bash", ...])` 解析到 `C:\Windows\System32\bash.exe`
（WSL）。WSL 里 `rm -rf 'D:\TEMP\...'` 对看不见的路径**静默成功**
（rm -rf 语义），`test ! -e` 恒真——所有「清理/探测」全部说谎但 RC=0，
测试全军覆没且无从下手。修法：`tests/posix_guest.py` 发现 **git-bash**
（共享 Windows 文件系统；不硬编码路径：which("bash") 排 System32 →
which("git") 祖先链 → ProgramFiles 兜底）。

同病根的另一个坑：**从 Windows 父进程直接起 bash（非 login）继承的 PATH 里
System32 排在 MSYS `/usr/bin` 前面**——`find` 撞名解析到 `find.exe`
（"FIND: Parameter format not correct"），`test`/`rm` 因为不撞名而侥幸。
修法：`guest_environment()` 在 Windows 前置 `/usr/bin` 与 `/mingw64/bin`。
生产含义（适配层要点）：**起 bash 时必须自管 PATH，绝不能假设 login 环境**。

## 病根 5：MSYS 对 Windows 原生 exe 的参数改写

MSYS 起原生 exe 时会把「看起来像 POSIX 路径」的参数翻译成宿主路径
（`/home/user/x` → `D:\...\Git\home\user\x`）。guest 契约路径是 POSIX 风格，
必须关掉：`MSYS_NO_PATHCONV=1`。这是**适配层传输的既定设计**
（POSIX 侧恒等映射 + 前缀改写），测试帮手里同步生效。

## 病根 6：`python3` 在 git-bash guest 里不存在

Git for Windows 不带 python3；guest 命令契约里有 `python3 -c ...`
（`_verify_actor_execution_evidence` 的校验脚本）。修法：临时目录生成
`python3` shim（`#!/bin/sh exec "<venv python>" "$@"`），PATH 前置。
MSYS 对常规文件默认合成可执行位，无需 chmod。
**适配层要点**：git-bash guest 的 PATH 必须提供 python3。

## 病根 7：POSIX 专属语义的测试断言

- `0o600` 权限位断言：来自 `mkstemp` 的 owner-only 默认模式，Windows 文件
  模式表达不出 → POSIX 守卫条件化（POSIX 行为不变）。
- `open('/dev/stdout','w')`（truncation 测试的模拟程序）：/dev 是 POSIX 概念 →
  程序行 POSIX 条件化，Windows 侧仍验证 NUL/高位字节载荷与退出码穿透。
- `chown ... /proc/self/fd/1 || exit 125`（特权下放机器的一部分）：MSYS chown
  不能操作 /proc/self/fd → Windows 测试侧替换为 `true`（管道其余部分照跑）。
- `re.sub` 替换串含 `shlex.quote(sys.executable)`：Windows 反斜杠被当转义
  （`re.error: bad escape`）→ 改 lambda 函数替换（替换串变字面量）。

## 测试基建：`tests/posix_guest.py`

| API | POSIX 宿主 | Windows 宿主 |
|---|---|---|
| `posix_bash()` | `None` | git-bash 路径（发现，非硬编码） |
| `bash_argv()` | `["bash"]` | `[<git-bash>]` |
| `guest_environment()` | `None`（继承，行为不变） | PATH 前置 `/usr/bin`、`/mingw64/bin` |
| `run_guest_command(cmd)` | `shell=True`（与原 LocalCommandVM 一致） | git-bash `-c` + shim + `MSYS_NO_PATHCONV=1` |
| `run_guest_stdout(cmd)` | `["bash","-c",cmd] check=True`（与原 LocalWaveVM 一致） | 同左 + guest 环境 |

消费点：`test_practice_loop.LocalCommandVM`、`test_phase1_wave_authoring.LocalWaveVM`、
`test_verifier_isolation` truncation×2 与 `bash -n` 校验。

## 复盘：这轮抓到的可复用教训

1. **「成功」不等于「发生了」**：WSL bash 对不可见路径全部静默成功——跨文件系统
   的 shell 探测必须先证明探测者与被探测对象在同一文件系统。
2. **撞名的命令是定时炸弹**：PATH 上 System32 的 `find`/`sort`/`tar`/`fc`
   会截胡 POSIX 同名工具；非 login bash 绝不能假设 MSYS 工具目录在前。
3. **时钟粒度不是精度问题，是语义问题**：任何「时长 > 0 才记账」的审计逻辑
   都在高粒度时钟平台上静默丢事件；事件与时长解耦。
4. **契约路径用契约库**：guest 是 POSIX 路径 → 宿主侧处理一律 posixpath。
