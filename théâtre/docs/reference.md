# Reference: architecture, operations, ALE, paper, release

> User-facing walkthrough: [../../docs/self-evolution.md](../../docs/self-evolution.md) §9 (Chinese; the former `docs/guide.md` was merged into that workspace total document on 2026-10-21). Paper PDF: [RSIAgent.pdf](RSIAgent.pdf).
> Historical export hashes: [source-manifest.json](source-manifest.json).

## 1 Architecture

RSIAgent separates task execution, independent verification, curriculum selection, memory
learning, and final benchmark measurement.

| Role | Inputs and authority |
| --- | --- |
| Actor Agent | Operates the guest, reads its durable memory, distills its own verified experiences. |
| Verifier Agent | Inspects candidate evidence with persistent context across revisions; issues PASS, FAIL, or unresolved. |
| Curriculum Agent | Reviews progress, selects the next practice or target attempt; does not grade or author Actor memory. |
| Host harness | Enforces isolation, records artifacts, commits memory at boundaries, invokes the sealed evaluator. |

The Verifier inspects a rollback-protected candidate with the Actor's private artifacts hidden;
its guest-local mutations are rolled back before the Actor resumes. Shared remote services are
not rolled back — use independent accounts or serialize studies that share mutable state.

**Phase 1** — the Curriculum authors a wave of practice projects. Every branch starts from the
same pre-wave memory snapshot, works independently, and receives a grounded Verifier verdict.
All branches must finish valid verification before the same Actors distill experience serially
in authored order; the next wave starts only after those commits are durable. An incomplete or
quarantined branch blocks the wave. Budget checks happen at complete-wave boundaries.

**Phase 2** — starts with an actual target attempt. Both PASS and FAIL ground learning. Under the
default `curriculum_review` the Curriculum reviews even after a PASS and can request more
practice or return readiness; if practice occurs, a fresh attempt on the unchanged target is
required. Readiness is not a correctness verdict. The alternative `verifier_pass` stops after a
target PASS and its memory commit. Neither policy turns an infrastructure error into PASS/FAIL;
`STALLED` and budget exits stay distinguishable from convergence. The Curriculum's default
memory view is read-only; `none` removes it while keeping trajectory and Verifier feedback.

**Phase 3** — the Actor uses frozen memory in the same framework as RSI. Each evaluation starts
with reset interaction history and environment; Actor–Verifier interaction finishes before the
sealed official evaluator runs; Curriculum and memory updates are disabled. Frozen hashes,
release identities, and terminal statuses record what ran. Infrastructure failure is unscored,
not an official zero; evaluator corrections are reported separately.

| Path | Responsibility |
| --- | --- |
| `run_osworld.py`, `run_ale.py` | Public benchmark entrypoints |
| `benchmarks/osworld/pipeline.py` | Protocol validation and three-stage orchestration |
| `benchmarks/osworld/phase1.py`, `explore/phase1_wave.py` | Phase 1 exploration and wave barrier |
| `benchmarks/osworld/phase2.py`, `core/self_evolving_loop.py` | Phase 2 target/practice lifecycle |
| `benchmarks/osworld/task.py` | Frozen-memory execution and sealed evaluation |
| `benchmarks/osworld/evaluator_corrections.py` | Explicit, source-bound corrections |
| `core/`, `llm/`, `env/` | Agent runtime, model transport, guest interface |
| `explore/` | Curriculum orchestration, memory, provisioning, recovery |
| `config/` | Role profiles, runtime paths, benchmark locks |
| `scripts/`, `tools/` | Setup, smoke checks, recovery utilities |

Internal stages run as modules from the checkout, e.g.
`python -m benchmarks.osworld.pipeline --help`. ALE lives under `benchmarks/ale/`: the outer
process owns provisioning and grading, a separate worker runs the shared learning runtime.

## 2 Operations

Run from the checkout with dependencies and the pinned OSWorld environment installed. Export
`RSIAGENT_ROOT` (this checkout) and `OSWORLD_ROOT` (benchmark checkout) in the shell; they are
read before `.env` loading. `RSIAGENT_ENV_FILE` optionally names a private credentials file.
Each machine needs Docker/KVM, the official guest image, gated task/assets access, and website
setup. Assets are not redistributed. `prepare_osworld_v2_release.py --verify-only` verifies a
prepared release; `--refresh-assets` replaces the snapshot deliberately on an idle setup.

