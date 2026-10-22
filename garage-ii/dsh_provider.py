#!/usr/bin/env python3
"""dsh_provider.py —— garage-ii 的 provider 装配：凭据从哪来、patch 怎么生成。

**凭据纪律**（本文件唯一的硬规矩）：

- token **只在进程内存里**，从 MiniMax Code 运行时的凭据店现读现用；
- 落盘的 patch 覆盖里只有**环境变量名**（`apiKeyEnv: MINIMAX_API_KEY`），没有 token 本身；
- token **永不**进仓库、永不进 run 目录、永不进日志；
- 每次调用**重读**一次 token：运行时会自己刷新它，写在盘上的 accessToken 过期后，
  下一次调用读到的就是新的那份。

为什么用 MiniMax 这条线：PATH 上的 dsh 默认走 fuyao 网关，而那把 key
**余额已尽**（实测 `QUOTA: Insufficient Balance`）；`codex` 登出、`claude` 未登录。
MiniMax 运行时自己的 provider 是这台机器上**当下唯一活着**的模型通路。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

#: MiniMax Code 运行时的配置与凭据位置（activeDataDir）。
MINIMAX_DIR = Path.home() / ".minimax"
MINIMAX_CONFIG = MINIMAX_DIR / "config.yaml"
MINIMAX_AUTH = MINIMAX_DIR / "auth" / "prod" / "cn" / "mcode-public" / "auth.json"

#: 传给 dsh 的环境变量名——patch 里写的是**名字**，不是值。
API_KEY_ENV = "MINIMAX_API_KEY"

#: 模型规格（对着运行时 config.yaml 的 MiniMax 条目抄的）。
#: `MiniMax-M3.1` 是 M3.1 这一代在平台上的服务名（平台把它落到 M3 上；
#: 运行时配置里另有一个 `MiniMax-M3.1-Flash`）。实测三个 id 都通。
MINIMAX_MODEL = "MiniMax-M3.1"
MINIMAX_CONTEXT_WINDOW = 512_000
MINIMAX_MAX_TOKENS = 128_000

#: **统一配置**（`explorateur/config/.env`）——仓库里唯一的一处机器本地凭据点。
#: slug → 端点对的解析规则与 RSI 侧（`garage/run_usine.py::_resolve_endpoints`）
#: 一致：先找 `LLM_<SLUG>_*`，再退到组级 `LLM_<GROUP>_*`（最长前缀优先）。
LLM_CONFIG = Path(__file__).resolve().parent.parent / "config" / ".env"
#: 走统一配置的 slug（如 `fuyao-coding`）声明的窗口/输出上限。
#:
#: **窗口不是「模型能吃多少」，是「dsh 敢往里塞多少」**——它同时决定了压缩什么时候触发。
#: dsh 的 `compaction-basic` 策略（`@deepseek-ai/dsh-compaction-basic`）是这么算阈值的：
#:
#: ```text
#: messageBudget = contextWindow − 保留输出(adapter 的 maxTokens)
#: pressureBudget = messageBudget − headroomTokens(默认 65536)
#: thresholdTokens = floor(min(contextWindow × 0.8, pressureBudget))
#: ```
#:
#: 2026-10-20 实测踩坑：窗口取 131072 时，**threshold 只剩 32768**（131072 − 32768 − 65536），
#: 于是海报 rollout 的上下文一过 32K 就触发压缩；而这个网关的模型写的**整段对话摘要**
#: （2,300–2,800 token）永远比被遮蔽的那一两条消息（432–3,111 token）大 →
#: 压缩**每次都失败**（`summary is not smaller than the shadowed content`）→ 每次失败
#: 又是一次 31 秒的模型调用（19 次压缩尝试、10 次摘要 ≈ 烧掉一半时间），
#: 而且 `compaction/prune` 会**把智能体的消息从上下文里删掉**。
#:
#: 于是 262144：threshold = 163840，本题（实测上下文约 30K token）**够不着**，既不压也不剪。
#: 真实窗口够不够？**实测网关接受 344,006 中文字符 = 177,042 input token（HTTP 200）**，
#: 真实窗口 > 177K；而 dsh 会在 163,840 就开始压缩——**永远先于真实上限**。
ENV_CONTEXT_WINDOW = 262_144
ENV_MAX_TOKENS = 32_768


class ProviderError(RuntimeError):
    """provider 装配不起来——消息必须带补救动作。"""


def _config_text() -> str:
    if not MINIMAX_CONFIG.is_file():
        raise ProviderError(
            f"找不到 MiniMax 运行时配置 {MINIMAX_CONFIG}：这个 provider 依赖本机的 "
            f"MiniMax Code 运行时。改用别的 provider，或先装好运行时"
        )
    return MINIMAX_CONFIG.read_text(encoding="utf-8", errors="replace")


def base_url() -> str:
    """MiniMax 的 Anthropic 兼容端点。"""
    m = re.search(r"baseURL:\s*(\S+)", _config_text())
    if not m:
        raise ProviderError(f"{MINIMAX_CONFIG} 里没有 baseURL")
    return m.group(1).strip().strip("\"'")


def access_token() -> str:
    """现读现用的 access token（不过期写进任何文件）。"""
    if not MINIMAX_AUTH.is_file():
        raise ProviderError(f"找不到运行时凭据 {MINIMAX_AUTH}：先在 MiniMax Code 里登录")
    try:
        data = json.loads(MINIMAX_AUTH.read_text(encoding="utf-8", errors="replace"))
    except ValueError as exc:
        raise ProviderError(f"{MINIMAX_AUTH} 读不出来：{exc}") from exc
    records = data.get("records") or {}
    for rec in records.values():
        tok = (rec or {}).get("accessToken")
        if tok:
            return str(tok)
    raise ProviderError(f"{MINIMAX_AUTH} 里没有 accessToken：先在 MiniMax Code 里登录")


def env_with_token() -> dict[str, str]:
    """给子进程用的环境：把 token 放进 `MINIMAX_API_KEY`。"""
    env = dict(os.environ)
    env[API_KEY_ENV] = access_token()
    return env


def llm_config_entries(path: Path | None = None) -> dict[str, str]:
    """读统一配置（扁平 KEY=VALUE）。**只留在内存里**，不落盘、不进日志。"""
    p = Path(path) if path else LLM_CONFIG
    if not p.is_file():
        raise ProviderError(
            f"找不到统一配置 {p}：走网关的 slug 需要它（机器本地凭据只允许出现在那里）"
        )
    out: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and value:
            out[name] = value
    return out


def resolve_llm_endpoint(slug: str, config_path: Path | None = None) -> dict[str, str]:
    """slug → 端点对（`base_url` + `api_key`）。**fail-closed**：缺就报错。

    规则与 RSI 侧一致：先找 slug 自己的 `LLM_<SLUG>_*`，再退到组级
    `LLM_<GROUP>_*`（最长前缀优先）。`fuyao-coding` → `LLM_FUYAO_CODING_*`
    没有就落 `LLM_FUYAO_*`。
    """
    cfg = llm_config_entries(config_path)
    parts = re.sub(r"[^A-Za-z0-9]", "_", slug).upper().split("_")
    for i in range(len(parts), 0, -1):
        stem = "_".join(parts[:i])
        base = cfg.get(f"LLM_{stem}_BASE_URL", "")
        key = cfg.get(f"LLM_{stem}_API_KEY", "")
        if base and key:
            return {"base_url": base, "api_key": key, "stem": stem}
    group = parts[0] if parts else ""
    raise ProviderError(
        f"统一配置里没有 {slug} 的端点对：填 LLM_{'_'.join(parts)}_BASE_URL + "
        f"LLM_{'_'.join(parts)}_API_KEY，或组级 LLM_{group}_BASE_URL + LLM_{group}_API_KEY"
    )


def make_patch(
    path: Path,
    *,
    provider: str,
    model: str,
    base_url: str,
    context_window: int = MINIMAX_CONTEXT_WINDOW,
    max_tokens: int = MINIMAX_MAX_TOKENS,
    api: str = "anthropic-messages",
) -> Path:
    """写一份 cordis patch 覆盖：provider + 插件面 + 审批策略 + 默认模型。

    **插件面必须在这里 insert**：headless/sdk 剖面默认不带 feuille-usine，
    智能体会对着零工具面发 shell（2026-10-18 真宿主首测实录）。

    **审批策略固定 `never`**：花额度的生成提交确定性停摆（视频生成卡在 dispatch 层的
    审批门上，工具不执行）。这一层是**红线**——本层的任何一次跑批都不许烧额度。

    **baseURL 必须是「根」，不能带 `/v1`**：Anthropic SDK 自己会拼 `/v1/messages`。
    带 `/v1` 的 baseURL 会拼出 `/v1/v1/messages`——上游 503
    `direct_route_not_configured`（实测踩过）。

    **凭据不落盘**：`baseURL` 指向本机中继，token 只活在中继进程的内存里；
    这里的 `apiKeyEnv` 只是个占位（会被中继摘掉）。

    ── `api` 决定走哪种线上协议（2026-10-20 实测后加的）────────────
    `anthropic-messages` 与 `openai-completions` 在**同一个网关、同一个模型**
    上，实际耗时差着一倍多：

    | 协议 | 同一硬任务的实际耗时 | 响应里的 reasoning |
    |---|---|---|
    | `/messages`（Anthropic 风格） | 56s / 94s / 102s / 116s | **1.1 万–2.6 万字符**（每次） |
    | `/chat/completions`（OpenAI 风格） | 36s / 41s / 47s | **0** |

    也就是说：**推理块是网关在 Anthropic 风格那一路上默认开的**，而 OpenAI
    风格那一路默认不推理。整条 rollout 的实际耗时大头就砸在这个块上——实测
    base1 的 39.2 分钟里，**23.2 分钟（59%）**是 19 次慢调用的 reasoning
    （每次 9.6k–24.1k 字符），而同一批调用的**可见输出加起来只有 1k 字符**。

    请求参数救不了：`thinking:{type:'disabled'}`、`reasoning:{effort:low}`、
    `reasoning:{enabled:false}` 在 `/messages` 那一路**全部被忽略**
    （实测 reasoning 仍有 1.1 万–2.6 万字符）；`thinking.budget_tokens=4096`
    直接 400。**换协议才有效**。
    """
    plugin_dist = Path(__file__).resolve().parent.parent / "usine" / "packages" / "dsh-plugin" / "dist" / "index.mjs"
    if not plugin_dist.is_file():
        raise ProviderError(
            f"插件产物不在 {plugin_dist}：先跑 pnpm --filter @feuille/dsh-plugin build"
        )
    if api == "openai-completions":
        # 私有网关的 baseURL 说明不了自己：pi-ai 的自动探测会「像 OpenAI 那样」
        # 乱填兼容开关，所以这几个必须**明说**（`catalog.ts` 的 PiAiCompatProfile）。
        # - `supportsStore: false`   不发 `store`（网关不认这个字段）。
        # - `supportsDeveloperRole: false`  系统提示走 `system` 角色（网关认）。
        # - `reasoningEfforts: false`（模型级）**彻底不推理**——网关那一路默认就不推理，
        #   这里再钉死，免得探测给它塞一个 reasoning 参数。
        api_key_env = "OPENAI_API_KEY"
        display = "FuyaoRelay"
        compat = """        supportsStore: false
        supportsDeveloperRole: false"""
    else:
        api_key_env = "ANTHROPIC_API_KEY"
        display = "MiniMaxRelay"
        compat = ""
    patch = f"""# garage-ii 生成的 dsh patch 覆盖（一次性运行产物，落 run root，不进仓库）。
