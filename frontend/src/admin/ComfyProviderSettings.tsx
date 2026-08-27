import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Input, Select, message } from "antd"
import { CheckCircle2, MonitorPlay } from "lucide-react"
import { useEffect, useState } from "react"
import { jsonMutation, requestJson } from "../api"

type ComfyConfig = {
  base_url: string
  env_default: string
  last_test_status?: string | null
  last_test_message?: string | null
  last_test_at?: string | null
}

const URL_PRESETS = [
  { label: "本机默认 8188", value: "http://127.0.0.1:8188" },
  { label: "服务器 FRP 18188", value: "http://127.0.0.1:18188" },
]

export default function ComfyProviderSettings({ csrfToken }: { csrfToken: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["comfy-provider"],
    queryFn: () => requestJson<ComfyConfig>("/api/admin/providers/comfy"),
  })
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:8188")

  useEffect(() => {
    if (!query.data) return
    setBaseUrl(query.data.base_url)
  }, [query.data])

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["comfy-provider"] })
  const save = useMutation({
    mutationFn: () => requestJson<ComfyConfig>("/api/admin/providers/comfy", jsonMutation(csrfToken, { base_url: baseUrl }, "PUT")),
    onSuccess: (config) => {
      setBaseUrl(config.base_url)
      refresh()
      message.success("ComfyUI 连接地址已保存，后续视频任务立即使用新地址")
    },
  })
  const test = useMutation({
    mutationFn: () => requestJson<ComfyConfig>("/api/admin/providers/comfy/test", jsonMutation(csrfToken, { base_url: baseUrl })),
    onSuccess: () => {
      refresh()
      message.success("ComfyUI 连接测试成功")
    },
  })
  const error = save.error ?? test.error ?? query.error
  const lastStatus = query.data?.last_test_status
  const statusClass = lastStatus === "success" ? "text-emerald-600" : lastStatus === "failed" ? "text-red-600" : "text-[#111827]"

  return (
    <main className="mx-auto max-w-[1020px] px-5 pt-6 lg:px-8">
      <section className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm">
        <div className="flex items-start gap-4 border-b border-black/[0.06] pb-5">
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-[#7047f6]/10 text-[#7047f6]">
            <MonitorPlay size={22} />
          </span>
          <div>
            <h2 className="text-base font-semibold text-[#111827]">ComfyUI 视频后端</h2>
            <p className="mt-1 text-xs leading-5 text-[#4b5563]">
              工作台只连接一个 ComfyUI 实例。保存后立即对后续视频任务生效，无需重启。宿主机浏览器直连交付仍使用本机
              {" "}
              <code className="rounded bg-[#f3f4f6] px-1 text-[#111827]">http://127.0.0.1:8188/view</code>
              ，与此处后端地址无关。
            </p>
          </div>
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_260px]">
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">常用地址</label>
              <Select
                className="mt-1.5 w-full"
                value={URL_PRESETS.some((item) => item.value === baseUrl) ? baseUrl : "custom"}
                options={[...URL_PRESETS, { label: "自定义", value: "custom" }]}
                onChange={(value) => {
                  if (value !== "custom") setBaseUrl(value)
                }}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">连接地址</label>
              <Input
                className="mt-1.5"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="http://127.0.0.1:8188"
              />
              {query.data?.env_default ? (
                <p className="mt-1.5 text-xs text-[#6b7280]">
                  环境变量默认值：
                  {query.data.env_default}
                </p>
              ) : null}
            </div>

            {error ? <Alert type="error" showIcon message={error.message} /> : null}

            <div className="flex flex-wrap gap-3 pt-1">
              <Button type="primary" loading={save.isPending} onClick={() => save.mutate()}>
                保存配置
              </Button>
              <Button loading={test.isPending} onClick={() => test.mutate()} icon={<CheckCircle2 size={15} />}>
                测试连接
              </Button>
            </div>
          </div>

          <aside className="rounded-xl border border-black/[0.06] bg-[#f9fafb] p-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-[#6b7280]">最近测试</p>
            <p className={`mt-3 text-sm font-semibold ${statusClass}`}>
              {lastStatus === "success" ? "● 已连通" : lastStatus === "failed" ? "● 连接失败" : "● 尚未测试"}
            </p>
            {query.data?.last_test_message ? (
              <p className="mt-2 text-xs leading-5 text-[#4b5563]">{query.data.last_test_message}</p>
            ) : null}
            <p className="mt-3 text-xs text-[#6b7280]">
              {query.data?.last_test_at
                ? new Date(query.data.last_test_at).toLocaleString("zh-CN", { hour12: false })
                : "保存或测试后会记录结果"}
            </p>
          </aside>
        </div>
      </section>
    </main>
  )
}
