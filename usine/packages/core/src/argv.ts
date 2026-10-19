/** argparse 同款取值：`--k v` 与 `--k=v` 都收；重复旗标取首个。 */
export function argValue(argv: string[], flag: string): string | undefined {
  const i = argv.indexOf(flag)
  if (i >= 0) return argv[i + 1]
  const p = `${flag}=`
  const j = argv.findIndex((a) => a.startsWith(p))
  return j >= 0 ? argv[j]!.slice(p.length) : undefined
}