# 凭据不在本文件里：baseURL 指向本机中继，token 只在中继的内存中。
- id: llm-pi-ai
  config:
    providers:
      {provider}:
        displayName: {display}
        api: {api}
        baseURL: {base_url}
        apiKeyEnv: {api_key_env}
        defaultInput:
          - text
{compat}
        models:
          - id: {model}
            name: {model}
            contextWindow: {context_window}
            maxTokens: {max_tokens}
            input:
              - text
""" + (
        """            reasoningEfforts: false
"""
        if api == "openai-completions"
        else ""
    ) + f"""- id: agent-default-model
  config:
    provider: {provider}
    model: {model}
- insert:
    - id: feuille-usine
      name: '{plugin_dist}'
- id: approval
  config:
    policy: never
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(patch, encoding="utf-8")
    return path


class Relay:
    """本机中继的句柄：起一个 `minimax_relay.mjs`，拿到端口，关掉。

    为什么需要它（全部是实测结论）：
    - MiniMax 运行时端点**只认** `Authorization: Bearer`，只发 `x-api-key` → 401。
    - pi-ai 的 anthropic 适配器**只**在 key 形如 `sk-ant-oat*` 时走 Bearer，
      否则一律当 apiKey 发成 `x-api-key`。
    - 两样都带能过鉴权，但平台按 `x-api-key` 的有无选路 → 503
      `direct_route_not_configured`。
    - 中继把 `x-api-key` 摘掉、把 `Authorization` 换上，请求体原样转发。

    顺带的收益：**token 不进磁盘**（落盘的 patch 里只有本机 URL 与占位 key）。
    """

    def __init__(self, script: Path | None = None, extra_args: list[str] | None = None):
        self.script = script or Path(__file__).resolve().parent / "minimax_relay.mjs"
        #: 中继的额外参数（走统一配置时是 `--slug` / `--config`）。
        self.extra_args = list(extra_args or [])
        self.proc = None
        self.port = 0

    def start(self) -> "Relay":
        if not self.script.is_file():
            raise ProviderError(f"中继脚本不在 {self.script}")
        import subprocess

        self.proc = subprocess.Popen(
            ["node", str(self.script), "--port", "0", *self.extra_args],
            stdout=subprocess.PIPE,
            text=True,
        )
        line = self.proc.stdout.readline()
        if not line:
            raise ProviderError("中继起不来：没有回端口")
        info = json.loads(line)
        self.port = int(info["port"])
        return self

    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
            self.proc = None

    def __enter__(self) -> "Relay":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()


__all__ = [
    "ProviderError",
    "API_KEY_ENV",
    "MINIMAX_MODEL",
    "ENV_CONTEXT_WINDOW",
    "ENV_MAX_TOKENS",
    "LLM_CONFIG",
    "access_token",
    "base_url",
    "env_with_token",
    "llm_config_entries",
    "make_patch",
    "resolve_llm_endpoint",
]
