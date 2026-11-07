import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Input, message } from "antd"
import { CheckCircle2, KeyRound, Music } from "lucide-react"
import { useEffect, useState } from "react"
import { jsonMutation, requestJson } from "../api"

type MusicConfig = {
  base_url: string
  has_access_key: boolean
  credential_ready: boolean
  configured: boolean
  last_test_status?: string | null
  last_test_message?: string | null
  last_test_at?: string | null
}

type MusicTestResult = MusicConfig & { available: boolean; unavailable_reason?: string | null }

/** 「AI 供应商」页的音乐生成（远端 YuE2 Studio）卡片：地址 + 访问密钥 + 测试连接。 */
export default function MusicProviderSettings({ csrfToken }: { csrfToken: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["music-provider"],
    queryFn: () => requestJson<MusicConfig>("/api/admin/providers/music"),
  })
  const [baseUrl, setBaseUrl] = useState("")
  const [accessKey, setAccessKey] = useState("")

  useEffect(() => {
    if (!query.data) return
    setBaseUrl(query.data.base_url)
  }, [query.data])

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["music-provider"] })
  const save = useMutation({
    mutationFn: () => requestJson<MusicConfig>("/api/admin/providers/music", jsonMutation(csrfToken, { base_url: baseUrl, access_key: accessKey || null }, "PUT")),
    onSuccess: () => {
      setAccessKey("")
      refresh()
      message.success("音乐生成配置已保存")
    },
  })
  const test = useMutation({
    mutationFn: () => requestJson<MusicTestResult>("/api/admin/providers/music/test", jsonMutation(csrfToken, { base_url: baseUrl || null, access_key: accessKey || null })),
    onSuccess: (data) => {
      refresh()
      if (data.available) message.success("连接成功")
      else message.warning(`连接失败：${data.unavailable_reason || "未知原因"}`)
    },
  })
  const error = save.error ?? test.error ?? query.error

  return (
    <main className="mx-auto max-w-[1020px] px-5 py-6 lg:px-8">
      <div className="flex items-start gap-4 border-b border-black/[0.06] pb-5">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-[#7047f6]/10 text-[#7047f6]">
          <Music size={22} />
        </span>
        <div>
          <h2 className="text-base font-semibold text-[#111827]">音乐生成（YuE2 Studio）</h2>
          <p className="mt-1 text-xs leading-5 text-[#4b5563]">
            远端电脑上的本地音乐生成服务。「音乐」菜单的生成任务经由该地址提交，成品自动转存七牛云。测试连接只探测 <code>/health</code>，不会启动生成。
          </p>
        </div>
      </div>

      {!query.data?.credential_ready ? (
        <Alert
          className="mt-5"
          type="warning"
          showIcon
          message="凭证主密钥不可用"
          description="请在部署环境设置 ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY。访问密钥将无法加密保存。"
        />
      ) : null}

      <section className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm space-y-5">
          <div>
            <label className="block text-xs font-medium text-[#4b5563]">YuE2 Studio 服务地址</label>
            <Input
              className="mt-1.5"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="http://192.168.10.54:8791"
            />
            <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
              远端机默认 <code>http://192.168.10.54:8791</code>；走公网 frp 时填对应地址（如 <code>http://124.70.90.30:18080</code>）。
            </p>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#4b5563]">访问密钥</label>
            <Input.Password
              className="mt-1.5"
              autoComplete="new-password"
              value={accessKey}
              onChange={(event) => setAccessKey(event.target.value)}
              prefix={<KeyRound size={15} className="text-[#9ca3af]" />}
              placeholder={query.data?.has_access_key ? "已保存，留空表示不修改" : "YuE2 Studio 设置中开启局域网访问后生成的 Access Key"}
            />
          </div>
          {error ? <Alert type="error" showIcon message={error.message} /> : null}
          <div className="flex flex-wrap gap-3 pt-2">
            <Button type="primary" loading={save.isPending} onClick={() => save.mutate()}>保存配置</Button>
            <Button loading={test.isPending} onClick={() => test.mutate()} icon={<CheckCircle2 size={15} />}>测试连接</Button>
          </div>
        </div>

        <aside className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm flex flex-col justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-[#6b7280]">服务状态</p>
            <p className={`mt-3 text-sm font-semibold ${query.data?.configured ? "text-emerald-600" : "text-amber-600"}`}>
              {query.data?.configured ? "● 已配置" : "● 未配置完整"}
            </p>
            <dl className="mt-6 space-y-4 text-xs">
              <div>
                <dt className="text-[#6b7280]">服务地址</dt>
                <dd className="mt-1 font-medium text-[#111827] break-all">{query.data?.base_url || "未配置"}</dd>
              </div>
              <div>
                <dt className="text-[#6b7280]">访问密钥</dt>
                <dd className="mt-1 font-medium text-[#111827]">{query.data?.has_access_key ? "已保存（不回显）" : "未保存"}</dd>
              </div>
              <div>
                <dt className="text-[#6b7280]">最近连通性测试</dt>
                <dd className="mt-1 font-medium text-[#111827]">
                  {query.data?.last_test_status
                    ? `${query.data.last_test_status} · ${query.data.last_test_at ? new Date(query.data.last_test_at).toLocaleString("zh-CN", { hour12: false }) : ""}`
                    : "尚未测试"}
                </dd>
                {query.data?.last_test_message ? (
                  <dd className="mt-1 break-all text-[11px] text-[#6b7280]">{query.data.last_test_message}</dd>
                ) : null}
              </div>
            </dl>
          </div>
          <div className="mt-6 rounded-xl border border-[#7047f6]/20 bg-[#7047f6]/[0.04] p-4 text-xs leading-5 text-[#4b5563]">
            <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
              密钥在远端 YuE2 Studio 界面「设置 → 网络访问」开启局域网访问后生成。生成由引擎排队串行执行，一首 3-4 分钟的歌通常几分钟内完成。
            </p>
          </div>
        </aside>
      </section>
    </main>
  )
}
