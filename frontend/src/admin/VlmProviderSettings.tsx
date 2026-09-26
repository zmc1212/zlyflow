import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, AutoComplete, Button, Input, Select, Switch, Tag, message } from "antd"
import { CheckCircle2, ExternalLink, Eye, KeyRound, RefreshCw, Sparkles } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { jsonMutation, requestJson } from "../api"

type VlmConfig = {
  enabled: boolean
  use_llm_credentials?: boolean
  independent_base_url?: string | null
  independent_model?: string | null
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
  vision_capability?: string | null
  vision_capability_source?: string | null
  vision_capability_checked_at?: string | null
  vision_capability_message?: string | null
}

const VISION_CAP_LABEL: Record<string, { text: string; color: string }> = {
  supported: { text: "已验证可看图", color: "success" },
  unsupported: { text: "视觉探测未通过", color: "error" },
  unknown: { text: "未验证或已过期", color: "warning" },
}

type CatalogModel = {
  id: string
  label: string
  free?: boolean | null
  owned_by?: string | null
}

type CatalogResponse = {
  models: CatalogModel[]
  provider: string
  free_only: boolean
  message?: string | null
}

const PROVIDER_PRESETS = [
  {
    label: "智谱 GLM（推荐免费视觉）",
    value: "zhipu",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    model: "glm-4v-flash",
    docUrl: "https://open.bigmodel.cn/usercenter/proj-mgmt/apikeys",
    recommendedModels: [
      { name: "GLM-4.6V-Flash（免费，推荐）", id: "glm-4.6v-flash" },
      { name: "GLM-4V-Flash（永久免费）", id: "glm-4v-flash" },
      { name: "GLM-4.1V-Thinking-Flash（免费推理）", id: "glm-4.1v-thinking-flash" },
    ],
  },
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

function isShorterPrefixOf(candidate: string, target: string) {
  const left = candidate.trim()
  const right = target.trim()
  return Boolean(left && right && left !== right && right.startsWith(left))
}

function presetFromBaseUrl(baseUrl: string) {
  const lowered = baseUrl.toLowerCase()
  if (lowered.includes("bigmodel.cn") || lowered.includes("api.z.ai")) return "zhipu"
  if (lowered.includes("dashscope")) return "dashscope"
  if (lowered.includes("modelscope")) return "modelscope"
  if (lowered.includes("siliconflow")) return "siliconflow"
  if (lowered.includes("127.0.0.1:11434") || lowered.includes("localhost:11434")) return "ollama"
  return "custom"
}

export default function VlmProviderSettings({ csrfToken }: { csrfToken: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["vlm-provider"],
    queryFn: () => requestJson<VlmConfig>("/api/admin/providers/vlm"),
  })

  const [enabled, setEnabled] = useState(false)
  const [useLlm, setUseLlm] = useState(false)
  const [baseUrl, setBaseUrl] = useState("https://open.bigmodel.cn/api/paas/v4")
  const [model, setModel] = useState("glm-4v-flash")
  const [apiKey, setApiKey] = useState("")
  const [selectedPreset, setSelectedPreset] = useState("zhipu")
  const [catalogModels, setCatalogModels] = useState<CatalogModel[]>([])
  const autoFetchedFor = useRef("")
  const llmConnection = useQuery({
    queryKey: ["llm-provider"],
    queryFn: () => requestJson<VlmConfig>("/api/admin/providers/llm"),
    enabled: useLlm,
  })

  useEffect(() => {
    if (!query.data) return
    setEnabled(query.data.enabled)
    setUseLlm(Boolean(query.data.use_llm_credentials))
    setBaseUrl(query.data.independent_base_url ?? query.data.base_url)
    setModel(query.data.independent_model ?? query.data.model)
    setSelectedPreset(presetFromBaseUrl(query.data.independent_base_url ?? query.data.base_url))
  }, [query.data?.enabled, query.data?.use_llm_credentials, query.data?.base_url, query.data?.model, query.data?.independent_base_url, query.data?.independent_model])

  const handlePresetChange = (value: string) => {
    setSelectedPreset(value)
    const preset = PROVIDER_PRESETS.find((item) => item.value === value)
    if (!preset || value === "custom") return
    setBaseUrl(preset.baseUrl)
    setModel(preset.model)
    setCatalogModels([])
    autoFetchedFor.current = ""
  }

  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ["vlm-provider"] }),
    queryClient.invalidateQueries({ queryKey: ["llm-provider"] }),
  ])

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
    onSuccess: (data) => {
      if (!data.vision_capability_message?.includes("当前输入未保存")) refresh()
      if (data.vision_capability === "supported") message.success("文本连接与视觉探测均通过")
      else message.warning("文本连接成功，但视觉探测未通过；请查看具体原因")
    },
    onError: () => { void refresh() },
  })

  const catalog = useMutation({
    mutationFn: () =>
      requestJson<CatalogResponse>(
        "/api/admin/providers/vlm/models",
        jsonMutation(csrfToken, {
          base_url: baseUrl,
          api_key: apiKey.trim() || null,
          free_only: false,
          use_llm_credentials: useLlm,
        }),
      ),
    onSuccess: (data) => {
      setCatalogModels(data.models)
      if (data.models.length) {
        message.success(`已拉取 ${data.models.length} 个视觉模型`)
      } else {
        message.warning(data.message || "未找到可用视觉模型")
      }
    },
  })

  useEffect(() => {
    if (useLlm || query.data?.use_llm_credentials) return
    const canFetchLocal = selectedPreset === "ollama"
    const canFetchCloud = (selectedPreset === "siliconflow" || selectedPreset === "zhipu" || selectedPreset === "dashscope") && Boolean(query.data?.has_api_key || apiKey)
    if (!canFetchLocal && !canFetchCloud) return
    const key = `${selectedPreset}|${baseUrl}|${query.data?.has_api_key ? "saved" : "none"}`
    if (autoFetchedFor.current === key) return
    autoFetchedFor.current = key
    catalog.mutate()
  }, [useLlm, selectedPreset, baseUrl, query.data?.has_api_key, query.data?.use_llm_credentials])

  const currentPreset = PROVIDER_PRESETS.find((p) => p.value === selectedPreset)
  const modelOptions = useMemo(() => {
    const seen = new Set<string>()
    const rows: { value: string; label: string }[] = []
    const add = (id: string, label?: string, free?: boolean | null) => {
      if (!id || seen.has(id)) return
      if (isShorterPrefixOf(id, model)) return
      seen.add(id)
      const text = label || id
      rows.push({ value: id, label: free ? `${text} · Free` : text })
    }
    for (const item of catalogModels) add(item.id, item.label, item.free)
    add(model)
    for (const rec of currentPreset?.recommendedModels ?? []) add(rec.id, rec.name)
    return rows
  }, [catalogModels, model, currentPreset])

  const error = save.error ?? test.error ?? catalog.error ?? query.error

  return (
    <main className="mx-auto max-w-[1020px] px-5 py-6 lg:px-8">
      <div className="flex items-start gap-4 border-b border-black/[0.06] pb-5">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-[#7047f6]/10 text-[#7047f6]">
          <Eye size={22} />
        </span>
        <div>
          <h2 className="text-base font-semibold text-[#111827]">VLM 视觉模型</h2>
          <p className="mt-1 text-xs leading-5 text-[#4b5563]">
            用于反推 / 拉片 / 主体分析。可独立配置视觉模型，也可直接复用 LLM 页的完整连接、模型与视觉验证结果；是否可看图以实测为准。
          </p>
        </div>
      </div>

      {query.data && !query.data.credential_ready ? (
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
              <p className="text-sm font-medium text-[#111827]">复用大模型连接</p>
              <p className="mt-0.5 text-xs text-[#6b7280]">跟随 LLM 页的地址、密钥、模型与视觉验证结果，无需重复选择模型。关闭后恢复独立 VLM 配置。</p>
            </div>
            <Switch checked={useLlm} onChange={setUseLlm} />
          </div>

          {!useLlm ? <div>
            <label className="block text-xs font-medium text-[#4b5563]">快速服务预设</label>
            <Select
              className="mt-1.5 w-full"
              value={selectedPreset}
              disabled={useLlm}
              onChange={handlePresetChange}
              options={PROVIDER_PRESETS.map((p) => ({ value: p.value, label: p.label }))}
            />
          </div> : null}

          {!useLlm && selectedPreset === "modelscope" ? (
            <Alert
              type="warning"
              showIcon
              message="魔搭会扣除账户魔粒"
              description="VL 模型同样按魔粒计费。不想扣费请改用智谱 glm-4v-flash，或本机 Ollama。"
            />
          ) : null}

          {!useLlm && selectedPreset === "siliconflow" ? (
            <Alert
              type="info"
              showIcon
              message="硅基流动通用视觉模型按量计费"
              description="广场上免费的 VL 多为 OCR。角色外貌反推请用 Qwen3-VL 等通用视觉模型，会按 Token 扣费。"
            />
          ) : null}

          {useLlm ? (
            <Alert
              type={llmConnection.data?.supports_vision ? "success" : "warning"}
              showIcon
              message={llmConnection.data?.supports_vision ? "已复用 LLM 的视觉验证结果" : "跟随 LLM 完整连接"}
              description={`地址：${llmConnection.data?.base_url || "正在读取"}；模型：${llmConnection.data?.model || "正在读取"}。${llmConnection.data?.supports_vision ? "已验证可看图，无需再次验证。" : "尚未验证或已过期，请重新探测。"}${!query.data?.use_llm_credentials ? "当前为未保存预览，保存配置后生效。" : ""}`}
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
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://open.bigmodel.cn/api/paas/v4"
              autoComplete="new-password"
            />
          </div>
            </>
          )}

          <div>
            <div className="flex items-center justify-between gap-3">
              <label className="block text-xs font-medium text-[#4b5563]">Model (视觉模型名称)</label>
              <Button
                size="small"
                loading={catalog.isPending}
                disabled={useLlm}
                onClick={() => catalog.mutate()}
                icon={<RefreshCw size={13} />}
              >
                拉取官方列表
              </Button>
            </div>
            <AutoComplete
              className="mt-1.5 w-full"
              value={useLlm ? llmConnection.data?.model ?? query.data?.model ?? "" : model}
              disabled={useLlm}
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
            <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
              {useLlm ? "模型自动跟随 LLM 页；如需独立选择模型，请关闭复用连接。" : "可直接输入模型 ID；不按名称判断视觉能力，请通过测试验证。"}
            </p>
          </div>

          {!useLlm ? (
          <div>
            <label className="block text-xs font-medium text-[#4b5563]">API Key / Access Token</label>
            <Input.Password
              className="mt-1.5"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              prefix={<KeyRound size={15} className="text-[#9ca3af]" />}
              placeholder={
                selectedPreset === "ollama"
                  ? "本地服务可留空"
                  : query.data?.api_key_masked || "输入平台生成的 API Key / Token"
              }
              autoComplete="new-password"
            />
            {selectedPreset === "zhipu" ? (
              <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
                请从 open.bigmodel.cn 的 API Keys 页面复制完整 Key（格式通常为 <code>id.secret</code>）。
                不要混用其他供应商的 Key；如需使用 LLM 页的同一连接，请勾选「复用大模型连接」。
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
            <Button loading={test.isPending} disabled={save.isPending} onClick={() => test.mutate()} icon={<RefreshCw size={15} />}>
              重新探测视觉能力
            </Button>
          </div>
          <p className="text-xs text-[var(--studio-text-secondary)]">测试会先验证文本连接，再用两张单色图探测视觉能力；不会生成业务文稿。修改地址、模型或密钥后需要重新验证。</p>
          {test.data ? <Alert showIcon type={test.data.vision_capability === "supported" ? "success" : "warning"}
            message={`最近一次测试（${test.data.model}）：${VISION_CAP_LABEL[test.data.vision_capability || "unknown"]?.text || "未验证"}`}
            description={test.data.vision_capability_message} /> : null}
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
              <div>
                <dt className="text-[#6b7280]">已保存连接的看图能力</dt>
                <dd className="mt-1"><Tag color={VISION_CAP_LABEL[query.data?.vision_capability || "unknown"]?.color || "warning"}>
                  {VISION_CAP_LABEL[query.data?.vision_capability || "unknown"]?.text || "未探测"}
                </Tag></dd>
                {query.data?.vision_capability_checked_at ? (
                  <dd className="mt-1 text-[11px] text-[#6b7280]">
                    探测于 {new Date(query.data.vision_capability_checked_at).toLocaleString("zh-CN", { hour12: false })}
                  </dd>
                ) : null}
                {query.data?.vision_capability_source === "legacy_name_guess" ? (
                  <dd className="mt-1 text-[11px] text-[#6b7280]">来自名称推断，尚未实测，点「测试连接」可真实探测。</dd>
                ) : null}
                {query.data?.vision_capability_message ? (
                  <dd className="mt-1 break-all text-[11px] text-[#6b7280]">{query.data.vision_capability_message}</dd>
                ) : null}
              </div>
            </dl>
          </div>

          <div className="mt-6 rounded-xl border border-[#7047f6]/20 bg-[#7047f6]/[0.04] p-4 text-xs leading-5 text-[#4b5563]">
            <span className="flex items-center gap-1.5 font-semibold text-[#7047f6]">
              <Sparkles size={14} /> 配置说明
            </span>
            <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
              {useLlm
                ? "当前使用 LLM 页的同一连接与视觉验证结果。独立 VLM 的地址、模型和密钥已保留，关闭复用后恢复。"
                : selectedPreset === "zhipu"
                ? "智谱 VL 模型（glm-4.6v-flash / glm-4v-flash）不在 /models 文本目录里，测试连接会直接试调用。Key 与 LLM 页互不影响。"
                : selectedPreset === "ollama"
                  ? "请确认 Ollama 已拉取 qwen2.5-vl 等视觉模型，名称须与 ollama list 完全一致。"
                  : selectedPreset === "modelscope"
                    ? "可手填模型 ID 并探测视觉能力；目录和模型名称不代表支持图片。"
                    : selectedPreset === "siliconflow"
                      ? "目录仅提供候选模型，不按名称排除；是否支持图片以视觉探测为准。"
                      : "请填写支持 OpenAI 兼容 /chat/completions 且能传 image_url 的视觉模型。"}
            </p>
          </div>
        </aside>
      </section>
    </main>
  )
}
