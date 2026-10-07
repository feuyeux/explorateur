#!/usr/bin/env node
/**
 * 打包前清理 (Pre-bundle Cleanup)
 *
 * 背景：macOS 的 DMG 打包依赖 create-dmg 的 bundle_dmg.sh。它会在
 * src-tauri/target/release/bundle/macos/ 下创建一个临时的可读写镜像
 * (rw.<pid>.<name>.dmg)，挂载后把 .app 拷贝进去，最后再卸载并转换。
 *
 * 如果这一步失败（最常见原因是镜像被占用、无法卸载），临时镜像会被**遗留在
 * 源目录里**。而下一次打包会把整个 macos/ 目录当作源目录，于是这个 8MB 左右的
 * 残留镜像又被算进内容，导致 create-dmg 在挂载后的临时卷上再次报
 * "No space left on device" —— 形成**自我延续的失败循环**，一次失败后
 * 后续每一次构建都会失败。
 *
 * 本脚本在打包前把该状态归零：
 *   1. 卸载遗留的 /Volumes/dmg.* 临时卷
 *   2. 结束从这些临时卷中运行的进程（否则卷无法卸载）
 *   3. 删除遗留在源目录中的 rw.*.dmg 临时镜像
 *
 * 幂等：状态干净时不做任何事。
 */
import { execFileSync } from 'child_process';
import { existsSync, readdirSync, unlinkSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const BUNDLE_MACOS = path.join(ROOT, 'src-tauri', 'target', 'release', 'bundle', 'macos');

const sh = (cmd, args, { allowFail = true } = {}) => {
  try {
    return execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  } catch (e) {
    if (!allowFail) throw e;
    return '';
  }
};

let cleaned = 0;

// --- 1. 找出遗留的 create-dmg 临时卷 ---
let volumes = [];
try {
  const info = sh('hdiutil', ['info']);
  volumes = [...new Set((info.match(/\/Volumes\/dmg\.[A-Za-z0-9]+/g) || []))];
} catch { /* hdiutil 不可用则跳过 */ }

// --- 2. 结束运行在临时卷中的应用（卷被占用就无法卸载）---
if (volumes.length) {
  try {
    const pids = sh('pgrep', ['-f', `/Volumes/dmg\\.`]).trim();
    if (pids) {
      for (const pid of pids.split(/\s+/).filter(Boolean)) {
        sh('kill', [pid]);
        cleaned++;
      }
      // 给进程一点时间退出，否则 detach 仍会失败
      sh('sleep', ['1']);
    }
  } catch { /* 忽略 */ }

  // --- 3. 卸载遗留卷 ---
  for (const v of volumes) {
    sh('hdiutil', ['detach', v, '-force']);
    cleaned++;
  }
}

// --- 4. 删除源目录中残留的临时镜像 ---
if (existsSync(BUNDLE_MACOS)) {
  for (const name of readdirSync(BUNDLE_MACOS)) {
    if (/^rw\..*\.dmg$/.test(name)) {
      try {
        unlinkSync(path.join(BUNDLE_MACOS, name));
        cleaned++;
      } catch { /* 忽略 */ }
    }
  }
}

console.log(cleaned > 0
  ? `[cleanup] 清理打包残留状态 (${cleaned} 项)`
  : '[cleanup] 打包状态干净，无需清理');
