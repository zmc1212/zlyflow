// ComfyUI 供应商设置卡 —— 逐行复刻自 dev0914 z-admin/src/views/settings/ComfyProviderSettings.vue
// Vue → React 对应：ref→useState、computed→渲染期变量、onMounted→useEffect；
// ant-design-vue 组件 → antd 同名组件；数据层走工作台 /api/admin 体系（requestJson + jsonMutation），
// 错误提示 err?.response?.data?.detail → director2ErrorDetail。
import { useCallback, useEffect, useState } from "react"
import { Alert, Button, Input, Select, message } from "antd"
import { CheckCircle2, MonitorPlay } from "lucide-react"
import { jsonMutation, requestJson } from "../../api"
import { director2ErrorDetail } from "../api"
import "./comfy-provider.css"

// 对应后端 ComfyProviderResponse（backend/app/models.py）
interface ComfyProviderConfig {
  base_url: string
  env_default: string
  last_test_status: string | null
  last_test_message: string | null
  last_test_at: string | null
}

const urlPresets = [
  { label: "本机默认 8188", value: "http://127.0.0.1:8188" },
  { label: "服务器 FRP 18188", value: "http://127.0.0.1:18188" },
  { label: "自定义地址", value: "custom" },
]

export default function ComfyProviderSettings({ csrfToken }: { csrfToken: string }) {
  const [config, setConfig] = useState<ComfyProviderConfig | null>(null)
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:8188")
  const [selectedPreset, setSelectedPreset] = useState("http://127.0.0.1:8188")
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const statusClass =
    config?.last_test_status === "success"
      ? "status-success"
      : config?.last_test_status === "failed"
        ? "status-failed"
        : "status-idle"

  const statusLabel =
    config?.last_test_status === "success"
      ? "已连通"
      : config?.last_test_status === "failed"
        ? "连接失败"
        : "尚未测试"

  const loadConfig = useCallback(async () => {
    try {
      const data = await requestJson<ComfyProviderConfig>("/api/admin/providers/comfy")
      setConfig(data)
      setBaseUrl(data.base_url)
      if (urlPresets.some((p) => p.value === data.base_url)) {
        setSelectedPreset(data.base_url)
      } else {
        setSelectedPreset("custom")
      }
    } catch (err) {
      setErrorMsg(director2ErrorDetail(err, "加载 ComfyUI 配置失败"))
    }
  }, [])

  const handlePresetChange = (val: string) => {
    if (val !== "custom") {
      setBaseUrl(val)
    }
  }

  async function handleSave() {
    setErrorMsg(null)
    setSaving(true)
    try {
      const updated = await requestJson<ComfyProviderConfig>(
        "/api/admin/providers/comfy",
        jsonMutation(csrfToken, { base_url: baseUrl }, "PUT"),
      )
      setConfig(updated)
      message.success("ComfyUI 连接地址已保存，后续视频任务立即使用新地址")
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
      const updated = await requestJson<ComfyProviderConfig>(
        "/api/admin/providers/comfy/test",
        jsonMutation(csrfToken, { base_url: baseUrl }, "POST"),
      )
      setConfig(updated)
      message.success("ComfyUI 连接测试成功")
    } catch (err) {
      setErrorMsg(director2ErrorDetail(err, "连接测试失败"))
      await loadConfig()
    } finally {
      setTesting(false)
    }
  }

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  return (
    <div className="d2-comfy-settings comfy-settings-card">
      <div className="card-header">
        <div className="icon-badge comfy-badge">
          <MonitorPlay size={22} />
        </div>
        <div>
          <h2 className="title">ComfyUI 视频后端</h2>
          <p className="desc">
            工作台只连接一个 ComfyUI 实例。保存后立即对后续视频任务生效，无需重启。宿主机浏览器直连交付使用本机
            <code className="code-tag">http://127.0.0.1:8188/view</code>。
          </p>
        </div>
      </div>

      <div className="card-body">
        <div className="form-col">
          <div className="form-item">
            <label className="form-label">常用预设地址</label>
            <Select
              value={selectedPreset}
              style={{ width: "100%" }}
              options={urlPresets}
              onChange={handlePresetChange}
            />
          </div>

          <div className="form-item">
            <label className="form-label">ComfyUI 连接地址</label>
            <Input
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="http://127.0.0.1:8188"
              allowClear
            />
            {config?.env_default ? (
              <span className="help-text">默认配置值：{config.env_default}</span>
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

        <div className="status-col">
          <div className="status-panel">
            <p className="status-title">最近连接状态</p>
            <p className={`status-badge ${statusClass}`}>
              <span className="status-dot" />
              {statusLabel}
            </p>
            {config?.last_test_message ? <p className="status-msg">{config.last_test_message}</p> : null}
            <p className="status-time">
              {config?.last_test_at
                ? new Date(config.last_test_at).toLocaleString("zh-CN", { hour12: false })
                : "保存或测试后记录结果"}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
