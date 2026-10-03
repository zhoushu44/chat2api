// spawn 补丁：在 DSH 沙箱（PowerShell ConstrainedLanguage）下运行时，esbuild/vite
// 通过 child_process.spawn(..., {stdio:'pipe'}) 启动服务进程会被 EPERM 拒绝
//（命名管道限制；'inherit' / 'ignore' 模式可用）。本文件把 spawn 的 stdio
// 强制改为 'inherit'。仅在沙箱构建（scripts/build-sandbox.mjs）时通过
// node --import 使用，正常构建链路不加载。
//
// 用法：node --import ./scripts/patch-spawn.cjs scripts/build-sandbox.mjs
const cp = require('node:child_process')
const originalSpawn = cp.spawn
function patchedSpawn(cmd, args, opts) {
  const next = Object.assign({}, opts)
  if (next.stdio === 'pipe' || Array.isArray(next.stdio)) {
    next.stdio = 'inherit'
  }
  return originalSpawn(cmd, args, next)
}
// CJS require cache 里的 spawn 是可写的；ESM namespace 只读，
// 但 vite/esbuild 内部走 require('child_process')，此补丁对其生效。
cp.spawn = patchedSpawn
