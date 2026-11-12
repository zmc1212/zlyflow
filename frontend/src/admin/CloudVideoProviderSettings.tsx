import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Input, Switch, message } from "antd"
import { CheckCircle2, Clapperboard } from "lucide-react"
import { useEffect, useState } from "react"
import { jsonMutation, requestJson } from "../api"

type CloudVideoProviderConfig = {
  provider_key: string
  label: string
  requires_secret: boolean
  api_key_label: string
  api_secret_label: string
  base_url_hint: string
  default_base_url: string
  enabled: boolean
  base_url: string
  effective_base_url: string
  has_api_key: boolean
  api_key_masked: string
  has_api_secret: boolean
  credential_ready: boolean
  available: boolean
  unavailable_reason?: string | null
  last_test_status?: string | null
  last_test_message?: string | null
  last_test_at?: string | null
}

/** 「AI 供应商」页的云端视频模型卡片：可灵 / 即梦 Seedance（火山方舟）/ 海螺 Hailuo 直连官方 API。 */
export default function CloudVideoProviderSettings({ csrfToken }: { csrfToken: string }) {
  const query = useQuery({
    queryKey: ["cloud-video-providers"],
    queryFn: () => requestJson<CloudVideoProviderConfig[]>("/api/admin/providers/cloud-video"),
  })

  return (
    <main className="studio-admin-panel max-w-[1180px] px-5 py-6 lg:px-8">
      <div className="flex items-start gap-4 border-b border-black/[0.06] pb-5">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-[#0e9384]/10 text-[#0e9384]">
          <Clapperboard size={22} />
        </span>
        <div>
          <h2 className="text-base font-semibold text-[#111827]">云端视频模型</h2>
          <p className="mt-1 text-xs leading-5 text-[#4b5563]">
            直连厂商官方 API 的云端视频生成（可灵 / 即梦 Seedance / 海螺），按次计费，不走本地显卡。
            启用后对应工作流出现在创作页「云端视频模型」分组；未启用或密钥缺失时下拉置灰并提示原因。
          </p>
        </div>
      </div>

      {query.data?.some((item) => !item.credential_ready) ? (
        <Alert
          className="mt-5"
          type="warning"
          showIcon
          message="凭证主密钥不可用"
          description="请在部署环境设置 ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY。云端视频密钥将无法加密保存。"
        />
      ) : null}

      <div className="mt-6 space-y-6">
        {(query.data ?? []).map((config) => (
          <CloudVideoProviderCard key={config.provider_key} csrfToken={csrfToken} config={config} />
        ))}
        {query.isLoading ? <p className="text-xs text-[#6b7280]">加载中…</p> : null}
      </div>
    </main>
  )
}

function CloudVideoProviderCard({ csrfToken, config }: { csrfToken: string; config: CloudVideoProviderConfig }) {
  const queryClient = useQueryClient()
  const [enabled, setEnabled] = useState(config.enabled)
  const [baseUrl, setBaseUrl] = useState(config.base_url)
  const [apiKey, setApiKey] = useState("")
  const [apiSecret, setApiSecret] = useState("")

  useEffect(() => {
    setEnabled(config.enabled)
    setBaseUrl(config.base_url)
  }, [config])

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["cloud-video-providers"] })
  const save = useMutation({
    mutationFn: () =>
      requestJson<CloudVideoProviderConfig>(
        `/api/admin/providers/cloud-video/${config.provider_key}`,
        jsonMutation(
          csrfToken,
          {
            enabled,
            base_url: baseUrl,
            api_key: apiKey || null,
            api_secret: config.requires_secret ? apiSecret || null : null,
          },
          "PUT",
        ),
      ),
    onSuccess: () => {
      setApiKey("")
      setApiSecret("")
      refresh()
      message.success(`「${config.label}」配置已保存`)
    },
  })
  const test = useMutation({
    mutationFn: () =>
      requestJson<CloudVideoProviderConfig>(
        `/api/admin/providers/cloud-video/${config.provider_key}/test`,
        jsonMutation(csrfToken, {
          base_url: baseUrl || null,
          api_key: apiKey || null,
          api_secret: config.requires_secret ? apiSecret || null : null,
        }),
      ),
    onSuccess: (data) => {
      refresh()
      if (data.available) message.success(`「${config.label}」连接成功`)
      else message.warning(`连接失败：${data.unavailable_reason || "未知原因"}`)
    },
  })
  const error = save.error ?? test.error
  const statusClass =
    config.last_test_status === "success" ? "text-emerald-600" : config.last_test_status === "failed" ? "text-red-600" : "text-[#111827]"

  return (
    <section className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[#111827]">{config.label}</h3>
          <p className="mt-0.5 text-[11px] text-[#6b7280]">
            默认地址 <code className="rounded bg-[#f3f4f6] px-1">{config.default_base_url}</code>
            {config.base_url_hint ? `；${config.base_url_hint}` : ""}
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs font-medium text-[#4b5563]">
          <Switch checked={enabled} onChange={setEnabled} aria-label={`启用 ${config.label}`} />
          {enabled ? "已启用" : "已停用"}
        </label>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-[#4b5563]">服务地址（留空使用官方默认）</label>
            <Input
              className="mt-1.5"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder={config.default_base_url}
              allowClear
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#4b5563]">{config.api_key_label}</label>
            <Input.Password
              className="mt-1.5"
              autoComplete="new-password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={config.has_api_key ? `已保存（${config.api_key_masked}），留空表示不修改` : `输入${config.api_key_label}`}
            />
          </div>
          {config.requires_secret ? (
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">{config.api_secret_label}</label>
              <Input.Password
                className="mt-1.5"
                autoComplete="new-password"
                value={apiSecret}
                onChange={(event) => setApiSecret(event.target.value)}
                placeholder={config.has_api_secret ? "已保存，留空表示不修改" : `输入${config.api_secret_label}`}
              />
            </div>
          ) : null}
          {error ? <Alert type="error" showIcon message={error.message} /> : null}
          <div className="studio-admin-actions">
            <Button type="primary" loading={save.isPending} onClick={() => save.mutate()}>保存配置</Button>
            <Button loading={test.isPending} onClick={() => test.mutate()} icon={<CheckCircle2 size={15} />}>测试连接</Button>
          </div>
        </div>

        <aside className="rounded-xl border border-black/[0.06] bg-[#f9fafb] p-4">
          <p className="text-xs font-semibold text-[#6b7280]">状态</p>
          <dl className="mt-3 space-y-3 text-xs">
            <div>
              <dt className="text-[#6b7280]">可用性</dt>
              <dd className={`mt-0.5 font-semibold ${config.available ? "text-emerald-600" : "text-amber-600"}`}>
                {config.available ? "● 可用" : "● 不可用"}
              </dd>
              {config.available ? null : (
                <dd className="mt-0.5 text-[11px] leading-4 text-[#6b7280]">{config.unavailable_reason || "—"}</dd>
              )}
            </div>
            <div>
              <dt className="text-[#6b7280]">生效地址</dt>
              <dd className="mt-0.5 break-all font-medium text-[#111827]">{config.effective_base_url}</dd>
            </div>
            <div>
              <dt className="text-[#6b7280]">最近连通性测试</dt>
              <dd className={`mt-0.5 font-medium ${statusClass}`}>
                {config.last_test_status
                  ? `${config.last_test_status === "success" ? "成功" : "失败"} · ${config.last_test_at ? new Date(config.last_test_at).toLocaleString("zh-CN", { hour12: false }) : ""}`
                  : "尚未测试"}
              </dd>
              {config.last_test_message ? (
                <dd className="mt-0.5 break-all text-[11px] text-[#6b7280]">{config.last_test_message}</dd>
              ) : null}
            </div>
          </dl>
        </aside>
      </div>
    </section>
  )
}