Copy `config/osworld/rsi.example.json`, choose a unique `run_name`, change task IDs and the
matching public Phase 1 query. Use a new protocol lineage for a different policy, model, memory
seed, or budget. The example has an eight-project Phase 1 boundary and four concurrent branches;
target Actor watchdog 36,000 s, practice Actor and Curriculum 86,400 s. There is no default
two-practice cap.

```bash
python run_osworld.py --arm both --name <batch_name>   # --dry-run / --concurrency N
bash scripts/run_rsi.sh <protocol.json>                # three phases sequentially
python -m benchmarks.osworld.pipeline --help           # phase-level inspection
```

Inspect `results/recursive_improvement/<run_name>/phaseN/result.json`, then follow recorded
paths. Phase 1 authoring records live under `phase1/curriculum/wave_NNN/`. Check published
projects, completed verdicts, and committed memory — not a live PID. The wrapper performs no
unattended recovery; it exits on failure. No daemon or scheduler is installed.

Begin with one study on a freshly provisioned machine. Independent studies need unique run
names and caches, enough memory/disk/KVM, and independent external application state; two runs
of the same task can interfere through a shared website account even with separate VMs.

**Recovery boundaries** — inspect the failed attempt's `recovery.json`, authoring state, and
preserved runtime; keep the failed attempt and memory snapshot; check for a live recovery first.
Never reuse a quarantined lineage, turn an infrastructure error into a task verdict, or overwrite
a sealed score. Phase 1 offers `--resume-completed-boundary` and
`tools/recover_phase1_wave.py`; Phase 2 recovery modules validate specific checkpoints and are
strict internal APIs, not a universal resume command. Preserve evaluator defects and identify
the corrected revision separately; never feed diagnostic grading back to a learning agent.

## 3 ALE

Pinned to the 67-task Near-term cohort at `d10fb61a14f9719774c3520c5763068b28ef5546`; 64 CPU
tasks run through Linux/Windows QEMU guests. The three GPU baselines were run separately
(Chroma Key on the official ALE Windows image, GCP NVIDIA L4 vWS) and are included in the
67-task aggregate. Missing results are never scored as zero.

```bash
python3 scripts/setup_ale.py                       # two isolated envs; refuses revision/lock mismatch
run_ale.py prepare --os linux|windows [--cache D]  # base disks ≈167 GiB / ≈157 GiB
run_ale.py smoke   --os linux|windows --output results/smoke/...
run_ale.py plan    --arm both
run_ale.py run     --arm both --output results/ale/run_01 --concurrency 1 [--vm-limit N] [--tasks file]
run_ale.py report  --runs results/ale/run_01 --output results/ale/report_01
```

The default checkout is `../agents-last-exam` (`--ale-root` overrides). Smoke checks memory
transfer, capture/replay, Verifier isolation, scratch, rollback, and guest reset — no model or
grader calls; receipts bind to source and runner image. `tasks.csv` records baseline/RSI scores
and sources; `summary.json` reports coverage; a full mean requires all 67 official scores.
The reporter never selects the best score or substitutes a historical baseline.

## 4 Paper and results

