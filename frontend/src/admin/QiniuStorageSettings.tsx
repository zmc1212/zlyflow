import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Input, Select, Switch, message } from "antd"
import { CheckCircle2, CloudCog, KeyRound, ShieldCheck } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { jsonMutation, requestJson } from "../api"

type QiniuConfig = {
  enabled: boolean; bucket: string; region: string; domain: string; object_prefix: string
  has_access_key: boolean; has_secret_key: boolean; credential_ready: boolean; available: boolean
  last_test_status?: string | null; last_test_message?: string | null; last_test_at?: string | null
}

const regionOptions = [
  { value: "z0", label: "华东" }, { value: "cn-east-2", label: "华东-浙江" },
  { value: "z1", label: "华北" }, { value: "z2", label: "华南" },
  { value: "na0", label: "北美" }, { value: "as0", label: "新加坡" },
]

export default function QiniuStorageSettings({ csrfToken }: { csrfToken: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["qiniu-provider"],
    queryFn: () => requestJson<QiniuConfig>("/api/admin/providers/qiniu"),
    refetchOnWindowFocus: false,
  })
  const [enabled, setEnabled] = useState(false)
  const [accessKey, setAccessKey] = useState("")
  const [secretKey, setSecretKey] = useState("")
  const [bucket, setBucket] = useState("")
  const [region, setRegion] = useState("z0")
  const [domain, setDomain] = useState("")
  const [objectPrefix, setObjectPrefix] = useState("zly-ai-video-studio/")
  const formLoaded = useRef(false)

  const applyConfig = (config: QiniuConfig) => {
    formLoaded.current = true
    setEnabled(config.enabled)
    setBucket(config.bucket)
    setRegion(config.region)
    setDomain(config.domain)
    setObjectPrefix(config.object_prefix)
    queryClient.setQueryData(["qiniu-provider"], config)
  }

  useEffect(() => {
    if (!query.data || formLoaded.current) return
    applyConfig(query.data)
  }, [query.data])

  const payload = () => ({
    enabled, access_key: accessKey || null, secret_key: secretKey || null, bucket, region, domain, object_prefix: objectPrefix,
  })
  const save = useMutation({
    mutationFn: () => requestJson<QiniuConfig>("/api/admin/providers/qiniu", jsonMutation(csrfToken, payload(), "PUT")),
    onSuccess: (config) => {
      setAccessKey("")
      setSecretKey("")
      applyConfig(config)
      message.success("七牛云存储配置已保存")
    },
  })
  const test = useMutation({
    mutationFn: () => requestJson<QiniuConfig>("/api/admin/providers/qiniu/test", jsonMutation(csrfToken, payload())),
    onSuccess: (config) => {
      queryClient.setQueryData<QiniuConfig>(["qiniu-provider"], (current) => current ? {
        ...current,
        last_test_status: config.last_test_status,
        last_test_message: config.last_test_message,
        last_test_at: config.last_test_at,
      } : config)
      message.success("七牛云连接测试成功")
    },
  })
  const error = query.error ?? save.error ?? test.error

  return (
    <main className="mx-auto max-w-[1020px] px-5 py-6 lg:px-8">
      <div className="flex items-start gap-4 border-b border-black/[0.06] pb-5">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-cyan-500/10 text-cyan-600">
          <CloudCog size={22} />
        </span>
        <div>
          <h2 className="text-base font-semibold text-[#111827]">七牛云媒体存储</h2>
          <p className="mt-1 text-xs leading-5 text-[#4b5563]">
            启用后，生成的图片和视频会先上传到七牛云，工作台以签名链接交付。
          </p>
        </div>
      </div>

      {!query.data?.credential_ready ? (
        <Alert
          className="mt-5"
          type="warning"
          showIcon
          message="凭证主密钥不可用"
          description="请先配置 ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY；七牛云 AK/SK 会使用该密钥加密保存。"
        />
      ) : null}

      <section className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm space-y-5">
          <div className="flex items-center justify-between gap-4 border-b border-black/[0.06] pb-4">
            <div>
              <p className="text-sm font-medium text-[#111827]">启用七牛云</p>
              <p className="mt-0.5 text-xs text-[#6b7280]">关闭后，新生成媒体继续使用当前本地交付方式；已存云端的作品不会删除。</p>
            </div>
            <Switch checked={enabled} onChange={setEnabled} />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">Access Key</label>
              <Input.Password
                className="mt-1.5"
                value={accessKey}
                onChange={(event) => setAccessKey(event.target.value)}
                prefix={<KeyRound size={15} className="text-[#9ca3af]" />}
                placeholder={query.data?.has_access_key ? "已保存，留空不修改" : "输入 Access Key"}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">Secret Key</label>
              <Input.Password
                className="mt-1.5"
                value={secretKey}
                onChange={(event) => setSecretKey(event.target.value)}
                prefix={<KeyRound size={15} className="text-[#9ca3af]" />}
                placeholder={query.data?.has_secret_key ? "已保存，留空不修改" : "输入 Secret Key"}
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">Bucket</label>
              <Input
                className="mt-1.5"
                value={bucket}
                onChange={(event) => setBucket(event.target.value)}
                placeholder="your-bucket"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">存储区域</label>
              <Select
                className="mt-1.5 w-full"
                value={region}
                onChange={setRegion}
                options={regionOptions}
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-[#4b5563]">访问域名</label>
            <Input
              className="mt-1.5"
              value={domain}
              onChange={(event) => setDomain(event.target.value)}
              placeholder="https://media.example.com"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-[#4b5563]">对象前缀</label>
            <Input
              className="mt-1.5"
              value={objectPrefix}
              onChange={(event) => setObjectPrefix(event.target.value)}
              placeholder="zly-ai-video-studio/"
            />
          </div>

          {error ? <Alert type="error" showIcon message={error.message} /> : null}

          <div className="flex flex-wrap gap-3 pt-2">
            <Button type="primary" loading={save.isPending} onClick={() => save.mutate()}>
              保存配置
            </Button>
            <Button loading={test.isPending} onClick={() => test.mutate()} icon={<CheckCircle2 size={15} />}>
              测试连接
            </Button>
          </div>
        </div>

        <aside className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm flex flex-col justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-[#6b7280]">当前状态</p>
            <p className={`mt-3 text-sm font-semibold ${query.data?.available ? "text-emerald-600" : "text-amber-600"}`}>
              {query.data?.available ? "● 新媒体将上传到七牛云" : "● 仍使用本地交付"}
            </p>

            <dl className="mt-6 space-y-4 text-xs">
              <div>
                <dt className="text-[#6b7280]">配置密钥</dt>
                <dd className="mt-1 font-medium text-[#111827]">
                  {query.data?.has_access_key && query.data?.has_secret_key ? "已保存" : "尚未完整配置"}
                </dd>
              </div>
              <div>
                <dt className="text-[#6b7280]">最近测试</dt>
                <dd className="mt-1 font-medium break-words text-[#111827]">
                  {query.data?.last_test_status
                    ? `${query.data.last_test_status} · ${query.data.last_test_at ? new Date(query.data.last_test_at).toLocaleString("zh-CN", { hour12: false }) : ""}`
                    : "尚未测试"}
                </dd>
              </div>
              {query.data?.last_test_message ? (
                <div>
                  <dt className="text-[#6b7280]">测试结果</dt>
                  <dd className="mt-1 break-words text-[11px] text-[#6b7280]">{query.data.last_test_message}</dd>
                </div>
              ) : null}
            </dl>
          </div>

          <div className="mt-6 flex gap-2 rounded-xl bg-[#f9fafb] border border-black/[0.06] p-3 text-xs leading-5 text-[#6b7280]">
            <ShieldCheck size={16} className="mt-0.5 shrink-0 text-[#7047f6]" />
            <span>AK/SK 不会回显，保存时留空即可保留已配置的密钥。</span>
          </div>
        </aside>
      </section>
    </main>
  )
}
