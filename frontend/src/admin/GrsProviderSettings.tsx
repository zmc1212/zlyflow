import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Input, Switch } from "antd"
import { CheckCircle2, Cloud, KeyRound, WalletCards } from "lucide-react"
import { useEffect, useState } from "react"
import { jsonMutation, requestJson } from "../api"

type ProviderConfig = {
  enabled: boolean; base_url: string; api_key_masked?: string | null; has_api_key: boolean
  credential_ready: boolean; gpt_image_2_enabled: boolean; gpt_image_2_vip_enabled: boolean
  last_test_status?: string | null; last_test_message?: string | null; last_test_at?: string | null
  last_balance?: number | null; last_balance_at?: string | null; available: boolean; unavailable_reason?: string | null
}

export default function GrsProviderSettings({ csrfToken }: { csrfToken: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ["grs-provider"], queryFn: () => requestJson<ProviderConfig>("/api/admin/providers/grs") })
  const [enabled, setEnabled] = useState(false)
  const [baseUrl, setBaseUrl] = useState("https://grsai.dakka.com.cn")
  const [apiKey, setApiKey] = useState("")
  const [standardEnabled, setStandardEnabled] = useState(true)
  const [vipEnabled, setVipEnabled] = useState(true)

  useEffect(() => {
    if (!query.data) return
    setEnabled(query.data.enabled)
    setBaseUrl(query.data.base_url)
    setStandardEnabled(query.data.gpt_image_2_enabled)
    setVipEnabled(query.data.gpt_image_2_vip_enabled)
  }, [query.data])

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["grs-provider"] })
  const save = useMutation({
    mutationFn: () => requestJson<ProviderConfig>("/api/admin/providers/grs", jsonMutation(csrfToken, {
      enabled, base_url: baseUrl, api_key: apiKey || null,
      gpt_image_2_enabled: standardEnabled, gpt_image_2_vip_enabled: vipEnabled,
    }, "PUT")),
    onSuccess: () => { setApiKey(""); refresh() },
  })
  const test = useMutation({
    mutationFn: () => requestJson<ProviderConfig>("/api/admin/providers/grs/test", jsonMutation(csrfToken, {
      base_url: baseUrl,
      api_key: apiKey || null,
    })),
    onSuccess: refresh,
  })
  const balance = useMutation({
    mutationFn: () => requestJson<{ credits: number }>("/api/admin/providers/grs/balance", { method: "POST", headers: { "X-CSRF-Token": csrfToken } }),
    onSuccess: refresh,
  })
  const error = save.error ?? test.error ?? balance.error ?? query.error

  return <main className="mx-auto max-w-[920px] px-5 py-8 lg:px-8">
    <div className="flex items-start gap-4 border-b border-white/[0.08] pb-6"><span className="grid size-11 shrink-0 place-items-center rounded-xl bg-[#7047f6]/15 text-[#a996ff]"><Cloud size={21} /></span><div><h2 className="text-lg font-semibold">GRS 图片供应商</h2><p className="mt-1 text-sm leading-6 text-[#92929c]">单一主配置，为 GPT Image 2 与 VIP 提供生成、轮询和余额查询。</p></div></div>
    {!query.data?.credential_ready ? <Alert className="mt-6" type="warning" showIcon message="凭证主密钥不可用" description="请在部署环境设置 ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY。视频功能不受影响，图片提交会保持锁定。" /> : null}
    <section className="mt-7 grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="space-y-5">
        <div className="flex items-center justify-between gap-4 border-b border-white/[0.07] pb-4"><div><p className="text-sm font-medium">启用 GRS 生图</p><p className="mt-1 text-xs text-[#85858f]">关闭后仍保留图片入口和历史，只锁定提交。</p></div><Switch checked={enabled} onChange={setEnabled} /></div>
        <label className="block text-sm text-[#cfcfd6]">Base URL<Input className="mt-2" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://grsai.dakka.com.cn" /></label>
        <label className="block text-sm text-[#cfcfd6]">API Key<Input.Password className="mt-2" value={apiKey} onChange={(event) => setApiKey(event.target.value)} prefix={<KeyRound size={15} />} placeholder={query.data?.api_key_masked || "输入新的 API Key"} /></label>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex items-center justify-between rounded-lg border border-white/[0.08] bg-white/[0.025] p-3"><div><p className="text-sm">GPT Image 2</p><p className="mt-1 text-xs text-[#85858f]">1K · 0–10 张参考图</p></div><Switch checked={standardEnabled} onChange={setStandardEnabled} /></div>
          <div className="flex items-center justify-between rounded-lg border border-white/[0.08] bg-white/[0.025] p-3"><div><p className="text-sm">GPT Image 2 VIP</p><p className="mt-1 text-xs text-[#85858f]">1K/2K/4K/自定义</p></div><Switch checked={vipEnabled} onChange={setVipEnabled} /></div>
        </div>
        {error ? <Alert type="error" showIcon message={error.message} /> : null}
        <div className="flex flex-wrap gap-3"><Button type="primary" loading={save.isPending} onClick={() => save.mutate()}>保存配置</Button><Button loading={test.isPending} onClick={() => test.mutate()} icon={<CheckCircle2 size={15} />}>测试连接</Button><Button loading={balance.isPending} onClick={() => balance.mutate()} icon={<WalletCards size={15} />}>查询余额</Button></div>
      </div>
      <aside className="border-l border-white/[0.08] pl-6">
        <p className="text-xs font-medium uppercase tracking-[0.12em] text-[#777781]">当前状态</p>
        <p className={`mt-4 text-sm ${query.data?.available ? "text-emerald-300" : "text-amber-200"}`}>{query.data?.available ? "可以提交图片任务" : "图片提交已锁定"}</p>
        {query.data?.unavailable_reason ? <p className="mt-2 text-xs leading-5 text-[#9b9ba5]">{query.data.unavailable_reason}</p> : null}
        <dl className="mt-6 space-y-4 text-xs"><div><dt className="text-[#777781]">最近测试</dt><dd className="mt-1 text-[#c9c9d1]">{query.data?.last_test_status ? `${query.data.last_test_status} · ${query.data.last_test_at ? new Date(query.data.last_test_at).toLocaleString("zh-CN", { hour12: false }) : ""}` : "尚未测试"}</dd></div><div><dt className="text-[#777781]">上游余额</dt><dd className="mt-1 text-[#c9c9d1]">{query.data?.last_balance ?? "尚未查询"}</dd></div></dl>
      </aside>
    </section>
  </main>
}
