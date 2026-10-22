# Machine substrate — measured on this host, 2026-10-21

## Paths (the biggest trap of the run)
* Guest is Windows git-bash. Python programs run as `python3 -u` and see the project at
  `/home/user/evolution_project`.
* **Use the literal `/home/user`, never `~`.** [measured] `os.environ['HOME']` is `/home/user`,
  but `os.path.expanduser('~')` once returned `'R:\home\user'` (a drive-mapped alias). A runtime
  artifact written through that alias did not appear under `/home/user` (`open()` then raised
  FileNotFoundError for the literal path). Later in the same session the alias happened to
  resolve to the same tree — i.e. it is *unstable*, so never build a deliverable path from it.
  Bash: use `$HOME`. Python: hard-code `/home/user/...`.
* Mixing languages for scratch bit me: I wrote build output with a bash `/tmp/...` path and the
  following python program could not find it. Keep one language for a scratch round-trip.

## Toolchain
* [measured] `node --import tsx` fails with `ERR_MODULE_NOT_FOUND: tsx` before install.
* [measured] `pnpm install` ≈ 7 s (store warm, 622 packages). Node v26, pnpm 11.8.
* [measured] `pnpm verify` = `pnpm -s typecheck && pnpm -s test`, ≈ 36 s, 577 tests.
* [measured] `git` is NOT available in the project tree (`fatal: not a git repository`), so
  "diff against HEAD" is not an option; snapshot originals to a scratch path first.

## The one red test in `pnpm verify` is the host's, not yours
[measured] `packages/gate/test/layout.test.ts` > 仓库根没有第三处放内容的地方 asserts that the
PARENT of the project root contains only `usine, garage, garage-ii, theatre-ii, théâtre, config,
  docs`. Here the parent is `/home/user` = `$HOME`, holding `AppData`, `bin`, `work`,
  `evolution_project` (all with the image's own 22:45 mtimes). There is no env override.
  Failure message seen: `仓库根多了 ["AppData","bin","evolution_project","work"]`.
[verifier] The Verifier attributed this to the substrate independently and returned PASS with the
  test red, so this is settled: do not burn budget on it, and do not re-run `pnpm verify` hoping
  for green.
Still keep `$HOME` clean: my scratch dirs `~/fnbuild`, `~/headbuild`, `~/fnbuild2` enlarged that
stray list and made the message noisier. Delete your scratch before the handoff.
