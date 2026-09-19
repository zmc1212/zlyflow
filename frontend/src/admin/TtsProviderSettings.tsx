import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Input, Select, Switch, message } from "antd"
import { CheckCircle2, ExternalLink, KeyRound, Mic, Sparkles } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { jsonMutation, requestJson } from "../api"

type TtsConfig = {
  enabled: boolean
  use_llm_credentials: boolean
  base_url: string
  model: string
  voice: string
  api_key_masked?: string | null
  has_api_key: boolean
  credential_ready: boolean
  available: boolean
  unavailable_reason?: string | null
  last_test_status?: string | null
  last_test_message?: string | null
  last_test_at?: string | null
  voices: { id: string; label: string; gender?: string }[]
  provider?: string
  supports_clone?: boolean
}

type VoiceOption = { id: string; label: string; gender?: string }

type TtsPreset = {
  label: string
  value: string
  baseUrl: string
  model: string
  voice: string
  docUrl: string
  recommendedModels: { name: string; id: string }[]
  voices: VoiceOption[]
}

const COSYVOICE2_MODEL = "FunAudioLLM/CosyVoice2-0.5B"

const SILICONFLOW_VOICES: VoiceOption[] = [
  { id: `${COSYVOICE2_MODEL}:alex`, label: "Alex（沉稳男声）", gender: "male" },
  { id: `${COSYVOICE2_MODEL}:benjamin`, label: "Benjamin（低沉男声）", gender: "male" },
  { id: `${COSYVOICE2_MODEL}:charles`, label: "Charles（磁性男声）", gender: "male" },
  { id: `${COSYVOICE2_MODEL}:david`, label: "David（活泼男声）", gender: "male" },
  { id: `${COSYVOICE2_MODEL}:anna`, label: "Anna（沉稳女声）", gender: "female" },
  { id: `${COSYVOICE2_MODEL}:bella`, label: "Bella（激情女声）", gender: "female" },
  { id: `${COSYVOICE2_MODEL}:claire`, label: "Claire（温柔女声）", gender: "female" },
  { id: `${COSYVOICE2_MODEL}:diana`, label: "Diana（活泼女声）", gender: "female" },
]

const OPENAI_VOICES: VoiceOption[] = [
  { id: "alloy", label: "Alloy（中性）" },
  { id: "echo", label: "Echo（男声）", gender: "male" },
  { id: "fable", label: "Fable（叙事）" },
  { id: "onyx", label: "Onyx（低沉男声）", gender: "male" },
  { id: "nova", label: "Nova（女声）", gender: "female" },
  { id: "shimmer", label: "Shimmer（柔和女声）", gender: "female" },
]

const PROVIDER_PRESETS: TtsPreset[] = [
  {
    label: "本机 IndexTTS-2.5（角色克隆，推荐配音台）",
    value: "indextts",
    baseUrl: "http://127.0.0.1:7866/v1",
    model: "indextts-2.5",
    voice: "clone",
    docUrl: "",
    recommendedModels: [
      { name: "IndexTTS-2.5（本机旁路）", id: "indextts-2.5" },
    ],
    voices: [{ id: "clone", label: "角色参考音克隆" }],
  },
  {
    label: "SiliconFlow 硅基流动（CosyVoice2，无 GPU 时降级）",
    value: "siliconflow",
    baseUrl: "https://api.siliconflow.cn/v1",
    model: COSYVOICE2_MODEL,
    voice: `${COSYVOICE2_MODEL}:alex`,
    docUrl: "https://cloud.siliconflow.cn/account/ak",
    recommendedModels: [
      { name: "CosyVoice2-0.5B（推荐，多语种/方言）", id: COSYVOICE2_MODEL },
      { name: "MOSS-TTSD-v0.5（双人克隆，高级）", id: "fnlp/MOSS-TTSD-v0.5" },
    ],
    voices: SILICONFLOW_VOICES,
  },
  {
    label: "OpenAI 官方 TTS",
    value: "openai",
    baseUrl: "https://api.openai.com/v1",
    model: "tts-1",
    voice: "alloy",
    docUrl: "https://platform.openai.com/api-keys",
    recommendedModels: [
      { name: "tts-1（标准）", id: "tts-1" },
      { name: "tts-1-hd（高清）", id: "tts-1-hd" },
    ],
    voices: OPENAI_VOICES,
  },
  {
    label: "自定义 OpenAI 兼容接口",
    value: "custom",
    baseUrl: "",
    model: "tts-1",
    voice: "alloy",
    docUrl: "",
    recommendedModels: [],
    voices: OPENAI_VOICES,
  },
]

