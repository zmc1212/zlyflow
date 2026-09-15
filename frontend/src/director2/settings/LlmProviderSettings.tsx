// LLM 大模型设置卡 —— 逐行复刻自 dev0914 z-admin/src/views/settings/LlmProviderSettings.vue
// Vue → React 对应：ref→useState、computed→渲染期变量、onMounted→useEffect、v-model→受控值；
// a-auto-complete → antd AutoComplete；数据层走工作台 /api/admin 体系（requestJson + jsonMutation），
// 错误提示 → director2ErrorDetail。当前后端 last_test_status 取值为「成功 / 失败」，与原版判断一致。
import { useCallback, useEffect, useState } from "react"
import { Alert, AutoComplete, Button, Input, Select, Switch, message } from "antd"
import { Bot, CheckCircle2, ExternalLink, RefreshCw } from "lucide-react"
import { jsonMutation, requestJson } from "../../api"
import { director2ErrorDetail } from "../api"
import "./llm-provider.css"

// 对应后端 LlmProviderResponse（backend/app/models.py）
interface LlmProviderConfig {
  enabled: boolean
  base_url: string
  model: string
  api_key_masked: string | null
  has_api_key: boolean
  credential_ready: boolean
  available: boolean
  unavailable_reason: string | null
  last_test_status: string | null
  last_test_message: string | null
  last_test_at: string | null
  supports_vision: boolean
}

// 对应后端 LlmModelCatalogResponse（models 元素为 LlmCatalogModel）
interface LlmCatalogResult {
  models: { id: string; label: string; free: boolean | null; owned_by: string | null }[]
  provider: string
  free_only: boolean
  message: string | null
}

interface LlmPreset {
  label: string
  value: string
  baseUrl: string
  model: string
  docUrl: string
  recommendedModels: { name: string; id: string }[]
}

