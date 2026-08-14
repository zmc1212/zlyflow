import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import { readFileSync } from "node:fs"

export default defineConfig(() => {
  const certificatePath = process.env.ZLY_AI_VIDEO_STUDIO_SSL_CERTFILE
  const keyPath = process.env.ZLY_AI_VIDEO_STUDIO_SSL_KEYFILE
  const useHttps = Boolean(certificatePath && keyPath)

  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
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
        },
      },
    },
  }
})
