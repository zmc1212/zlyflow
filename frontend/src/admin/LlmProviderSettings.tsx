import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, AutoComplete, Button, Input, Select, Switch, Tag, message } from "antd"
import { Bot, CheckCircle2, ExternalLink, KeyRound, RefreshCw, Sparkles } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { jsonMutation, requestJson } from "../api"

type LlmConfig = {
  profile_id: string
  enabled: boolean
  base_url: string
  model: string
  reasoning_effort: string
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

type ProviderProfile = {
  profile_id: string
  configured: boolean
  base_url: string
  model: string
  reasoning_effort: string
  api_key_masked?: string | null
  has_api_key: boolean
  last_test_status?: string | null
  last_test_message?: string | null
  last_test_at?: string | null
}

type ProviderProfilesResponse = {
  active_profile_id: string
  profiles: ProviderProfile[]
}

const REASONING_EFFORT_OPTIONS = [
  { value: "auto", label: "自动（不发送参数）" },
  { value: "none", label: "关闭（none）" },
  { value: "minimal", label: "极低（minimal）" },
  { value: "low", label: "低（low，推荐）" },
  { value: "medium", label: "中（medium）" },
  { value: "high", label: "高（high）" },
  { value: "xhigh", label: "很高（xhigh）" },
  { value: "max", label: "最高（max）" },
  { value: "ultra", label: "超高（ultra）" },
]

function modelSupportsReasoningEffort(model: string): boolean {
  const lowered = model.trim().toLowerCase()
  if (lowered.includes("gpt-5")) return true
  const name = lowered.split("/").at(-1) || ""
  return /^(o1|o3|o4)/.test(name)
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
    label: "Modelink 极客云 (支持 GPT-4o 等)",
    value: "modelink",
    baseUrl: "https://api.modelink.ai/v1",
    model: "gpt-4o",
    docUrl: "https://docs.modelink.ai/api-endpoints/overview",
    recommendedModels: [
      { name: "GPT-4o", id: "gpt-4o" },
      { name: "GPT-4o Mini", id: "gpt-4o-mini" },
      { name: "Claude 3.5 Sonnet", id: "claude-3-5-sonnet-20240620" },
    ],
  },
  {
    label: "ModelScope 魔搭社区 (按魔粒计费)",
    value: "modelscope",
    baseUrl: "https://api-inference.modelscope.cn/v1",
    model: "deepseek-ai/DeepSeek-V4-Flash-0731",
    docUrl: "https://modelscope.cn/my/access/token",
    recommendedModels: [
      { name: "DeepSeek-V4-Flash (约 2 魔粒/次)", id: "deepseek-ai/DeepSeek-V4-Flash-0731" },
      { name: "DeepSeek-V4-Pro (更高消耗)", id: "deepseek-ai/DeepSeek-V4-Pro" },
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
      { name: "Qwen3-8B (免费)", id: "Qwen/Qwen3-8B" },
      { name: "DeepSeek-R1 蒸馏 8B (免费)", id: "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B" },
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
    label: "Ollama 本地离线千问/推理模型 (100% 本地运行，零云端消耗)",
    value: "ollama",
    baseUrl: "http://127.0.0.1:11434/v1",
    model: "qwen2.5:7b",
    docUrl: "https://ollama.com/library/qwen2.5",
    recommendedModels: [
      { name: "qwen2.5:7b-instruct (本机常见已拉取名)", id: "qwen2.5:7b-instruct" },
      { name: "qwen2.5:7b (推荐本地轻量，4GB显存)", id: "qwen2.5:7b" },
      { name: "qwen2.5:14b (进阶电影导演分析)", id: "qwen2.5:14b" },
      { name: "deepseek-r1:7b (本地推理模型)", id: "deepseek-r1:7b" },
      { name: "deepseek-r1:14b (深度思维链分析)", id: "deepseek-r1:14b" },
      { name: "qwen2.5-coder:7b", id: "qwen2.5-coder:7b" },
    ],
  },
  {
    label: "LM Studio 本地大模型",
    value: "lmstudio",
    baseUrl: "http://127.0.0.1:1234/v1",
    model: "qwen2.5-7b-instruct",
    docUrl: "https://lmstudio.ai/",
    recommendedModels: [
      { name: "qwen2.5-7b-instruct", id: "qwen2.5-7b-instruct" },
      { name: "deepseek-r1-distill-qwen-7b", id: "deepseek-r1-distill-qwen-7b" },
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

export default function LlmProviderSettings({ csrfToken }: { csrfToken: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["llm-provider"],
    queryFn: () => requestJson<LlmConfig>("/api/admin/providers/llm"),
  })
  const profilesQuery = useQuery({
    queryKey: ["llm-provider-profiles"],
    queryFn: () => requestJson<ProviderProfilesResponse>("/api/admin/providers/llm/profiles"),
  })

  const [enabled, setEnabled] = useState(false)
  const [baseUrl, setBaseUrl] = useState("https://api-inference.modelscope.cn/v1")
  const [model, setModel] = useState("Qwen/Qwen2.5-7B-Instruct")
  const [reasoningEffort, setReasoningEffort] = useState("low")
  const [apiKey, setApiKey] = useState("")
  const [selectedPreset, setSelectedPreset] = useState("modelscope")
  const [catalogModels, setCatalogModels] = useState<CatalogModel[]>([])
  const autoFetchedFor = useRef("")

  useEffect(() => {
    if (!query.data) return
    setEnabled(query.data.enabled)
    setBaseUrl(query.data.base_url)
    setModel(query.data.model)
    setReasoningEffort(query.data.reasoning_effort || "low")

    setSelectedPreset(query.data.profile_id || "custom")
  }, [query.data?.enabled, query.data?.base_url, query.data?.model, query.data?.reasoning_effort, query.data?.has_api_key])

  const handlePresetChange = (presetValue: string) => {
    setSelectedPreset(presetValue)
    const found = PROVIDER_PRESETS.find((p) => p.value === presetValue)
    const saved = profilesQuery.data?.profiles.find((profile) => profile.profile_id === presetValue)
    setBaseUrl(saved?.base_url ?? found?.baseUrl ?? "")
    setModel(saved?.model ?? found?.model ?? "")
    setReasoningEffort(saved?.reasoning_effort || "low")
    setApiKey("")
    setCatalogModels([])
    autoFetchedFor.current = ""
  }

  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ["llm-provider"] }),
    queryClient.invalidateQueries({ queryKey: ["llm-provider-profiles"] }),
    queryClient.invalidateQueries({ queryKey: ["vlm-provider"] }),
  ])

  const save = useMutation({
    mutationFn: () =>
      requestJson<LlmConfig>(
        "/api/admin/providers/llm",
        jsonMutation(csrfToken, {
          profile_id: selectedPreset,
          enabled,
          base_url: baseUrl,
          model,
          reasoning_effort: reasoningEffort,
          api_key: apiKey || null,
        }, "PUT"),
      ),
    onSuccess: (data) => {
      setApiKey("")
      test.reset()
      queryClient.setQueryData(["llm-provider"], data)
      refresh()
      message.success("LLM 大模型配置已保存")
    },
  })

  const test = useMutation({
    mutationFn: () =>
      requestJson<LlmConfig>(
        "/api/admin/providers/llm/test",
        jsonMutation(csrfToken, {
          profile_id: selectedPreset,
          base_url: baseUrl,
          model,
          api_key: apiKey || null,
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
        "/api/admin/providers/llm/models",
        jsonMutation(csrfToken, {
          profile_id: selectedPreset,
          base_url: baseUrl,
          api_key: apiKey || null,
          free_only: selectedPreset === "siliconflow" || selectedPreset === "ollama" || selectedPreset === "lmstudio",
        }),
      ),
    onSuccess: (data) => {
      setCatalogModels(data.models)
      if (data.models.length) {
        message.success(`已拉取 ${data.models.length} 个${data.free_only ? "免费 " : ""}模型`)
      } else {
        message.warning(data.message || "未找到可用模型")
      }
    },
  })

  useEffect(() => {
    const selectedProfile = profilesQuery.data?.profiles.find((profile) => profile.profile_id === selectedPreset)
    const canFetchLocal = selectedPreset === "ollama" || selectedPreset === "lmstudio"
    const canFetchCloud = selectedPreset === "siliconflow" && Boolean(selectedProfile?.has_api_key || apiKey)
    if (!canFetchLocal && !canFetchCloud) return
    const key = `${selectedPreset}|${baseUrl}|${selectedProfile?.has_api_key ? "saved" : "none"}`
    if (autoFetchedFor.current === key) return
    autoFetchedFor.current = key
    catalog.mutate()
  }, [selectedPreset, baseUrl, profilesQuery.data, apiKey])

  const currentPreset = PROVIDER_PRESETS.find((p) => p.value === selectedPreset)
  const selectedProfile = profilesQuery.data?.profiles.find((profile) => profile.profile_id === selectedPreset)
  const modelOptions = useMemo(() => {
    const seen = new Set<string>()
    const rows: { value: string; label: string }[] = []
    const add = (id: string, label?: string, free?: boolean | null) => {
      if (!id || seen.has(id)) return
      // AutoComplete treats a shorter option as a match for a longer current value
      // (`DeepSeek-R1` vs `DeepSeek-R1-0528-Qwen3-8B`) and can overwrite the field.
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

  const error = save.error ?? test.error ?? catalog.error ?? query.error ?? profilesQuery.error

  return (
    <main className="mx-auto max-w-[1020px] px-5 py-6 lg:px-8">
      <div className="flex items-start gap-4 border-b border-black/[0.06] pb-5">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-[#7047f6]/10 text-[#7047f6]">
          <Bot size={22} />
        </span>
        <div>
          <h2 className="text-base font-semibold text-[#111827]">LLM 大模型服务</h2>
          <p className="mt-1 text-xs leading-5 text-[#4b5563]">
            通用 OpenAI 兼容协议，用于创作提示词润色、拆剧本和导演台对话。通过视觉探测的连接可带图写稿；VLM 页可直接复用这里的完整连接、模型与验证结果，也可独立配置。
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

          {selectedPreset === "modelscope" ? (
            <Alert
              type="warning"
              showIcon
              message="魔搭会扣除账户魔粒，不是独立免费次数"
              description="魔搭 API-Inference 已改为按魔粒计费。绑定阿里云后每日会赠送少量魔粒；赠送用尽后会继续扣除账户里签到、任务或充值获得的魔粒。工作台无法把调用限制为「只花赠送、不碰余额」。DeepSeek-V4 约 2 魔粒/次。不想消耗魔粒时，请改用硅基流动免费 7B，或本机 Ollama。"
            />
          ) : null}

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
                  <span>{selectedPreset === "ollama" || selectedPreset === "lmstudio" ? "查看模型文档" : "获取访问 Token"}</span>
                  <ExternalLink size={12} />
                </a>
              )}
            </div>
            <Input
              className="mt-1.5"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api-inference.modelscope.cn/v1"
              autoComplete="new-password"
            />
          </div>

          <div>
            <div className="flex items-center justify-between gap-3">
              <label className="block text-xs font-medium text-[#4b5563]">Model (模型名称)</label>
              <Button
                size="small"
                loading={catalog.isPending}
                onClick={() => catalog.mutate()}
                icon={<RefreshCw size={13} />}
              >
                拉取官方列表
              </Button>
            </div>
            <AutoComplete
              className="mt-1.5 w-full"
              value={model}
              options={modelOptions}
              defaultActiveFirstOption={false}
              onChange={(value) => setModel(value)}
              placeholder={selectedPreset === "siliconflow" ? "从官方目录选择价格为 0 的免费模型" : "选择或输入模型名称"}
              filterOption={(input, option) => {
                const query = (input || "").trim().toLowerCase()
                if (!query) return true
                const isExactOption = modelOptions.some((row) => row.value.toLowerCase() === query)
                if (isExactOption) return true
                const haystack = `${option?.value ?? ""} ${option?.label ?? ""}`.toLowerCase()
                return haystack.includes(query)
              }}
              listHeight={320}
            />
            <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
              {selectedPreset === "siliconflow"
                ? "展开下拉框会列出已拉取的全部免费对话模型；输入关键字才搜索。填写 Token 后点「拉取官方列表」。"
                : selectedPreset === "ollama" || selectedPreset === "lmstudio"
                  ? "展开下拉框可看到本机已安装模型，名称须与服务端完全一致。"
                  : "展开下拉框可看到推荐或已拉取的模型，也可直接输入模型 ID。"}
            </p>
            {query.data?.supports_vision && model.trim() === query.data.model && baseUrl.trim().replace(/\/+$/, "") === query.data.base_url.replace(/\/+$/, "") && selectedPreset === query.data.profile_id && !apiKey.trim() ? (
              <Alert
                className="mt-2"
                type="info"
                showIcon
                message="工坊写稿会带参考图调用此模型"
                description="当前连接已通过真实图片探测。工坊带图写稿会使用视觉能力；VLM 页启用复用连接后可直接共享此验证结果。"
              />
            ) : (
              <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
                模型名称不能证明是否支持看图。请保存当前连接并重新探测；要求看图的写稿不会静默降级为纯文本。
              </p>
            )}
          </div>

          {modelSupportsReasoningEffort(model) ? (
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">推理程度</label>
              <Select
                className="mt-1.5 w-full"
                value={reasoningEffort}
                onChange={setReasoningEffort}
                options={REASONING_EFFORT_OPTIONS}
              />
              <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
                仅对 GPT-5 / o 系列发送 <code>reasoning_effort</code>。等级越高通常推理更充分，但响应更慢、消耗更多；不确定中转站是否兼容时请选择“自动”。
              </p>
            </div>
          ) : null}

          <div>
            <label className="block text-xs font-medium text-[#4b5563]">API Key / Access Token</label>
            <Input.Password
              className="mt-1.5"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              prefix={<KeyRound size={15} className="text-[#9ca3af]" />}
              placeholder={
                selectedPreset === "ollama" || selectedPreset === "lmstudio"
                  ? "本地服务可留空"
                  : selectedProfile?.api_key_masked || "输入平台生成的 API Key / Token"
              }
              autoComplete="new-password"
            />
            {selectedPreset === "ollama" ? (
              <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
                Ollama 不需要云端 Token。模型名必须与 <code>ollama list</code> 完全一致；首次测试会把 7B 模型加载进显存，可能需要几十秒，请等按钮转完。
              </p>
            ) : null}
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
              {modelSupportsReasoningEffort(query.data?.model || "") ? (
                <div>
                  <dt className="text-[#6b7280]">推理程度</dt>
                  <dd className="mt-1 font-medium text-[#111827]">{query.data?.reasoning_effort || "low"}</dd>
                </div>
              ) : null}
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
              <Sparkles size={14} /> {selectedPreset === "ollama" ? "Ollama 本地连接说明" : selectedPreset === "modelink" ? "Modelink 说明" : selectedPreset === "modelscope" ? "魔搭魔粒说明" : selectedPreset === "siliconflow" ? "硅基流动免费说明" : "服务说明"}
            </span>
            <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
              {selectedPreset === "ollama"
                ? "请确认 Ollama 已启动且 11434 端口可访问。连接测试会真实调用当前模型；冷启动加载进显存时常超过 15 秒，工作台会等待最多 90 秒。若 ComfyUI 正在占满显卡，请等其空闲后再测。"
                : selectedPreset === "modelscope"
                  ? "魔搭不再提供独立于账户余额的免费次数池。调用会扣魔粒；工作台已对 DeepSeek-V4 关闭思考模式以降低单次消耗，但无法阻止扣费。"
                  : selectedPreset === "siliconflow"
                    ? "会拉取硅基流动全部模型，再用名称或标记里的 Free 文字筛选免费项。Qwen2.5-7B-Instruct 等免费模型不扣魔搭魔粒。"
                    : "请按所选平台的官方文档配置 Base URL、模型名和 API Key。拉取列表只验证目录接口；「测试连接」分别检查文本连接与双色图视觉能力。文本连接成功不等于支持看图，视觉探测结果以当前已保存连接为准。"}
            </p>
          </div>
        </aside>
      </section>
    </main>
  )
}