const OPENAI_LEGACY_MODELS = new Set(["tts-1", "tts-1-hd", "alloy", "echo", "fable", "onyx", "nova", "shimmer"])

function presetFromConfig(baseUrl: string, model: string) {
  const lowered = baseUrl.toLowerCase()
  const loweredModel = model.toLowerCase()
  if (lowered.includes("7866") || lowered.includes("indextts") || loweredModel.includes("indextts")) return "indextts"
  if (lowered.includes("siliconflow")) return "siliconflow"
  if (loweredModel.includes("cosyvoice") || loweredModel.includes("moss-ttsd") || loweredModel.startsWith("funaudiollm/")) {
    return "siliconflow"
  }
  if (lowered.includes("openai.com") || loweredModel === "tts-1" || loweredModel === "tts-1-hd") return "openai"
  return "custom"
}

function isOpenAiLegacyModel(model: string) {
  return OPENAI_LEGACY_MODELS.has(model.trim().toLowerCase())
}

function voicesForPreset(preset: TtsPreset | undefined, serverVoices: VoiceOption[]) {
  if (serverVoices.length) return serverVoices
  return preset?.voices ?? OPENAI_VOICES
}

export default function TtsProviderSettings({ csrfToken }: { csrfToken: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["tts-provider"],
    queryFn: () => requestJson<TtsConfig>("/api/admin/providers/tts"),
  })
  const [enabled, setEnabled] = useState(false)
  const [useLlm, setUseLlm] = useState(true)
  const [baseUrl, setBaseUrl] = useState("")
  const [model, setModel] = useState("tts-1")
  const [voice, setVoice] = useState("alloy")
  const [apiKey, setApiKey] = useState("")
  const [selectedPreset, setSelectedPreset] = useState("siliconflow")

  useEffect(() => {
    if (!query.data) return
    setEnabled(query.data.enabled)
    setUseLlm(query.data.use_llm_credentials)
    setBaseUrl(query.data.base_url)
    const preset = presetFromConfig(query.data.base_url, query.data.model)
    setSelectedPreset(preset)
    // 复用硅基 LLM 凭据时，旧配置常残留 tts-1；自动切到 CosyVoice2，避免选了硅基却仍显示 OpenAI 模型
    if (preset === "siliconflow" && isOpenAiLegacyModel(query.data.model)) {
      setModel(COSYVOICE2_MODEL)
      setVoice(`${COSYVOICE2_MODEL}:alex`)
    } else {
      setModel(query.data.model)
      setVoice(query.data.voice)
    }
  }, [query.data])

  const currentPreset = PROVIDER_PRESETS.find((item) => item.value === selectedPreset) ?? PROVIDER_PRESETS[0]
  const effectiveBaseUrl = useLlm ? (query.data?.base_url || baseUrl) : baseUrl
  const voiceOptions = useMemo(() => {
    const rows = voicesForPreset(currentPreset, query.data?.voices ?? [])
    const seen = new Set<string>()
    const options: { value: string; label: string }[] = []
    const add = (id: string, label?: string) => {
      if (!id || seen.has(id)) return
      seen.add(id)
      options.push({ value: id, label: label || id })
    }
    for (const item of rows) add(item.id, item.label)
    add(voice)
    return options
  }, [currentPreset, query.data?.voices, voice])

  const handlePresetChange = (value: string) => {
    setSelectedPreset(value)
    const preset = PROVIDER_PRESETS.find((item) => item.value === value)
    if (!preset || value === "custom") return
    if (value === "indextts") {
      setUseLlm(false)
      setBaseUrl(preset.baseUrl)
    } else if (!useLlm) {
      setBaseUrl(preset.baseUrl)
    }
    setModel(preset.model)
    setVoice(preset.voice)
  }

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["tts-provider"] })
  const payload = {
    enabled,
    use_llm_credentials: useLlm,
    base_url: baseUrl,
    model,
    voice,
    api_key: apiKey || null,
  }
  const save = useMutation({
    mutationFn: () => requestJson<TtsConfig>("/api/admin/providers/tts", jsonMutation(csrfToken, payload, "PUT")),
    onSuccess: () => {
      setApiKey("")
      refresh()
      message.success("TTS 配置已保存")
    },
  })
  const test = useMutation({
    mutationFn: () => requestJson<TtsConfig>("/api/admin/providers/tts/test", jsonMutation(csrfToken, payload)),
    onSuccess: () => {
      refresh()
      message.success("语音合成测试成功")
    },
  })
  const error = save.error ?? test.error ?? query.error

  return (
    <main className="mx-auto max-w-[1020px] px-5 py-6 lg:px-8">
      <div className="flex items-start gap-4 border-b border-black/[0.06] pb-5">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-[#7047f6]/10 text-[#7047f6]">
          <Mic size={22} />
        </span>
        <div>
          <h2 className="text-base font-semibold text-[#111827]">TTS 语音合成</h2>
          <p className="mt-1 text-xs leading-5 text-[#4b5563]">
            导演台2 配音台走本机 IndexTTS-2.5 旁路（参考音克隆 + 情绪/语速）。无 GPU 或旁路未启动时，可降级硅基 CosyVoice2 系统音色。测试连接对 IndexTTS 只打 <code>/health</code>，不会真正合成。
          </p>
        </div>
      </div>

      {!query.data?.credential_ready && !useLlm ? (
        <Alert
          className="mt-5"
          type="warning"
          showIcon
          message="凭证主密钥不可用"
          description="请在部署环境设置 ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY。独立 TTS 凭据将无法加密保存。"
        />
      ) : null}

      <section className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm space-y-5">
          <div className="flex items-center justify-between gap-4 border-b border-black/[0.06] pb-4">
            <div>
              <p className="text-sm font-medium text-[#111827]">启用语音合成</p>
              <p className="mt-0.5 text-xs text-[#6b7280]">开启后导演台可按对白生成可播放配音。</p>
            </div>
            <Switch checked={enabled} onChange={setEnabled} />
          </div>

          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-[#111827]">复用大模型凭据</p>
              <p className="mt-0.5 text-xs text-[#6b7280]">
                {selectedPreset === "indextts"
                  ? "本机 IndexTTS 旁路不需要 API Key，也不复用大模型凭据。"
                  : "使用 LLM 大模型页的 Base URL 与 API Key。LLM 为硅基流动时可直接复用同一 Key。"}
              </p>
            </div>
            <Switch checked={useLlm} disabled={selectedPreset === "indextts"} onChange={setUseLlm} />
          </div>

          <div>
            <label className="block text-xs font-medium text-[#4b5563]">快速服务预设</label>
            <Select
              className="mt-1.5 w-full"
              value={selectedPreset}
              onChange={handlePresetChange}
              options={PROVIDER_PRESETS.map((item) => ({ value: item.value, label: item.label }))}
            />
          </div>

          {selectedPreset === "indextts" ? (
            <Alert
              type="info"
              showIcon
              message="旁路服务默认 http://127.0.0.1:7866"
              description="权重放在工作台父级「整合包及模型/index-tts/checkpoints」，不要装进 FastAPI 虚拟环境。双击仓库根目录「启动 IndexTTS 旁路.bat」。H3 出片前会卸载 IndexTTS；配音前会对 ComfyUI POST /free。"
            />
          ) : null}

          {selectedPreset === "siliconflow" ? (
            <Alert
              type="info"
              showIcon
              message="云端 TTS 没有「永久免费」档（不像 LLM 7B）"
              description="硅基 CosyVoice2 按量计费，单价很低，新账号通常有赠送余额，日常试听/短对白基本够用。请把模型选成 CosyVoice2-0.5B，不要用 OpenAI 的 tts-1。"
            />
          ) : null}

          {useLlm && selectedPreset !== "indextts" ? (
            <Alert
              type="info"
              showIcon
              message="Base URL 与 API Key 来自 LLM 大模型页"
              description={`当前生效地址：${effectiveBaseUrl || "未配置"}。请确认 LLM 供应商支持 /audio/speech，并在下方选择匹配的 TTS 模型与音色。`}
            />
          ) : (
            <>
              <div>
                <div className="flex items-center justify-between">
                  <label className="block text-xs font-medium text-[#4b5563]">TTS Base URL</label>
                  {currentPreset.docUrl ? (
                    <a
                      href={currentPreset.docUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1 text-xs font-medium text-[#7047f6] hover:underline"
                    >
                      <span>获取访问 Token</span>
                      <ExternalLink size={12} />
                    </a>
                  ) : null}
                </div>
                <Input
                  className="mt-1.5"
                  value={baseUrl}
                  onChange={(event) => {
                    setBaseUrl(event.target.value)
                    setSelectedPreset(presetFromConfig(event.target.value, model))
                  }}
                  placeholder={selectedPreset === "indextts" ? "http://127.0.0.1:7866/v1" : "https://api.siliconflow.cn/v1"}
                />
              </div>
              {selectedPreset === "indextts" ? null : (
              <div>
                <label className="block text-xs font-medium text-[#4b5563]">API Key</label>
                <Input.Password
                  className="mt-1.5"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  prefix={<KeyRound size={15} className="text-[#9ca3af]" />}
                  placeholder={query.data?.api_key_masked || "独立 TTS 密钥，复用大模型时可留空"}
                />
              </div>
              )}
            </>
          )}

          <div>
            <label className="block text-xs font-medium text-[#4b5563]">模型</label>
            {currentPreset.recommendedModels.length ? (
              <Select
                className="mt-1.5 w-full"
                value={model}
                options={[
                  ...currentPreset.recommendedModels.map((item) => ({ value: item.id, label: item.name })),
                  ...(model && !currentPreset.recommendedModels.some((item) => item.id === model)
                    ? [{ value: model, label: model }]
                    : []),
                ]}
                onChange={(value) => {
                  setModel(value)
                  if (selectedPreset === "siliconflow" && value === COSYVOICE2_MODEL && !voice.includes(":")) {
                    setVoice(`${COSYVOICE2_MODEL}:alex`)
                  }
                }}
              />
            ) : (
              <Input className="mt-1.5" value={model} onChange={(event) => setModel(event.target.value)} placeholder="tts-1" />
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-[#4b5563]">默认音色</label>
            <Select
              className="mt-1.5 w-full"
              value={voice}
              options={voiceOptions}
              onChange={setVoice}
              showSearch
              optionFilterProp="label"
            />
            {selectedPreset === "siliconflow" ? (
              <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
                硅基流动音色 ID 格式为 <code>模型:角色名</code>。导演台男/女声默认会映射到 Benjamin / Bella。
              </p>
            ) : selectedPreset === "indextts" ? (
              <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
                配音台按角色资产参考音克隆，不使用系统音色列表。情绪八维与语速在工坊「配音」Tab 逐句设置。
              </p>
            ) : null}
          </div>

          {error ? <Alert type="error" showIcon message={error.message} /> : null}
          <div className="flex flex-wrap gap-3 pt-2">
            <Button type="primary" loading={save.isPending} onClick={() => save.mutate()}>保存配置</Button>
            <Button loading={test.isPending} onClick={() => test.mutate()} icon={<CheckCircle2 size={15} />}>测试连接</Button>
          </div>
        </div>

        <aside className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm flex flex-col justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-[#6b7280]">TTS 状态</p>
            <p className={`mt-3 text-sm font-semibold ${query.data?.available ? "text-emerald-600" : "text-amber-600"}`}>
              {query.data?.available ? "● 语音合成可用" : "● 语音合成未就绪"}
            </p>
            {query.data?.unavailable_reason ? (
              <p className="mt-2 text-xs leading-5 text-[#6b7280]">{query.data.unavailable_reason}</p>
            ) : null}
            <dl className="mt-6 space-y-4 text-xs">
              <div>
                <dt className="text-[#6b7280]">当前模型 / 音色</dt>
                <dd className="mt-1 font-medium text-[#111827] break-all">{query.data?.model || "未配置"} · {query.data?.voice || "alloy"}</dd>
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
              {selectedPreset === "indextts"
                ? "测试连接只检查旁路 /health 与权重目录，不会占用显存合成。请先启动 IndexTTS 旁路。"
                : selectedPreset === "siliconflow"
                ? "与 LLM 同用硅基流动时，勾选复用凭据即可，无需重复填 Key。CosyVoice2 支持中文、英文及多种方言。"
                : selectedPreset === "openai"
                  ? "OpenAI 官方 tts-1 按字符计费，音色为 alloy / nova 等 6 种。"
                  : "请填写支持 OpenAI 兼容 POST /audio/speech 的上游地址与模型名。"}
            </p>
          </div>
        </aside>
      </section>
    </main>
  )
}
