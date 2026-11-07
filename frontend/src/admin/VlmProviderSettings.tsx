import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, AutoComplete, Button, Input, Select, Switch, Tag, message } from "antd"
import { CheckCircle2, ExternalLink, Eye, KeyRound, RefreshCw, Sparkles } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { jsonMutation, requestJson } from "../api"
import { CopyFieldButton } from "./FieldCopy"
import { buildModelOptions, modelPriceLabel, modelPriceTagStyle, providerPresetFor, resolveModelFree, sameProviderEndpoint } from "./provider-models"
import type { CatalogModel, CatalogResponse, ProviderPresetsResponse } from "./provider-models"

type VlmConfig = {
  enabled: boolean
  use_llm_credentials?: boolean
  llm_base_url?: string | null
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
  supports_vision?: boolean
}

const PROVIDER_PRESETS = [
  {
    label: "阿里云百炼 / 通义千问 VL",
    value: "dashscope",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen3-vl-flash",
    docUrl: "https://bailian.console.aliyun.com/?apiKey=1",
    recommendedModels: [
      { name: "qwen3-vl-flash（新人额度）", id: "qwen3-vl-flash" },
      { name: "qwen-vl-plus", id: "qwen-vl-plus" },
      { name: "qwen3-vl-plus", id: "qwen3-vl-plus" },
    ],
  },
  {
    label: "ModelScope 魔搭社区（扣魔粒）",
    value: "modelscope",
    baseUrl: "https://api-inference.modelscope.cn/v1",
    model: "Qwen/Qwen2.5-VL-7B-Instruct",
    docUrl: "https://modelscope.cn/my/access/token",
    recommendedModels: [
      { name: "Qwen2.5-VL-7B-Instruct", id: "Qwen/Qwen2.5-VL-7B-Instruct" },
      { name: "Qwen3-VL-8B-Instruct", id: "Qwen/Qwen3-VL-8B-Instruct" },
    ],
  },
  {
    label: "SiliconFlow 硅基流动（VL 按量付费）",
    value: "siliconflow",
    baseUrl: "https://api.siliconflow.cn/v1",
    model: "Qwen/Qwen3-VL-8B-Instruct",
    docUrl: "https://cloud.siliconflow.cn/account/ak",
    recommendedModels: [
      { name: "Qwen3-VL-8B-Instruct（按量）", id: "Qwen/Qwen3-VL-8B-Instruct" },
      { name: "Qwen2.5-VL-7B-Instruct", id: "Qwen/Qwen2.5-VL-7B-Instruct" },
    ],
  },
  {
    label: "Ollama 本地视觉模型",
    value: "ollama",
    baseUrl: "http://127.0.0.1:11434/v1",
    model: "qwen2.5-vl",
    docUrl: "https://ollama.com/library/qwen2.5vl",
    recommendedModels: [
      { name: "qwen2.5-vl", id: "qwen2.5-vl" },
      { name: "llava", id: "llava" },
      { name: "minicpm-v", id: "minicpm-v" },
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

export default function VlmProviderSettings({ csrfToken }: { csrfToken: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["vlm-provider"],
    queryFn: () => requestJson<VlmConfig>("/api/admin/providers/vlm"),
  })
  const presetsQuery = useQuery({
    queryKey: ["model-provider-presets"],
    queryFn: () => requestJson<ProviderPresetsResponse>("/api/admin/providers/model-presets"),
  })
  const officialPresets = presetsQuery.data?.presets
  const providerPresets = useMemo(() => [
    ...(officialPresets ?? []).map(preset => providerPresetFor(preset, "vision")),
    ...PROVIDER_PRESETS,
  ], [officialPresets])

  const [enabled, setEnabled] = useState(false)
  const [useLlm, setUseLlm] = useState(false)
  const [baseUrl, setBaseUrl] = useState("https://open.bigmodel.cn/api/paas/v4")
  const [model, setModel] = useState("glm-4.6v-flash")
  const [apiKey, setApiKey] = useState("")
  const [selectedPreset, setSelectedPreset] = useState("zhipu")
  const [catalogModels, setCatalogModels] = useState<CatalogModel[]>([])
  const [catalogBaseUrl, setCatalogBaseUrl] = useState("")
  const autoFetchedFor = useRef("")
  const hydratedConnection = useRef("")

  useEffect(() => {
    if (!query.data) return
    const connection = JSON.stringify([query.data.enabled, query.data.use_llm_credentials, query.data.base_url, query.data.model, query.data.has_api_key])
    if (connection === hydratedConnection.current) return
    hydratedConnection.current = connection
    setEnabled(query.data.enabled)
    setUseLlm(Boolean(query.data.use_llm_credentials))
    setBaseUrl(query.data.base_url)
    setModel(query.data.model)
  }, [query.data])

  useEffect(() => {
    setSelectedPreset(providerPresets.find(preset => sameProviderEndpoint(preset.baseUrl, baseUrl))?.value ?? "custom")
  }, [baseUrl, providerPresets])

  const handlePresetChange = (value: string) => {
    setSelectedPreset(value)
    setApiKey("")
    const preset = providerPresets.find((item) => item.value === value)
    if (preset && value !== "custom") {
      setBaseUrl(preset.baseUrl)
      setModel(preset.model)
    }
    setCatalogModels([])
    autoFetchedFor.current = ""
  }

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["vlm-provider"] })

  const save = useMutation({
    mutationFn: () =>
      requestJson<VlmConfig>(
        "/api/admin/providers/vlm",
        jsonMutation(
          csrfToken,
          {
            enabled,
            use_llm_credentials: useLlm,
            base_url: baseUrl,
            model,
            api_key: apiKey.trim() || null,
          },
          "PUT",
        ),
      ),
    onSuccess: () => {
      setApiKey("")
      refresh()
      message.success("视觉模型配置已保存")
    },
  })

  const test = useMutation({
    mutationFn: () =>
      requestJson<VlmConfig>(
        "/api/admin/providers/vlm/test",
        jsonMutation(csrfToken, {
          base_url: baseUrl,
          model,
          api_key: apiKey.trim() || null,
          use_llm_credentials: useLlm,
        }),
      ),
    onSuccess: () => {
      refresh()
      message.success("视觉模型连接测试成功")
    },
  })

  const catalog = useMutation({
    mutationFn: async () => {
      const requestedBaseUrl = useLlm ? query.data?.llm_base_url ?? baseUrl : baseUrl
      const response = await requestJson<CatalogResponse>(
        "/api/admin/providers/vlm/models",
        jsonMutation(csrfToken, {
          base_url: baseUrl,
          api_key: apiKey.trim() || null,
          free_only: false,
          use_llm_credentials: useLlm,
        }),
      )
      return { ...response, requestedBaseUrl }
    },
    onSuccess: (data) => {
      setCatalogModels(data.models)
      setCatalogBaseUrl(data.requestedBaseUrl)
      if (data.models.length) {
        message.success(`已拉取 ${data.models.length} 个视觉模型`)
      } else {
        message.warning(data.message || "未找到可用视觉模型")
      }
    },
  })

  useEffect(() => {
    const canFetchLocal = selectedPreset === "ollama"
    const savedKeyMatches = query.data?.has_api_key && sameProviderEndpoint(baseUrl, query.data.base_url)
    const canFetchCloud = (selectedPreset === "siliconflow" || selectedPreset === "zhipu" || selectedPreset === "dashscope" || selectedPreset === "internai") && Boolean(savedKeyMatches)
    if (!canFetchLocal && !canFetchCloud) return
    const key = `${selectedPreset}|${baseUrl}|${query.data?.has_api_key ? "saved" : "none"}`
    if (autoFetchedFor.current === key) return
    autoFetchedFor.current = key
    catalog.mutate()
  }, [selectedPreset, baseUrl, query.data?.has_api_key])

  const currentPreset = providerPresets.find((p) => p.value === selectedPreset)
  const effectiveBaseUrl = useLlm ? query.data?.llm_base_url ?? baseUrl : baseUrl
  const activeCatalog = useMemo(() => sameProviderEndpoint(effectiveBaseUrl, catalogBaseUrl) ? catalogModels : [], [effectiveBaseUrl, catalogBaseUrl, catalogModels])
  const modelOptions = useMemo(() => {
    return buildModelOptions(effectiveBaseUrl, model, activeCatalog, currentPreset, officialPresets ?? [])
  }, [effectiveBaseUrl, model, activeCatalog, currentPreset, officialPresets])
  const selectedModelFree = resolveModelFree(effectiveBaseUrl, model, activeCatalog, officialPresets ?? [])
  const pricingPreset = officialPresets?.find(preset => sameProviderEndpoint(preset.base_url, effectiveBaseUrl))
  const savedKeyMatches = Boolean(!query.data?.use_llm_credentials && query.data?.has_api_key && sameProviderEndpoint(baseUrl, query.data.base_url))

  const error = save.error ?? test.error ?? catalog.error ?? query.error ?? presetsQuery.error

  return (
    <main className="mx-auto max-w-[1020px] px-5 py-6 lg:px-8">
      <div className="flex items-start gap-4 border-b border-black/[0.06] pb-5">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-[#7047f6]/10 text-[#7047f6]">
          <Eye size={22} />
        </span>
        <div>
          <h2 className="text-base font-semibold text-[#111827]">VLM 视觉模型</h2>
          <p className="mt-1 text-xs leading-5 text-[#4b5563]">
            只用于反推 / 拉片 / 主体分析（便宜看图）。工坊写稿与生成页润色若 LLM 名称可看图，会直接带图调用大模型页，不必把同一套 Key 再抄到这里。可选复用大模型凭据。
          </p>
        </div>
      </div>

      {!query.data?.credential_ready ? (
        <Alert
          className="mt-5"
          type="warning"
          showIcon
          message="凭证主密钥不可用"
          description="请在部署环境设置 ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY。视觉模型凭据将无法加密保存。"
        />
      ) : null}

      <section className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm space-y-5">
          <div className="flex items-center justify-between gap-4 border-b border-black/[0.06] pb-4">
            <div>
              <p className="text-sm font-medium text-[#111827]">启用视觉模型</p>
              <p className="mt-0.5 text-xs text-[#6b7280]">开启后资产库反推与复刻台拉片才能自动看图。</p>
            </div>
            <Switch checked={enabled} onChange={setEnabled} />
          </div>

          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-[#111827]">复用大模型凭据</p>
              <p className="mt-0.5 text-xs text-[#6b7280]">使用 LLM 大模型页的 Base URL 与 API Key，模型名称仍在本页选择视觉模型。</p>
            </div>
            <Switch checked={useLlm} onChange={setUseLlm} />
          </div>

          <div>
            <label className="block text-xs font-medium text-[#4b5563]">快速服务预设</label>
            <Select
              className="mt-1.5 w-full"
              aria-label="快速服务预设"
              disabled={useLlm}
              value={selectedPreset}
              onChange={handlePresetChange}
              options={providerPresets.map((p) => ({ value: p.value, label: p.label }))}
            />
          </div>

          {selectedPreset === "modelscope" ? (
            <Alert
              type="warning"
              showIcon
              message="魔搭会扣除账户魔粒"
              description="VL 模型同样按魔粒计费。不想扣费请改用智谱 glm-4.6v-flash，或本机 Ollama。"
            />
          ) : null}

          {selectedPreset === "siliconflow" ? (
            <Alert
              type="info"
              showIcon
              message="硅基流动通用视觉模型按量计费"
              description="广场上免费的 VL 多为 OCR。角色外貌反推请用 Qwen3-VL 等通用视觉模型，会按 Token 扣费。"
            />
          ) : null}

          {useLlm ? (
            <Alert
              type="info"
              showIcon
              message="Base URL 与 API Key 来自 LLM 大模型页"
              description={`当前生效地址：${effectiveBaseUrl || "未配置"}。请在下方继续选择名称含 VL/Vision 的视觉模型。`}
            />
          ) : (
            <>
          <div>
            <div className="flex items-center justify-between">
              <label className="block text-xs font-medium text-[#4b5563]">Base URL (接口地址)</label>
              {currentPreset?.docUrl ? (
                <a
                  href={currentPreset.docUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-xs font-medium text-[#7047f6] hover:underline"
                >
                  <span>{selectedPreset === "ollama" ? "查看模型文档" : "获取访问 Token"}</span>
                  <ExternalLink size={12} />
                </a>
              ) : null}
            </div>
            <Input
              className="mt-1.5"
              aria-label="接口地址"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://open.bigmodel.cn/api/paas/v4"
              suffix={<CopyFieldButton label="Base URL" value={baseUrl} csrfToken={csrfToken} />}
            />
          </div>
            </>
          )}

          <div>
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <label className="block text-xs font-medium text-[#4b5563]">Model (视觉模型名称)</label>
                <Tag style={modelPriceTagStyle(selectedModelFree)}>{modelPriceLabel(selectedModelFree)}</Tag>
              </div>
              <div className="flex items-center gap-1">
                <CopyFieldButton label="模型名称" value={model} csrfToken={csrfToken} />
                <Button
                  size="small"
                  loading={catalog.isPending}
                  onClick={() => catalog.mutate()}
                  icon={<RefreshCw size={13} />}
                >
                  拉取官方列表
                </Button>
              </div>
            </div>
            <AutoComplete
              className="mt-1.5 w-full"
              aria-label="模型名称"
              value={model}
              options={modelOptions}
              defaultActiveFirstOption={false}
              onChange={(value) => setModel(value)}
              placeholder="选择或输入 VL / Vision 模型名称"
              filterOption={(input, option) => {
                const queryText = (input || "").trim().toLowerCase()
                if (!queryText) return true
                const isExactOption = modelOptions.some((row) => row.value.toLowerCase() === queryText)
                if (isExactOption) return true
                const haystack = `${option?.value ?? ""} ${option?.label ?? ""}`.toLowerCase()
                return haystack.includes(queryText)
              }}
              listHeight={320}
            />
            {pricingPreset ? (
              <p className="mt-1.5 text-[11px] leading-4 text-[var(--studio-text-muted)]">
                费用标记依据<a href={pricingPreset.pricing_url} target="_blank" rel="noreferrer" className="text-[var(--studio-accent-text)] hover:underline">智谱官方价目表</a>（{pricingPreset.pricing_verified_at} 核对）；未知型号显示价格未知。账号可用性请测试连接。
              </p>
            ) : null}
            <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
              名称须含 VL / Vision / glm-4v 等标记，保存时会校验。也可直接输入模型 ID。
            </p>
          </div>

          {!useLlm ? (
          <div>
            <label className="block text-xs font-medium text-[#4b5563]">API Key / Access Token</label>
            <Input.Password
              className="mt-1.5"
              aria-label="API Key / Access Token"
              autoComplete="new-password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              prefix={<KeyRound size={15} className="text-[#9ca3af]" />}
              placeholder={
                selectedPreset === "ollama"
                  ? "本地服务可留空"
                  : (savedKeyMatches ? query.data?.api_key_masked : null) || "输入平台生成的 API Key / Token"
              }
              suffix={<CopyFieldButton label="API Key" value={apiKey} csrfToken={csrfToken} provider="vlm" />}
            />
            {selectedPreset === "zhipu" ? (
              <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
                请从 open.bigmodel.cn 的 API Keys 页面复制完整 Key（格式通常为 <code>id.secret</code>）。
                不要填 LLM 页里的硅基流动 <code>sk-</code> Key；同一套多模态通吃请改勾选「复用大模型凭据」。
              </p>
            ) : null}
          </div>
          ) : null}

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
              {query.data?.available ? "● 视觉模型可用" : "● 视觉模型未就绪"}
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
                {query.data?.last_test_message ? (
                  <dd className="mt-1 break-all text-[11px] text-[#6b7280]">{query.data.last_test_message}</dd>
                ) : null}
              </div>
            </dl>
          </div>

          <div className="mt-6 rounded-xl border border-[#7047f6]/20 bg-[#7047f6]/[0.04] p-4 text-xs leading-5 text-[#4b5563]">
            <span className="flex items-center gap-1.5 font-semibold text-[#7047f6]">
              <Sparkles size={14} /> 配置说明
            </span>
            <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
              {selectedPreset === "zhipu"
                ? "默认使用免费 glm-4.6v-flash，也可选择标记付费的型号。部分视觉模型不在上游目录里，可直接选择推荐型号并测试连接。Key 与 LLM 页独立，也可显式复用 LLM 凭据。"
                : selectedPreset === "ollama"
                  ? "请确认 Ollama 已拉取 qwen2.5-vl 等视觉模型，名称须与 ollama list 完全一致。"
                  : selectedPreset === "modelscope"
                    ? "手填 VL 模型名。魔搭免费对话列表里的 7B/8B Instruct 不能看图。"
                    : selectedPreset === "siliconflow"
                      ? "拉取列表会筛掉纯文本模型，只保留名称含 VL/Vision 的项。"
                      : "请填写支持 OpenAI 兼容 /chat/completions 且能传 image_url 的视觉模型。"}
            </p>
          </div>
        </aside>
      </section>
    </main>
  )
}
