import { VERSION } from '@feuille/core'

export function main(): number {
  process.stdout.write(`feuille ${VERSION} (TS monorepo；门禁 = pnpm verify)\n`)
  return 0
}
