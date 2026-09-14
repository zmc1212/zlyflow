// 构建前清空 dist。不能用 Node 的 fs.rmSync：本机环境（Node v24 + 安全软件过滤驱动）
// 下 rmSync 会静默失败——返回成功但文件仍在，导致 Vite emptyOutDir 形同虚设、
// dist/assets 里历史构建持续堆积。Windows 走 cmd rd（已验证可用），其它平台走 rm -rf。
import { execSync } from "node:child_process"
import { existsSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const distDir = join(dirname(fileURLToPath(import.meta.url)), "..", "dist")
if (!existsSync(distDir)) process.exit(0)

if (process.platform === "win32") {
  execSync(`rd /s /q "${distDir}"`, { stdio: "ignore" })
} else {
  execSync(`rm -rf "${distDir}"`, { stdio: "ignore" })
}

if (existsSync(distDir)) {
  console.error(`[clean-dist] 清理失败，目录仍存在：${distDir}`)
  process.exit(1)
}
console.log(`[clean-dist] 已清理 ${distDir}`)
