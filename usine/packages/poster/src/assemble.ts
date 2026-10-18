// assemble.ts — 把 fonts.css（及共享主题/排版基础样式）注入模板的 /*__FONTS__*/ 标记。
// （promoted from skills/one-page-poster/scripts/assemble.py，P5-7e 归流）
//
// Usage: assemble [src.html] [out.html]
// 缺省 poster_src.html -> ../index.html（相对 cwd）。模板可用别的
// `/*__FONTS__*/` 风格注释覆盖标记；标记须在 <style> 块内。
import { existsSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { basename, dirname, join, resolve } from 'node:path'

export function main(argv: string[]): number {
  const here = process.cwd()
  const src = resolve(here, argv[0] !== undefined ? argv[0]! : 'poster_src.html')
  const out = resolve(here, argv[1] !== undefined ? argv[1]! : '../index.html')
  const marker = '/*__FONTS__*/'

  // 支持 fonts.css 与共享基础样式表的定位
  const fontsFile = join(dirname(src), 'fonts.css')
  const fontsCss = existsSync(fontsFile) ? readFileSync(fontsFile, 'utf-8') : ''

  let body = readFileSync(src, 'utf-8')

  // 多主题与共享排版支持
  const skillsRoot = ['scripts', 'assets'].includes(basename(here)) ? dirname(here) : here
  const themeFile = join(skillsRoot, 'theme-tokens.css')
  const typoFile = join(skillsRoot, 'typography-base.css')

  // 可选主题参数：--theme <name>
  let themeName: string | undefined
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--theme' && i + 1 < argv.length) {
      themeName = argv[i + 1]!
      break
    }
  }

  if (themeName !== undefined) {
    // 在 <body> / <html> 上注入 data-theme（原文件没有时）
    if (!body.includes('data-theme="')) {
      body = body.replace('<body', `<body data-theme="${themeName}"`) // 首处替换（Python replace(..., 1)）
    }
  }

  const injected: string[] = []
  if (existsSync(themeFile)) injected.push(`/* Extracted Theme Tokens */\n${readFileSync(themeFile, 'utf-8')}`)
  if (existsSync(typoFile)) injected.push(`/* Extracted Typography & Component Base */\n${readFileSync(typoFile, 'utf-8')}`)
  if (fontsCss) injected.push(fontsCss)

  const replacement = injected.length > 0 ? injected.join('\n\n') : '/* No extra CSS injected */'

  // Python str.replace 换所有出现处——split/join 镜像（marker 无 → 原样写回）
  writeFileSync(out, body.includes(marker) ? body.split(marker).join(replacement) : body, 'utf-8')

  console.log(
    `wrote ${out} (${Math.floor(statSync(out).size / 1024)} KB)`
      + (themeName !== undefined ? ` [theme: ${themeName}]` : ''),
  )
  return 0
}