const providerPresets: LlmPreset[] = [
  {
    label: "ModelScope 魔搭社区 (默认推荐)",
    value: "modelscope",
    baseUrl: "https://api-inference.modelscope.cn/v1",
    model: "deepseek-ai/DeepSeek-V4-Flash-0731",
    docUrl: "https://modelscope.cn/my/access/token",
    recommendedModels: [
      { name: "DeepSeek-V4-Flash (极速推荐)", id: "deepseek-ai/DeepSeek-V4-Flash-0731" },
      { name: "MiniMax-M1-80k", id: "MiniMax/MiniMax-M1-80k" },
    ],
  },
  {
    label: "阿里云百炼 / 通义千问 (DashScope)",
    value: "dashscope",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen-plus",
    docUrl: "https://bailian.console.aliyun.com/?apiKey=1",
    recommendedModels: [
      { name: "qwen-plus (通用优选)", id: "qwen-plus" },
      { name: "qwen-turbo (极速)", id: "qwen-turbo" },
      { name: "deepseek-v3", id: "deepseek-v3" },
    ],
  },
  {
    label: "SiliconFlow 硅基流动 (超多免费大模型)",
    value: "siliconflow",
    baseUrl: "https://api.siliconflow.cn/v1",
    model: "Qwen/Qwen2.5-7B-Instruct",
    docUrl: "https://cloud.siliconflow.cn/account/ak",
    recommendedModels: [
      { name: "Qwen2.5-7B (永久免费)", id: "Qwen/Qwen2.5-7B-Instruct" },
      { name: "DeepSeek-R1-8B (免费推理)", id: "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B" },
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
    label: "Ollama 本地部署 (100% 离线隐私)",
    value: "ollama",
    baseUrl: "http://127.0.0.1:11434/v1",
    model: "qwen2.5:7b",
    docUrl: "https://ollama.com",
    recommendedModels: [
      { name: "qwen2.5:7b (轻量推荐)", id: "qwen2.5:7b" },
      { name: "deepseek-r1:7b", id: "deepseek-r1:7b" },
    ],
  },
]

export default function LlmProviderSettings({ csrfToken }: { csrfToken: string }) {
  const [config, setConfig] = useState<LlmProviderConfig | null>(null)
  const [enabled, setEnabled] = useState(false)
  const [baseUrl, setBaseUrl] = useState("https://api-inference.modelscope.cn/v1")
  const [model, setModel] = useState("deepseek-ai/DeepSeek-V4-Flash-0731")
  const [apiKey, setApiKey] = useState("")
  const [selectedPreset, setSelectedPreset] = useState("modelscope")
  const [onlineModels, setOnlineModels] = useState<string[]>([])

  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [fetchingCatalog, setFetchingCatalog] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const currentPreset = providerPresets.find((p) => p.value === selectedPreset)

  const modelOptions = (() => {
    const list = new Set<string>()
    onlineModels.forEach((m) => list.add(m))
    currentPreset?.recommendedModels.forEach((m) => list.add(m.id))
    return Array.from(list).map((val) => ({ value: val }))
  })()

  const statusClass =
    config?.last_test_status === "成功"
      ? "status-success"
      : config?.last_test_status === "失败"
        ? "status-failed"
        : "status-idle"

  const statusLabel =
    config?.last_test_status === "成功"
      ? "已连通"
      : config?.last_test_status === "失败"
        ? "连接失败"
        : "尚未测试"

  const loadConfig = useCallback(async () => {
    try {
      const data = await requestJson<LlmProviderConfig>("/api/admin/providers/llm")
      setConfig(data)
      setEnabled(data.enabled)
      setBaseUrl(data.base_url)
      setModel(data.model)

      const matched = providerPresets.find((p) => p.baseUrl === data.base_url)
      if (matched) setSelectedPreset(matched.value)
    } catch (err) {
      setErrorMsg(director2ErrorDetail(err, "加载配置失败"))
    }
  }, [])

  const handlePresetChange = (val: string) => {
    const p = providerPresets.find((item) => item.value === val)
    if (p) {
      setBaseUrl(p.baseUrl)
      setModel(p.model)
    }
  }

  async function handleSave() {
    setErrorMsg(null)
    setSaving(true)
    try {
      const updated = await requestJson<LlmProviderConfig>(
        "/api/admin/providers/llm",
        jsonMutation(csrfToken, {
          enabled,
          base_url: baseUrl,
          model,
          api_key: apiKey || null,
        }, "PUT"),
      )
      setConfig(updated)
      setApiKey("")
      message.success("大模型配置已保存")
    } catch (err) {
      setErrorMsg(director2ErrorDetail(err, "保存失败"))
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    setErrorMsg(null)
    setTesting(true)
    try {
      const updated = await requestJson<LlmProviderConfig>(
        "/api/admin/providers/llm/test",
        jsonMutation(csrfToken, {
          base_url: baseUrl,
          model,
          api_key: apiKey || null,
        }, "POST"),
      )
      setConfig(updated)
      message.success("大模型连接测试成功！")
    } catch (err) {
      setErrorMsg(director2ErrorDetail(err, "测试失败"))
      await loadConfig()
    } finally {
      setTesting(false)
    }
  }

  async function handleFetchCatalog() {
    setFetchingCatalog(true)
    try {
      const res = await requestJson<LlmCatalogResult>(
        "/api/admin/providers/llm/models",
        jsonMutation(csrfToken, {
          base_url: baseUrl,
          api_key: apiKey || null,
        }, "POST"),
      )
      setOnlineModels(res.models.map((m) => m.id))
      message.success(res.message || `成功获取 ${res.models.length} 个可用模型`)
    } catch (err) {
      message.error(director2ErrorDetail(err, "获取模型列表失败"))
    } finally {
      setFetchingCatalog(false)
    }
  }

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  return (
    <div className="d2-llm-settings llm-settings-card">
      <div className="card-header">
        <div className="icon-badge llm-badge">
          <Bot size={22} />
        </div>
        <div>
          <h2 className="title">LLM 大语言模型服务</h2>
          <p className="desc">
            驱动剧本拆解、分镜创作、导演提示词优化与角色分析。兼容所有标准 OpenAI 格式接口。
          </p>
        </div>
      </div>

      <div className="card-body">
        <div className="settings-grid">
          <div className="form-col">
            {/* 启用开关 */}
            <div className="form-item row-item">
              <div>
                <span className="form-label">启用 LLM 大模型</span>
                <p className="form-sub">关闭后系统将暂停所有大模型分析与提示词生成任务</p>
              </div>
              <Switch checked={enabled} onChange={setEnabled} />
            </div>

            {/* 预设厂商选择 */}
            <div className="form-item">
              <label className="form-label">服务商预设方案</label>
              <Select
                value={selectedPreset}
                options={providerPresets.map((p) => ({ label: p.label, value: p.value }))}
                onChange={handlePresetChange}
              />
            </div>

            {/* Base URL */}
            <div className="form-item">
              <label className="form-label">Base URL (接口地址)</label>
              <Input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://api-inference.modelscope.cn/v1"
              />
            </div>

            {/* Model Name */}
            <div className="form-item">
              <div className="flex justify-between items-center">
                <label className="form-label">模型名称 (Model)</label>
                <Button
                  type="link"
                  size="small"
                  loading={fetchingCatalog}
                  onClick={handleFetchCatalog}
                  icon={<RefreshCw size={12} />}
                >
                  拉取可用模型
                </Button>
              </div>
              <AutoComplete
                value={model}
                onChange={(value: string) => setModel(value)}
                options={modelOptions}
                placeholder="例如：deepseek-ai/DeepSeek-V4-Flash-0731"
              />
              {/* 推荐模型快捷填入 */}
              {currentPreset?.recommendedModels.length ? (
                <div className="quick-tags">
                  <span className="tags-label">推荐快捷填入：</span>
                  {currentPreset.recommendedModels.map((rm) => (
                    <span key={rm.id} className="quick-tag" onClick={() => setModel(rm.id)}>
                      {rm.name}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>

            {/* API Key */}
            <div className="form-item">
              <div className="flex justify-between items-center">
                <label className="form-label">API Key / Token</label>
                {currentPreset?.docUrl ? (
                  <a href={currentPreset.docUrl} target="_blank" className="doc-link">
                    获取 Token <ExternalLink size={12} />
                  </a>
                ) : null}
              </div>
              <Input.Password
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={
                  config?.has_api_key ? config.api_key_masked || "已配置密钥 (留空保持不变)" : "请输入 API Key"
                }
              />
              {config?.has_api_key ? (
                <span className="help-text text-success">已加密存储；如不修改 API Key 请保持此输入框留空。</span>
              ) : null}
            </div>

            {errorMsg ? (
              <div className="form-item">
                <Alert type="error" showIcon message={errorMsg} />
              </div>
            ) : null}

            <div className="form-actions">
              <Button type="primary" loading={saving} onClick={handleSave}>
                保存配置
              </Button>
              <Button loading={testing} onClick={handleTest} icon={<CheckCircle2 size={15} />}>
                测试连接
              </Button>
            </div>
          </div>

          {/* 状态面板 */}
          <div className="status-col">
            <div className="status-panel">
              <p className="status-title">大模型连通测试</p>
              <p className={`status-badge ${statusClass}`}>
                <span className="status-dot" />
                {statusLabel}
              </p>
              {config?.last_test_message ? <p className="status-msg">{config.last_test_message}</p> : null}
              <p className="status-time">
                {config?.last_test_at
                  ? new Date(config.last_test_at).toLocaleString("zh-CN", { hour12: false })
                  : "未执行测试"}
              </p>
            </div>

            <div className="tips-panel mt-3">
              <p className="tips-title">配置提示</p>
              <ul className="tips-list">
                <li>
                  若使用 <b>本地 Ollama</b>，地址填 <code>http://127.0.0.1:11434/v1</code>，密钥可留空或填{" "}
                  <code>ollama</code>。
                </li>
                <li>
                  通义千问兼容地址：<code>https://dashscope.aliyuncs.com/compatible-mode/v1</code>。
                </li>
                <li>点击「拉取可用模型」可在线读取服务商支持的模型列表并自动补全。</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
