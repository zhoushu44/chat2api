import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// 将 Vite 构建产物同步到 Go embed 目录(backend 静态资源唯一来源)。
// 目的：消除“改了前端但后端二进制仍是旧页面”的手工拷贝步骤。
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const sourceDir = path.resolve(__dirname, '../dist')
const targetDir = path.resolve(__dirname, '../../internal/api/web_dist')

if (!fs.existsSync(sourceDir)) {
  console.error(`[sync-web-dist] 构建产物不存在: ${sourceDir}，请先执行 vite build`)
  process.exit(1)
}

// 清空目标目录后整体覆盖，确保不残留旧 hash 的 chunk
fs.rmSync(targetDir, { recursive: true, force: true })
fs.mkdirSync(targetDir, { recursive: true })
fs.cpSync(sourceDir, targetDir, { recursive: true })

const count = fs.readdirSync(path.join(targetDir, 'assets')).length
console.log(`[sync-web-dist] 已同步 ${count} 个 assets 到 ${path.relative(process.cwd(), targetDir)}`)
