import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Input, Select, Switch, Tag, message } from "antd"
import { Bot, CheckCircle2, ExternalLink, KeyRound, Sparkles } from "lucide-react"
import { useEffect, useState } from "react"
import { jsonMutation, requestJson } from "../api"

type LlmConfig = {
  enabled: boolean
  base_url: string
  model: string
  api_key_masked?: string | null
  has_api_key: boolean
  credential_ready: boolean
  available: boolean
  unavailable_reason?: string | null
  last_test_status?: string | null
  last_test_message?: string | null
  last_test_at?: string | null
}

const PROVIDER_PRESETS = [
  {
    label: "ModelScope 魔搭社区 (免费额度)",
    value: "modelscope",
    baseUrl: "https://api-inference.modelscope.cn/v1",
    model: "deepseek-ai/DeepSeek-V4-Flash-0731",
    docUrl: "https://modelscope.cn/my/access/token",
    recommendedModels: [
      { name: "DeepSeek-V4-Flash (推荐)", id: "deepseek-ai/DeepSeek-V4-Flash-0731" },
      { name: "DeepSeek-V4-Pro", id: "deepseek-ai/DeepSeek-V4-Pro" },
      { name: "MiniMax-M1-80k", id: "MiniMax/MiniMax-M1-80k" },
      { name: "MiniMax-M3", id: "MiniMax/MiniMax-M3" },
      { name: "LongCat-Flash-Lite", id: "meituan-longcat/LongCat-Flash-Lite" },
    ],
  },

  {
    label: "阿里云百炼 / 通义千问 (免费百/千万Token)",
    value: "dashscope",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen-plus",
    docUrl: "https://bailian.console.aliyun.com/?apiKey=1",
    recommendedModels: [
      { name: "qwen-plus (推荐)", id: "qwen-plus" },
      { name: "qwen-turbo (极速)", id: "qwen-turbo" },
      { name: "qwen-max (高智能)", id: "qwen-max" },
      { name: "deepseek-v3", id: "deepseek-v3" },
      { name: "deepseek-r1", id: "deepseek-r1" },
    ],
  },
  {
    label: "SiliconFlow 硅基流动 (送2000万Token/7B永久免费)",
    value: "siliconflow",
    baseUrl: "https://api.siliconflow.cn/v1",
    model: "Qwen/Qwen2.5-7B-Instruct",
    docUrl: "https://cloud.siliconflow.cn/account/ak",
    recommendedModels: [
      { name: "Qwen2.5-7B (永久免费)", id: "Qwen/Qwen2.5-7B-Instruct" },
      { name: "DeepSeek-V3", id: "deepseek-ai/DeepSeek-V3" },
      { name: "DeepSeek-R1", id: "deepseek-ai/DeepSeek-R1" },
    ],
  },
  {
    label: "DeepSeek 官方平台",
    value: "deepseek",
    baseUrl: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    docUrl: "https://platform.deepseek.com/api_keys",
    recommendedModels: [
      { name: "deepseek-chat (V3)", id: "deepseek-chat" },
      { name: "deepseek-reasoner (R1)", id: "deepseek-reasoner" },
    ],
  },

  {
    label: "自定义 OpenAI 兼容接口",
    value: "custom",
    baseUrl: "",
    model: "",
    docUrl: "",
    recommendedModels: [],
  },
]

