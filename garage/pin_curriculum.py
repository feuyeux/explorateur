"""把波次的题目钉死：`pin_curriculum.py`。

为什么必须有这个东西
====================

A 线想做「记忆有没有害」的对照，就得比**同一道题**在有记忆 / 无记忆下的表现。
2026-10-22 真跑了两臂，结果做不成对照：

    有记忆臂：抽到 food names 十二语种视频线（要碰渲染，重）→ 950s 上限里 0 个项目
    无记忆臂：抽到常规包任务（轻）→ 1578s 做完 3 个全 PASS

只看成绩表（0 个项目 vs 3 个全 PASS）很容易写成「记忆有害，这是负迁移」。真相是
**两臂抽到的题不一样**，`memory_control.py` 判 `not_paired` 正是为了挡住这一句。

根因在引擎：Curriculum 从 `TARGET MENU` 自由选题（`curriculum-usine.yaml`），
没有确定性开关，`--memory-seed` 也不参与出题。`phase1_wave.py:670` 调
`_author_wave()` 拿决策、`:676` 写盘——**中间没有「读入既定决策」的入口**。

它怎么工作
==========

`théâtre/` 是 vendored fork，补丁必须逐字节不变（PROVENANCE 纪律），所以不在
引擎里开洞，而是在 `garage/` 这一层 **wrap** `_author_wave`：

    第一次跑（不 pin）：把 wave_001 的 curriculum_decision.json 存下来
    第二次跑（--pin-projects <那份 json>）：Curriculum 的决策被替换成它

替换**不是伪造**：`raw` 字段仍然走引擎自己的 `parse_wave_handoff()` 解析路径，
所以校验逻辑一条没绕过（`decision == WAVE`、projects 非空、字段齐全）。被换掉的
只有「抽哪道题」这一个自由度——那正是要控制的变量。

fail-closed 的三条
==================

1. **接缝漂移就报错，不静默降级**：`_author_wave` 的签名或 `WaveDecision` 的字段
   变了，这里 raise，而不是让 patch 变成 no-op（那样两臂又会抽到不同的题，而人
   以为已经钉住了）。
2. **钉住的文件必须能被引擎自己的解析器接受**：用 `parse_wave_handoff()` 验一遍，
   不过就 raise——不能靠「我拼的 dict 应该对」。
3. **只替换 `WAVE` 决策**：若引擎算出 `SATURATED` / `STALLED`，那是「题目池用完了」
   或「卡住了」的信号，**不许**被钉住的文件盖掉——那不是选题自由度，那是终止条件。

它**能**做什么、**不能**做什么
==============================

**能**：同一进程内的后续波次复用同一道题（首波由 Curriculum 现做 fixture，后续
波次 replay 它）。

**也能**：跨运行复用——**只要你给出 fixture 存档**（`--fixture-from`）。

跨运行这条曾经以为不行。2026-10-22 实测钉住上一轮的 `foodnames_d1_hero` 重跑，
40 秒后炸在

    cp: cannot stat '/home/user/evolution_wave/foodnames_d1_hero/evolution_project'

当时把结论写成「fixture 随 guest 销毁、跨运行不可行」。**那个结论是错的，错在没查
存档**：`_capture_wave_fixtures`（`phase1_wave.py:313`）在**每个** episode 里都
留了 `fixtures/materials.tgz`，tar 的顶层就是 `evolution_project/`。第一臂的
`ep001/fixtures/materials.tgz` 33.5 MB 一直在盘上。

所以现在：给出 `--fixture-from <episode 目录>` 就把它解回
`WAVE_ROOT/<id>/`，解完仍让**引擎自己的** `_validate_wave_fixtures` 判一次
（文件到位不等于它认得）。没给或恢复失败，才按缺失处理。

> **这条要记住的不是「pin 能用」，是「我把没找当成不存在了」。** 报 `PinFixtureMissing`
> 那一刻，错误信息写的是「fixture 随 guest 销毁了」——一个**听起来很有道理、
> 但没验证过**的因果。真正的事实是它被 `_capture_wave_fixtures` 存下来了。
> 「我验不了」与「它不存在」必须分开，这次是把两者合并了。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 已经装过的标记：重复安装会套两层 patch，第二层拿到的 `stock` 是第一层的产物，
# 于是「接缝漂移检测」比的是打过补丁的字符串——那条检查就失真了。
_INSTALLED = False


class PinFixtureMissing(RuntimeError):
    """钉住的题在 guest 里没有可 replay 的 fixture。

    单独一个类型，是因为它**不是运行故障**：它是「这个用法本身不成立」。
    上层据此可以说「你钉的题不可能被 replay」而不是「这一轮跑挂了」。
    """


def _fixture_present(wave_mod: Any, vm: Any, project_id: str) -> bool:
    """用**引擎自己的** `_validate_wave_fixtures` 判 fixture 在不在。

    不自己拼 `test -d` 命令：那条判据在引擎里（`phase1_wave.py:158`），复写一份
    就会漂——引擎改了判据（比如加「非空」），这里还在用旧口径。
    """
    if vm is None:
        # 拿不到 vm 时不假装验过：保守返回 True，让引擎在它自己那一刻判。
        # **不能返回 False**——那会把「我验不了」说成「fixture 不存在」。
        return True
    validate = getattr(wave_mod, "_validate_wave_fixtures", None)
    if validate is None:
        raise RuntimeError(
            "pin_curriculum 接缝漂移：_validate_wave_fixtures 不见了。"
            "fixture 判据是它的，不能自己另写一份")

    class _OneProject:
        def __init__(self, pid: str) -> None:
            self.project_id = pid

    class _OneDecision:
        def __init__(self, pid: str) -> None:
            self.projects = (_OneProject(pid),)

    return bool(validate(vm, _OneDecision(project_id)))


def load_pinned(path: Path) -> dict[str, Any]:
    """读入要钉住的 curriculum 决策，并**用引擎自己的解析器验一遍**。

    直接 `json.loads` 之后不验就塞进 `WaveDecision` 是危险的：引擎的
    `parse_wave_handoff()` 有一整套字段约束（`decision` 三选一、`rationale`
    非空、`projects` 是 list、`WAVE` 时非空）。绕过它等于绕过校验。
    """
    from explore.phase1_wave import parse_wave_handoff

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"--pin-projects 读不了 {path}: {exc}") from exc

    decision = parse_wave_handoff(text)
    if decision is None:
        raise RuntimeError(
            f"--pin-projects 的文件过不了引擎自己的解析器：{path}。"
            f"它必须是一份 curriculum_decision.json（含 decision/rationale/projects）")
    if decision.decision != "WAVE":
        raise RuntimeError(
            f"--pin-projects 钉住的是 {decision.decision}，只有 WAVE 能被钉。"
            f"SATURATED / STALLED 是「题目池用完了 / 卡住了」，盖掉它等于藏起终止条件")
    if not decision.projects:
        raise RuntimeError(f"--pin-projects 的文件里一个项目都没有：{path}")
    return {
        "decision": decision.decision,
        "rationale": decision.rationale,
        "projects": [
            {"id": p.project_id, "instruction": p.instruction}
            for p in decision.projects
        ],
    }


def _restore_fixture(
    wave_mod: Any, vm: Any, project_id: str, fixture_from: Path | None
) -> bool:
    """把存档里的 `evolution_project/` 解回 `WAVE_ROOT/<id>/`。

    存档就是 episode 的 `fixtures/materials.tgz`——`_capture_wave_fixtures`
    （`phase1_wave.py:313`）在**每个** episode 里都留了一份，tar 的顶层就是
    `evolution_project`。所以「上一轮的 fixture」从来没有真的丢，只是没人把它
    放回去。

    **推进 guest，让 guest 自己解压**，不在宿主侧解：真 guest 的 `WorktreeVM`
    只承诺 `push_file` / `fetch_file`（`guest_env.py:962`），没有路径映射方法
    （`guest_to_host` 在 `WorktreeEnv` 上，VM 拿不到）。

    > 这一版是改过的。第一版在宿主侧 `tarfile.extractall(vm.guest_to_host(...))`，
    > 在真 guest 上直接返回 False、整轮记 `infra`——因为 `WorktreeVM` 没有那个
    > 方法。当时的自检用的是自写的假 vm，**假对象恰好有那个方法**，于是全绿。
    > 「自检只测内存里的假对象，等于没测」这条，是踩过才发现它在自己身上。
    """
    if vm is None or fixture_from is None:
        return False

    archive = Path(fixture_from)
    if archive.is_dir():
        # 两种都收：episode 目录（下面有 `fixtures/`）与 `fixtures/` 本身。
        # 只认前者会让「我指向了装着 tgz 的那个目录」这种自然用法失败，
        # 而它的失败长相是「返回 False」，看不出是路径拼错了。
        for candidate in (archive / "fixtures" / "materials.tgz",
                          archive / "materials.tgz"):
            if candidate.is_file():
                archive = candidate
                break
        else:
            return False
    if not archive.is_file():
        return False

    wave_root = getattr(wave_mod, "WAVE_ROOT", None)
    if not wave_root:
        raise RuntimeError(
            "pin_curriculum 接缝漂移：phase1_wave.WAVE_ROOT 不见了。"
            "fixture 的目标位置由它决定，不能自己写死")

    # ── 推进 guest，再让 guest 自己解压 ────────────────────────────────────
    #
    # 上一版在**宿主侧**用 `tarfile` 解到 `vm.guest_to_host(...)`，在真 guest 上
    # 直接失败：`WorktreeVM` **没有** `guest_to_host`（那是 `WorktreeEnv` 的方法），
    # 于是拿不到映射、返回 False、整轮记 `infra`。
    #
    # **这个错是我自己造的**：验证时用的是自写的假 vm，它恰好有那个方法。
    # 一句「自检只测内存里的假对象，等于没测」——我自己刚犯过一遍（AGENTS.md
    # 第九节那条，2026-10-20 抓到的三个缺陷里就有一个是这个形状）。
    # 真对象只承诺 `push_file` / `fetch_file`（`guest_env.py:962`），
    # 推文件走它，解压交给 guest 的 `tar`。
    staged = f"/home/user/.pin-fixture-{project_id}.tgz"
    push = getattr(vm, "push_file", None)
    if push is None:
        return False
    pushed = push(str(archive), staged)
    if isinstance(pushed, tuple):
        if not pushed[0]:
            return False
    elif not pushed:
        return False

    target = f"{wave_root}/{project_id}"
    out = vm.run_command(
        f"mkdir -p {_q(target)} && "
        f"tar -xzf {_q(staged)} -C {_q(target)} ; "
        f"rm -f {_q(staged)} ; "
        "echo PHASE1_RESTORE_RC=$?", timeout=900) or ""
    if "PHASE1_RESTORE_RC=0" not in out:
        return False

    # **恢复完必须让引擎自己验一次**：文件到位不等于它认得。
    return _fixture_present(wave_mod, vm, project_id)


def _q(text: str) -> str:
    """单引号安全引用（guest 是 POSIX shell）。"""
    return "'" + str(text).replace("'", "'\\''") + "'"


def install(pinned: dict[str, Any], *, fixture_from: Path | None = None) -> None:
    """wrap `explore.phase1_wave._author_wave`，让每一波都用钉住的项目。"""
    global _INSTALLED
    if _INSTALLED:
        raise RuntimeError("pin_curriculum.install() 被调了两次")

    import explore.phase1_wave as wave_mod

    stock = wave_mod._author_wave

    # ── 接缝漂移检测：签名一变就停，别让 patch 变成静默 no-op ──────────────
    expected_params = {
        "hooks", "vm", "cfg", "target_direction", "previous_wave_outcomes",
        "history", "sink_root", "target_query_conditioned",
    }
    import inspect

    actual = set(inspect.signature(stock).parameters)
    missing = expected_params - actual
    if missing:
        raise RuntimeError(
            f"pin_curriculum 接缝漂移：_author_wave 少了参数 {sorted(missing)}。"
            f"现在它是 {sorted(actual)}")
    if not hasattr(wave_mod, "WaveDecision") or not hasattr(wave_mod, "WaveProject"):
        raise RuntimeError("pin_curriculum 接缝漂移：WaveDecision / WaveProject 不见了")

    def pinned_author_wave(**kwargs: Any):
        decision, history = stock(**kwargs)
        # **只替换 WAVE**：SATURATED / STALLED 是终止信号，不是选题自由度。
        if decision.decision != "WAVE":
            return decision, history

        # ── fixture：先试着恢复，恢复不了才拒绝 ────────────────────────────
        #
        # 引擎要求 Curriculum 在 `WAVE_ROOT/<project_id>/evolution_project` 放一份
        # fixture（`phase1_wave.py:158` 的 `_validate_wave_fixtures`，由
        # `publication_ready`（:251）与 replay 前（:288）各验一次）。那份 fixture
        # 是 Curriculum 在 guest VM 里现做的，**随 guest 销毁**。
        #
        # 但它不是真的丢了：`_capture_wave_fixtures`（`phase1_wave.py:313`）在每
        # 个 episode 里留了 `fixtures/materials.tgz`，里面就是
        # `evolution_project/` 那棵树。**2026-10-22 实测确认**：
        # `ep001/fixtures/materials.tgz` 33.5 MB，tar 首项即 `evolution_project`。
        #
        # 所以跨运行 pin 是可行的——只要先把它解回 `WAVE_ROOT/<id>/`。上一轮这里
        # 直接抛 `PinFixtureMissing`，那是**当时没查清存档**，把「我没找」写成了
        # 「不存在」。现在改成：`--fixture-from <episode 目录>` 给出存档就先恢复；
        # 没给或恢复不了，才按缺失处理（错误信息照样说清两种可能）。
        vm = kwargs.get("vm")
        for project in pinned["projects"]:
            if _fixture_present(wave_mod, vm, project["id"]):
                continue
            restored = _restore_fixture(wave_mod, vm, project["id"], fixture_from)
            if not restored:
                raise PinFixtureMissing(
                    f"钉住的题在 guest 里没有 fixture，也恢复不出来：{project['id']}。"
                    f"两条路：① 同一进程内的后续波次——首波由 Curriculum 现做，"
                    f"后续波次自然复用；② 跨运行——用 `--fixture-from` 指向上一轮"
                    f"某个 episode 的目录（它有 `fixtures/materials.tgz`，里面就是"
                    f"`evolution_project/` 那棵树）。两者都不满足时无法 replay："
                    f"fixture 随 guest 销毁，钉住的只是一段题面文字。")

        raw = json.dumps(pinned, ensure_ascii=False)
        replaced = wave_mod.WaveDecision(
            decision="WAVE",
            rationale=(
                f"[pinned] {pinned['rationale']}"
            ),
            projects=tuple(
                wave_mod.WaveProject(project_id=p["id"], instruction=p["instruction"])
                for p in pinned["projects"]
            ),
            raw=raw,
        )
        return replaced, history

    wave_mod._author_wave = pinned_author_wave
    _INSTALLED = True


def describe(pinned: dict[str, Any]) -> str:
    """人读的一行摘要，写进日志让「这次是被钉住的」有据可查。"""
    ids = ", ".join(p["id"] for p in pinned["projects"])
    return f"题目已钉住（{len(pinned['projects'])} 个）：{ids}"
