// Vite 构建包装（DSH 沙箱专用）：
// 正常环境请继续用 `npm run build`（vite build + sync-web-dist，完全一致）。
// 本脚本仅在沙箱下使用：配合 scripts/patch-spawn.cjs（node --import）把
// esbuild 服务进程的 spawn(stdio:'pipe') 改为 'inherit' 以绕开 EPERM。
//
// 用法：node --import ./scripts/patch-spawn.cjs scripts/build-sandbox.mjs
import { pathToFileURL } from 'node:url'
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(__dirname, '..')

const vitePath = path.resolve(root, 'node_modules/vite/dist/node/index.js')
const vite = await import(pathToFileURL(vitePath).href)

// 等价 npm run build：clean → vite build → sync
fs.rmSync(path.resolve(root, 'dist'), { recursive: true, force: true })
await vite.build({ root, logLevel: 'info' })

const sourceDir = path.resolve(root, 'dist')
const targetDir = path.resolve(root, '../internal/api/web_dist')
fs.rmSync(targetDir, { recursive: true, force: true })
fs.mkdirSync(targetDir, { recursive: true })
fs.cpSync(sourceDir, targetDir, { recursive: true })
const count = fs.readdirSync(path.join(targetDir, 'assets')).length
console.log(`[build-sandbox] 已同步 ${count} 个 assets 到 ${path.relative(root, targetDir)}`)