export default function LlmProviderSettings({ csrfToken }: { csrfToken: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["llm-provider"],
    queryFn: () => requestJson<LlmConfig>("/api/admin/providers/llm"),
  })

  const [enabled, setEnabled] = useState(false)
  const [baseUrl, setBaseUrl] = useState("https://api-inference.modelscope.cn/v1")
  const [model, setModel] = useState("Qwen/Qwen2.5-7B-Instruct")
  const [apiKey, setApiKey] = useState("")
  const [selectedPreset, setSelectedPreset] = useState("modelscope")

  useEffect(() => {
    if (!query.data) return
    setEnabled(query.data.enabled)
    setBaseUrl(query.data.base_url)
    setModel(query.data.model)

    const matched = PROVIDER_PRESETS.find(
      (p) => p.baseUrl && query.data.base_url.startsWith(p.baseUrl.replace(/\/v1$/, "")),
    )
    if (matched) {
      setSelectedPreset(matched.value)
    } else {
      setSelectedPreset("custom")
    }
  }, [query.data])

  const handlePresetChange = (presetValue: string) => {
    setSelectedPreset(presetValue)
    const found = PROVIDER_PRESETS.find((p) => p.value === presetValue)
    if (found && found.value !== "custom") {
      setBaseUrl(found.baseUrl)
      setModel(found.model)
    }
  }

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["llm-provider"] })

  const save = useMutation({
    mutationFn: () =>
      requestJson<LlmConfig>(
        "/api/admin/providers/llm",
        jsonMutation(csrfToken, {
          enabled,
          base_url: baseUrl,
          model,
          api_key: apiKey || null,
        }, "PUT"),
      ),
    onSuccess: () => {
      setApiKey("")
      refresh()
      message.success("LLM 大模型配置已保存")
    },
  })

  const test = useMutation({
    mutationFn: () =>
      requestJson<LlmConfig>(
        "/api/admin/providers/llm/test",
        jsonMutation(csrfToken, {
          base_url: baseUrl,
          model,
          api_key: apiKey || null,
        }),
      ),
    onSuccess: () => {
      refresh()
      message.success("大模型连接测试成功")
    },
  })

  const error = save.error ?? test.error ?? query.error
  const currentPreset = PROVIDER_PRESETS.find((p) => p.value === selectedPreset)

  return (
    <main className="mx-auto max-w-[1020px] px-5 py-6 lg:px-8">
      <div className="flex items-start gap-4 border-b border-black/[0.06] pb-5">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-[#7047f6]/10 text-[#7047f6]">
          <Bot size={22} />
        </span>
        <div>
          <h2 className="text-base font-semibold text-[#111827]">LLM 大模型服务</h2>
          <p className="mt-1 text-xs leading-5 text-[#4b5563]">
            通用 OpenAI 兼容协议，支持 ModelScope 魔搭社区免费额度模型、DeepSeek、SiliconFlow 等，用于创作提示词一键润色与优化。
          </p>
        </div>
      </div>

      {!query.data?.credential_ready ? (
        <Alert
          className="mt-5"
          type="warning"
          showIcon
          message="凭证主密钥不可用"
          description="请在部署环境设置 ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY。LLM 凭据将无法加密保存。"
        />
      ) : null}

      <section className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm space-y-5">
          <div className="flex items-center justify-between gap-4 border-b border-black/[0.06] pb-4">
            <div>
              <p className="text-sm font-medium text-[#111827]">启用大模型功能</p>
              <p className="mt-0.5 text-xs text-[#6b7280]">开启后创作工作台可使用 AI 提示词一键优化功能。</p>
            </div>
            <Switch checked={enabled} onChange={setEnabled} />
          </div>

          <div>
            <label className="block text-xs font-medium text-[#4b5563]">快速服务预设</label>
            <Select
              className="mt-1.5 w-full"
              value={selectedPreset}
              onChange={handlePresetChange}
              options={PROVIDER_PRESETS.map((p) => ({ value: p.value, label: p.label }))}
            />
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label className="block text-xs font-medium text-[#4b5563]">Base URL (接口地址)</label>
              {currentPreset?.docUrl && (
                <a
                  href={currentPreset.docUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-xs font-medium text-[#7047f6] hover:underline"
                >
                  <span>获取访问 Token</span>
                  <ExternalLink size={12} />
                </a>
              )}
            </div>
            <Input
              className="mt-1.5"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api-inference.modelscope.cn/v1"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-[#4b5563]">Model (模型名称)</label>
            <Input
              className="mt-1.5"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="例如 Qwen/Qwen2.5-7B-Instruct 或 deepseek-ai/DeepSeek-V3"
            />
            {currentPreset?.recommendedModels && currentPreset.recommendedModels.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] text-[#9ca3af]">推荐模型:</span>
                {currentPreset.recommendedModels.map((m) => (
                  <Tag
                    key={m.id}
                    className={`cursor-pointer transition ${model === m.id ? "border-[#7047f6] text-[#7047f6] font-medium" : "text-[#4b5563]"}`}
                    onClick={() => setModel(m.id)}
                  >
                    {m.name}
                  </Tag>
                ))}
              </div>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-[#4b5563]">API Key / Access Token</label>
            <Input.Password
              className="mt-1.5"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              prefix={<KeyRound size={15} className="text-[#9ca3af]" />}
              placeholder={query.data?.api_key_masked || "输入平台生成的 API Key / Token"}
            />
          </div>

          {error ? <Alert type="error" showIcon message={error.message} /> : null}

          <div className="flex flex-wrap gap-3 pt-2">
            <Button type="primary" loading={save.isPending} onClick={() => save.mutate()}>
              保存配置
            </Button>
            <Button
              loading={test.isPending}
              onClick={() => test.mutate()}
              icon={<CheckCircle2 size={15} />}
            >
              测试连接
            </Button>
          </div>
        </div>

        <aside className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm flex flex-col justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-[#6b7280]">服务状态</p>
            <p className={`mt-3 text-sm font-semibold ${query.data?.available ? "text-emerald-600" : "text-amber-600"}`}>
              {query.data?.available ? "● 大模型服务正常可用" : "● 大模型服务未就绪"}
            </p>
            {query.data?.unavailable_reason ? (
              <p className="mt-2 text-xs leading-5 text-[#6b7280]">{query.data.unavailable_reason}</p>
            ) : null}

            <dl className="mt-6 space-y-4 text-xs">
              <div>
                <dt className="text-[#6b7280]">当前模型</dt>
                <dd className="mt-1 font-mono font-medium text-[#111827] break-all">{query.data?.model || "未配置"}</dd>
              </div>
              <div>
                <dt className="text-[#6b7280]">最近连通性测试</dt>
                <dd className="mt-1 font-medium text-[#111827]">
                  {query.data?.last_test_status
                    ? `${query.data.last_test_status} · ${query.data.last_test_at ? new Date(query.data.last_test_at).toLocaleString("zh-CN", { hour12: false }) : ""}`
                    : "尚未测试"}
                </dd>
                {query.data?.last_test_message && (
                  <dd className="mt-1 break-all text-[11px] text-[#6b7280]">{query.data.last_test_message}</dd>
                )}
              </div>
            </dl>
          </div>

          <div className="mt-6 rounded-xl border border-[#7047f6]/20 bg-[#7047f6]/[0.04] p-4 text-xs leading-5 text-[#4b5563]">
            <span className="flex items-center gap-1.5 font-semibold text-[#7047f6]">
              <Sparkles size={14} /> 魔搭社区免费额度说明
            </span>
            <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
              ModelScope Serverless API 为注册用户提供主流开源模型（如 Qwen2.5-7B/14B/32B、DeepSeek-V3 等）的每日免费调用额度。
            </p>
          </div>
        </aside>
      </section>
    </main>
  )
}
