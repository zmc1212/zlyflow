import { defineConfig, loadEnv } from "vite"
import react from "@vitejs/plugin-react"
import { readFileSync, existsSync } from "node:fs"

export default defineConfig(({ mode }) => {
  const env = {
    ...loadEnv(mode, process.cwd(), ""),
    ...loadEnv("dev", process.cwd(), ""),
    ...process.env,
  }

  const certificatePath = env.ZLY_AI_VIDEO_STUDIO_SSL_CERTFILE
  const keyPath = env.ZLY_AI_VIDEO_STUDIO_SSL_KEYFILE
  const useHttps = Boolean(certificatePath && keyPath && existsSync(certificatePath) && existsSync(keyPath))
  const port = Number(env.VITE_PORT || 5173)

  return {
    plugins: [react()],
    server: {
      host: env.HOST || "0.0.0.0",
      port,
      strictPort: true,
      allowedHosts: true,
      https: useHttps
        ? {
            cert: readFileSync(certificatePath!),
            key: readFileSync(keyPath!),
          }
        : undefined,
      proxy: {
        "/api": {
          target: `${useHttps ? "https" : "http"}://127.0.0.1:7865`,
          changeOrigin: true,
          secure: false,
          // 导入剧本会逐集规划镜头，单集大模型最长约 240 秒；120 秒会先掐掉前端、后端仍在跑。
          timeout: 900000,
          proxyTimeout: 900000,
        },
      },
    },
  }
})
