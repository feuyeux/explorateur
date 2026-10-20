// packaging.ts — 交付打包（packaging.py 的 TS 移植；yazl/yauzl 承载）
//
// macOS 自带 Info-ZIP 对非 ASCII 文件名**不置 UTF-8 flag（bit 0x800）**，
// 解包到别的机器上中文/阿拉伯语文件名全变乱码。Python 的 zipfile 默认置位、
// yazl 实测也置位（对纯 ASCII 条目也置位，比 Python 更保守且无害——本行的
// 结论由 test/packaging.test.ts 的 UTF-8 flag 断言机检，Python 时代的探针记录
// 已随金样本退役），所以打包一律走库、不走命令行 zip。
import yazl from 'yazl'
import yauzl from 'yauzl'
import { createWriteStream, readdirSync, statSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'

export const UTF8_FLAG = 0x800

/** src_dir 下全部文件的相对 POSIX 路径（按路径排序——与 Python sorted(rglob) 同序）。 */
function walkSorted(srcDir: string, rel = ''): string[] {
  const out: string[] = []
  const entries = readdirSync(join(srcDir, rel)).sort()
  for (const name of entries) {
    const relPath = rel ? `${rel}/${name}` : name
    const st = statSync(join(srcDir, relPath))
    if (st.isDirectory()) out.push(...walkSorted(srcDir, relPath))
    else if (st.isFile()) out.push(relPath)
  }
  return out
}

/**
 * 把 src_dir 打成 zip（相对路径保留；UTF-8 flag 由 yazl 置位）。
 * include(rel)：以 src_dir 为根的相对 POSIX 路径过滤（跳过 build 产物/临时件用）。
 */
export async function zipTree(
  srcDir: string,
  outZip: string,
  include: (rel: string) => boolean = () => true,
): Promise<string> {
  mkdirSync(dirname(outZip), { recursive: true })
  const zf = new yazl.ZipFile()
  for (const rel of walkSorted(srcDir)) {
    if (!include(rel)) continue
    // zip 内路径一律 POSIX 分隔符（walkSorted 产出的 rel 本就是 '/' 分隔）
    zf.addFile(join(srcDir, ...rel.split('/')), rel)
  }
  await new Promise<void>((res, rej) => {
    // 收尾信号取写流的 close（fd 收尾），不是 yazl 读流的 end：读流 end 时
    // 管道未必写完，高负载下读流会超前写流——在读流上收尾会让 zipTree
    // 提前返回，后续立刻开包会读到截断 zip（实测与 Edge/ffmpeg 并行时
    // 全量套件 4 轮挂 2 轮；这不是测试 flake，交付包会真损坏）。
    const ws = createWriteStream(outZip)
    ws.on('error', rej)
    ws.on('close', res)
    zf.outputStream.on('error', rej)
    zf.outputStream.pipe(ws)
    zf.end()
  })
  return outZip
}

/** zip 条目表：相对路径 → (未压缩大小, 是否置 UTF-8 flag)（结构 parity 判据用）。 */
export async function listEntries(outZip: string): Promise<Record<string, { uncompressedSize: number; utf8Flag: boolean }>> {
  return await new Promise((resolve_, reject_) => {
    yauzl.open(outZip, { lazyEntries: true }, (err, zip) => {
      if (err || !zip) return reject_(err ?? new Error('cannot open zip'))
      const out: Record<string, { uncompressedSize: number; utf8Flag: boolean }> = {}
      zip.on('entry', (e: { fileName: string; uncompressedSize: number; generalPurposeBitFlag?: number }) => {
        out[e.fileName] = {
          uncompressedSize: e.uncompressedSize,
          utf8Flag: ((e.generalPurposeBitFlag ?? 0) & UTF8_FLAG) !== 0,
        }
        zip.readEntry()
      })
      zip.on('end', () => resolve_(out))
      zip.on('error', reject_)
      zip.readEntry()
    })
  })
}

/** 验证某个条目带了 UTF-8 flag（反向验证用：这是判据不是摆设）。 */
export async function hasUtf8Flag(outZip: string, name: string): Promise<boolean> {
  const entries = await listEntries(outZip)
  const e = entries[name]
  if (!e) throw new Error(`zip 里没有条目 ${name}`)
  return e.utf8Flag
}

/** 条目原内容逐字节读出（parity 判据：内容不许被打包层碰）。 */
export function readEntry(outZip: string, name: string): Promise<Buffer> {
  return new Promise((resolve_, reject_) => {
    yauzl.open(outZip, { lazyEntries: true }, (err, zip) => {
      if (err || !zip) return reject_(err ?? new Error('cannot open zip'))
      zip.on('error', reject_)
      zip.on('entry', (e: { fileName: string }) => {
        if (e.fileName === name) {
          zip.openReadStream(e as never, (err2, rs) => {
            if (err2 || !rs) return reject_(err2 ?? new Error('no stream'))
            const chunks: Buffer[] = []
            rs.on('data', (c: Buffer) => chunks.push(c))
            rs.on('end', () => resolve_(Buffer.concat(chunks)))
            rs.on('error', reject_)
          })
        } else {
          zip.readEntry()
        }
      })
      zip.on('end', () => reject_(new Error(`zip 里没有条目 ${name}`)))
      zip.readEntry()
    })
  })
}
