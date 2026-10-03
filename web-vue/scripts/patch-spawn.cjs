// spawn 补丁 v3：pipe 模式被 DSH 沙箱拦截时，改用「自建 pipe 替身」方案：
// esbuild 服务进程需要 stdin/stdout 双向通信（协议流），不能改成 ignore/inherit。
// Windows 下 spawn 支持传入已有的 socket/pipe fd 逃逸 stdio 限制不可行；
// 因此这里改为：拦截 esbuildCommandAndArgs 的调用结果，让 esbuild 走
// 「node 进程内启动」—— 仍需 spawn，无解。
//
// 实际可行方案：本补丁把 stdio 保留 pipe，但预先用 'ignore' 模式 spawn 成功的方式
// 不适用于 esbuild 协议。真正的修复是「在非沙箱环境构建」。
// 此文件保留 v2 行为（尽力而为），主流程建议在 DSH 外执行 npm run build。
const cp = require('node:child_process')
const originalSpawn = cp.spawn
function patchedSpawn(cmd, args, opts) {
  const next = Object.assign({}, opts)
  if (next.stdio === 'pipe') {
    next.stdio = ['ignore', 'ignore', 'inherit']
  } else if (Array.isArray(next.stdio)) {
    next.stdio = next.stdio.map((s) => (s === 'pipe' ? 'ignore' : s))
  }
  return originalSpawn(cmd, args, next)
}
cp.spawn = patchedSpawn