*RSIAgent: Autonomous Exploration for Recursive Self-improvement in New Environments* — Sibo Zhu,
Shicheng Fan, Xinyue Wang, Wenyi Wu, Kun Zhou, Biwei Huang. [arXiv 2609.15364](https://arxiv.org/abs/2609.15364);
author-supplied [PDF mirror](RSIAgent.pdf) distributed byte-for-byte (September 15, 2026).

| Paper terminology | Runtime |
| --- | --- |
| Broad Recursive Self-exploration (BRS) | Phase 1: parallel experience acquisition, then ordered consolidation |
| Deep Recursive Self-exploration (DRS) | Phase 2: sequential attempts and practice selected by the Curriculum |
| Test-time memory reuse | Phase 3: frozen memory + sealed evaluation |

Framework figure: [assets/framework.png](assets/framework.png), a faithful PNG rendering of
`assets/ExRSI_framework.pdf` at method revision `6e36cb4…`; PDF SHA-256
`eb33267920acabbf1706247b4f91e501d3847ef4dae28ff954cc3ea9fce7f452`. Source PDF is not bundled.

| Benchmark | Partial w/o RSI | Partial with RSI | Full w/o RSI | Full with RSI |
| --- | ---: | ---: | ---: | ---: |
| OSWorld 2.0, 0808 offline | 71.97 | 78.98 | 37.80 | 42.68 |
| Agents' Last Exam, Near-term | 83.75 | 84.82 | 49.25 | 50.75 |

Scope: OSWorld 82 tasks (including T082 setup failure as zero; RSI row uses 41 non-diagnostic
scores, remaining 41 retain baselines); ALE all 67 (19 RSI entries, 48 baselines; 33/67 vs 34/67
full credit). Retained baselines are not new RSI evaluations; runs, budgets, and scopes are not
fully matched. These are manuscript-reported results, not a new audit or leaderboard entry.

## 5 Release provenance and validation

Base `e7f7130…`; runtime export `8a142a4…`; browser readiness fix `04421e5…`; infrastructure and
recovery integration source `e790a01…`; ALE integration `a92f5be…`; ALE benchmark `d10fb61…`.
`source-manifest.json` describes the original export and is historical, not a current inventory.

Maintained: model profiles, reasoning settings, Verifier isolation, memory commit protocol,
Phase 1 wave ordering, Phase 2 `curriculum_review`. ALE adds a longer checkpoint timeout and
lets verified Phase 1 branches release idle guests before ordered commits (contexts and captured
candidates are replayed). OSWorld keeps its default timeout and wave behavior. Public interface
has no personnel assignments or shard launchers; new runs use `RSIAGENT_*`. The OSWorld release
remains August 8, 2026 (its VM artifact's June tag is upstream identity, not a second runtime).

Validation (September 14, 2026): 718 portable tests plus two optional evaluator tests; full
OSWorld dry run 108 tasks / 432 commands; all seven model profiles retain effective settings.
Real VM smoke passed OSWorld HTTP and virtio (10 checks each) and ALE Linux (16 checks); ALE
Windows and GPU were not tested on real guests in this release. Portable suite:
`python tools/check_rsi_release.py`; evaluator tests are opt-in with
`RSI_TEST_OSWORLD_INTEGRATION=1`. Smoke success establishes mechanics, not a benchmark score.

## 6 Runtime fixes, attribution, contributing

- Per-thread model reasoning; concurrent calls cannot attach another branch's reasoning.
- HTTP 200 with an embedded provider error follows that status's retry policy; empty-response
  retries preserve request options. `RSIAGENT_JSON_ACTION_RETRY=1` optionally requests JSON
  output after an unparseable reply; the parser still decides whether an action exists.
- Guest signal termination and staging failures remain transport evidence.
- Verifier replay preserves inspection authority; private scratch export handles unreadable
  files in a confined reader while model programs keep desktop UID, dropped capabilities, and an
  isolated scratch namespace.
- Phase 1 records branch failures immediately and drains siblings before cleanup; terminal
  verdicts, learning commits, and boundary violations are never retried.
- `--resume-completed-boundary` validates completed waves, manifests, protocol fields, and the
  absence of later phases before archiving; quarantined lineages are always rejected.
- Docker provider: two concurrent cold boots per host UID; port cache per allocation; 300 s
  timeouts; `RSIAGENT_VM_OWNER` labels containers; a unique launch token bounds cleanup; a
  readiness timeout may retry once before task setup.
- `RSIAGENT_DNSMASQ_START_RETRY=1` retries only the transient inotify startup error. Ubuntu
  guests get a runtime-only `OOMPolicy=continue` drop-in; RAM limits and OOM scores unchanged.
- `RSIAGENT_TRUSTED_VERIFIER_TRANSPORT=virtio` provisions a host-only, loopback, root-only
  Verifier channel before desktop sudo is disabled.

License: Apache-2.0. OSWorld-V2 is separately licensed Apache-2.0; benchmark tasks, gated
assets, guest images, and websites are obtained separately and not bundled. ALE is installed
separately at the revision in `config/ale/protocol.lock.json`; guest OSes, applications, images,
and datasets are not redistributed. Python dependencies come from `requirements.txt`; model
accounts and credentials are user-supplied.

Contributing: open an issue or a focused pull request with before/after behavior and validation.
Use Python 3.12, install `requirements-dev.txt`, run `python tools/check_rsi_release.py` (fake
guests/model responses; no paid calls). Preserve Actor/Verifier/Curriculum/memory/evaluator
separation and add a regression test for boundary or recovery changes. Role-profile or
benchmark-lock changes need explicit provenance and a new lineage. Never commit credentials,
private trajectories, memory snapshots, VM images, benchmark assets, or result directories.
