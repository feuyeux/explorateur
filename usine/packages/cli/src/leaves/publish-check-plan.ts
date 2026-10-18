// publish check-plan 叶子：薄适配层——业务全在 @feuille/publish/check_plan。
import { check_plan } from '@feuille/publish'

export function main(argv: string[]): Promise<number> {
  return check_plan.main(argv)
}
