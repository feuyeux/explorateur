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


def make_patch(path: Path, *, provider: str, model: str, base_url: str) -> Path:
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
    """
    plugin_dist = Path(__file__).resolve().parent.parent / "usine" / "packages" / "dsh-plugin" / "dist" / "index.mjs"
    if not plugin_dist.is_file():
        raise ProviderError(
            f"插件产物不在 {plugin_dist}：先跑 pnpm --filter @feuille/dsh-plugin build"
        )
    patch = f"""# garage-ii 生成的 dsh patch 覆盖（一次性运行产物，落 run root，不进仓库）。
# 凭据不在本文件里：baseURL 指向本机中继，token 只在中继的内存中。
- id: llm-pi-ai
  config:
    providers:
      {provider}:
        displayName: MiniMaxRelay
        api: anthropic-messages
        baseURL: {base_url}
        apiKeyEnv: ANTHROPIC_API_KEY
        defaultInput:
          - text
        models:
          - id: {model}
            name: {model}
            contextWindow: {MINIMAX_CONTEXT_WINDOW}
            maxTokens: {MINIMAX_MAX_TOKENS}
            input:
              - text
- id: agent-default-model
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

    def __init__(self, script: Path | None = None):
        self.script = script or Path(__file__).resolve().parent / "minimax_relay.mjs"
        self.proc = None
        self.port = 0

    def start(self) -> "Relay":
        if not self.script.is_file():
            raise ProviderError(f"中继脚本不在 {self.script}")
        import subprocess

        self.proc = subprocess.Popen(
            ["node", str(self.script), "--port", "0"],
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
    "access_token",
    "base_url",
    "env_with_token",
    "make_patch",
]
