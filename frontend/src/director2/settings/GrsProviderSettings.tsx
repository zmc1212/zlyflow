// GRS 生图供应商设置卡 —— 逐行复刻自 dev0914 z-admin/src/views/settings/GrsProviderSettings.vue
// Vue → React 对应：ref→useState、computed→渲染期变量、onMounted→useEffect、v-model→受控值；
// a-table 插槽 bodyCell → columns render；a-modal → antd Modal（挂 d2-grs-settings 类，弹层内样式继续命中）。
// 数据层走工作台 /api/admin 体系（requestJson + jsonMutation），错误提示 → director2ErrorDetail。
// 差异：当前工作台 API 无 max_storyboard_concurrency 字段（见 backend/app/models.py GrsProviderUpdateRequest/
// GrsProviderResponse），UI 保留展示（默认 5）、加载与提交均不读写该字段。
import { useCallback, useEffect, useState } from "react"
import {
  Alert,
  Button,
  Input,
  InputNumber,
  Modal,
  Radio,
  Select,
  Switch,
  Table,
  Tag,
  message,
} from "antd"
import type { TableColumnsType } from "antd"
import { CheckCircle2, Cloud, Plus, RefreshCw } from "lucide-react"
import { jsonMutation, requestJson } from "../../api"
import { director2ErrorDetail } from "../api"
import "./grs-provider.css"

// 对应后端 GrsProviderResponse（backend/app/models.py）
interface GrsProviderConfig {
  enabled: boolean
  base_url: string
  api_key_masked: string | null
  has_api_key: boolean
  credential_ready: boolean
  gpt_image_2_enabled: boolean
  gpt_image_2_vip_enabled: boolean
  models: string
  vip_models: string
  last_test_status: string | null
  last_test_message: string | null
  last_test_at: string | null
  last_balance: number | null
  last_balance_at: string | null
  available: boolean
  unavailable_reason: string | null
}

// 对应后端 GrsImageModelResponse
interface GrsImageModel {
  workflow_id: string
  provider_model: string
  display_name: string
  description: string
  profile: string
  resolutions: string[] | null
  enabled: boolean
  sort_order: number
  is_default: boolean
  builtin: boolean
}

// 对应后端 GrsImageModelsResponse（profiles 为 { value, label } 字典列表）
interface GrsProfileOption {
  value: string
  label: string
}

interface GrsCatalogPayload {
  models: GrsImageModel[]
  profiles: GrsProfileOption[]
}

// 对应后端 GrsBalanceResponse
interface GrsBalanceResult {
  credits: number
  queried_at: string
}

interface NewGrsModelForm {
  provider_model: string
  display_name: string
  profile: string
  description: string
}

export default function GrsProviderSettings({ csrfToken }: { csrfToken: string }) {
  const [config, setConfig] = useState<GrsProviderConfig | null>(null)
  const [enabled, setEnabled] = useState(false)
  const [baseUrl, setBaseUrl] = useState("https://grsai.dakka.com.cn")
  const [apiKey, setApiKey] = useState("")
  const [maxStoryboardConcurrency, setMaxStoryboardConcurrency] = useState<number | null>(5)
  const [models, setModels] = useState<GrsImageModel[]>([])
  const [profiles, setProfiles] = useState<GrsProfileOption[]>([])

  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [refreshingBalance, setRefreshingBalance] = useState(false)
  const [savingModels, setSavingModels] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const [addModalVisible, setAddModalVisible] = useState(false)
  const [newModel, setNewModel] = useState<NewGrsModelForm>({
    provider_model: "",
    display_name: "",
    profile: "nano_banana",
    description: "",
  })

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

  function getProfileLabel(p: string) {
    const item = profiles.find((i) => i.value === p)
    return item?.label || p
  }

  const columns: TableColumnsType<GrsImageModel> = [
    {
      title: "模型名称",
      key: "display_name",
      render: (_, record) => (
        <div>
          <span className="font-medium">{record.display_name}</span>
          <p className="text-xs text-gray-500 m-0">{record.provider_model}</p>
        </div>
      ),
    },
    {
      title: "规格类型",
      key: "profile",
      width: 220,
      render: (_, record) => <Tag color="purple">{getProfileLabel(record.profile)}</Tag>,
    },
    {
      title: "状态",
      key: "enabled",
      width: 90,
      render: (_, record) => (
        <Switch
          size="small"
          checked={record.enabled}
          onChange={(checked) =>
            setModels((current) =>
              current.map((m) => (m.workflow_id === record.workflow_id ? { ...m, enabled: checked } : m)),
            )
          }
        />
      ),
    },
    {
      title: "默认模型",
      key: "is_default",
      width: 100,
      render: (_, record) => (
        <Radio checked={record.is_default} onClick={() => handleSetDefault(record)}>
          默认
        </Radio>
      ),
    },
  ]

  const loadData = useCallback(async () => {
    try {
      const [cfg, modelsData] = await Promise.all([
        requestJson<GrsProviderConfig>("/api/admin/providers/grs"),
        requestJson<GrsCatalogPayload>("/api/admin/providers/grs/models"),
      ])
      setConfig(cfg)
      setEnabled(cfg.enabled)
      setBaseUrl(cfg.base_url)
      // 当前 API 无 max_storyboard_concurrency 字段，保持默认值 5（提交时略去）。
      setModels(modelsData.models)
      setProfiles(modelsData.profiles)
    } catch (err) {
      setErrorMsg(director2ErrorDetail(err, "加载 GRS 配置失败"))
    }
  }, [])

  async function handleSave() {
    setErrorMsg(null)
    setSaving(true)
    try {
      // 当前 API（GrsProviderUpdateRequest）仅接收 enabled/base_url/api_key，
      // max_storyboard_concurrency 略去不提交。
      const updated = await requestJson<GrsProviderConfig>(
        "/api/admin/providers/grs",
        jsonMutation(csrfToken, {
          enabled,
          base_url: baseUrl,
          api_key: apiKey || null,
        }, "PUT"),
      )
      setConfig(updated)
      setApiKey("")
      message.success("GRS 配置已保存")
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
      const updated = await requestJson<GrsProviderConfig>(
        "/api/admin/providers/grs/test",
        jsonMutation(csrfToken, {
          base_url: baseUrl,
          api_key: apiKey || null,
        }, "POST"),
      )
      setConfig(updated)
      message.success(`连接测试成功，当前点数: ${updated.last_balance}`)
    } catch (err) {
      setErrorMsg(director2ErrorDetail(err, "测试失败"))
      await loadData()
    } finally {
      setTesting(false)
    }
  }

  async function handleRefreshBalance() {
    setRefreshingBalance(true)
    try {
      const res = await requestJson<GrsBalanceResult>(
        "/api/admin/providers/grs/balance",
        jsonMutation(csrfToken, undefined, "POST"),
      )
      setConfig((prev) => (prev ? { ...prev, last_balance: res.credits, last_balance_at: res.queried_at } : prev))
      message.success(`余额已更新: ${res.credits} 点`)
    } catch (err) {
      message.error(director2ErrorDetail(err, "刷新余额失败"))
    } finally {
      setRefreshingBalance(false)
    }
  }

  function handleSetDefault(record: GrsImageModel) {
    setModels((current) =>
      current.map((m) => ({ ...m, is_default: m.workflow_id === record.workflow_id })),
    )
  }

  async function handleSaveModels() {
    setSavingModels(true)
    try {
      const res = await requestJson<GrsCatalogPayload>(
        "/api/admin/providers/grs/models",
        jsonMutation(csrfToken, { models }, "PUT"),
      )
      setModels(res.models)
      message.success("生图模型配置已保存")
    } catch (err) {
      message.error(director2ErrorDetail(err, "模型更新失败"))
    } finally {
      setSavingModels(false)
    }
  }

  async function handleCreateModel() {
    if (!newModel.provider_model || !newModel.display_name) {
      message.warning("请填写模型标识和显示名称")
      return
    }
    try {
      const res = await requestJson<GrsCatalogPayload>(
        "/api/admin/providers/grs/models",
        jsonMutation(csrfToken, newModel, "POST"),
      )
      setModels(res.models)
      setAddModalVisible(false)
      setNewModel({ provider_model: "", display_name: "", profile: "nano_banana", description: "" })
      message.success("模型已添加并保存")
    } catch (err) {
      message.error(director2ErrorDetail(err, "创建模型失败"))
    }
  }

  useEffect(() => {
    void loadData()
  }, [loadData])

  return (
    <div className="d2-grs-settings grs-settings-card">
      <div className="card-header">
        <div className="icon-badge grs-badge">
          <Cloud size={22} />
        </div>
        <div>
          <h2 className="title">GRS 极速生图供应商</h2>
          <p className="desc">
            提供 NanoBanana、FLUX 等极速画质大模型，用于人物、场景与分镜资产快速生成。
          </p>
        </div>
      </div>

      <div className="card-body">
        {/* 基础配置 */}
        <div className="settings-grid">
          <div className="form-col">
            <div className="form-item row-item">
              <div>
                <span className="form-label">启用 GRS 服务</span>
                <p className="form-sub">开启后系统可调用 GRS 进行云端文生图与图生图</p>
              </div>
              <Switch checked={enabled} onChange={setEnabled} />
            </div>

            <div className="form-item">
              <label className="form-label">Base URL (API 服务地址)</label>
              <Input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://grsai.dakka.com.cn"
              />
            </div>

            <div className="form-item">
              <label className="form-label">API Key / Token</label>
              <Input.Password
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={
                  config?.has_api_key ? config.api_key_masked || "已配置密钥 (留空保持不变)" : "请输入 GRS API Key"
                }
              />
              {config?.has_api_key ? (
                <span className="help-text text-success">已安全加密存储，再次保存如留空则保留原密钥。</span>
              ) : null}
            </div>

            <div className="form-item">
              <label className="form-label">分镜生图最大并发数</label>
              <InputNumber
                value={maxStoryboardConcurrency}
                onChange={(value) => setMaxStoryboardConcurrency(value)}
                min={1}
                max={20}
                precision={0}
              />
              <span className="help-text">草图和渲染图共用该并发上限，默认 5。</span>
            </div>

            {errorMsg ? (
              <div className="form-item">
                <Alert type="error" showIcon message={errorMsg} />
              </div>
            ) : null}

            <div className="form-actions">
              <Button type="primary" loading={saving} onClick={handleSave}>
                保存供应商配置
              </Button>
              <Button loading={testing} onClick={handleTest} icon={<CheckCircle2 size={15} />}>
                测试连接
              </Button>
            </div>
          </div>

          {/* 余额与状态面板 */}
          <div className="status-col">
            <div className="balance-panel">
              <div className="panel-header">
                <span className="panel-title">账户点数余额</span>
                <Button
                  type="link"
                  size="small"
                  loading={refreshingBalance}
                  onClick={handleRefreshBalance}
                  icon={<RefreshCw size={13} />}
                >
                  刷新
                </Button>
              </div>
              <div className="balance-value">
                {config?.last_balance != null ? config.last_balance.toLocaleString() : "--"}
                <span className="balance-unit">点</span>
              </div>
              <p className="panel-time">
                {config?.last_balance_at
                  ? `更新于 ${new Date(config.last_balance_at).toLocaleTimeString()}`
                  : "点击测试或刷新获取"}
              </p>
            </div>

            <div className="status-panel mt-3">
              <p className="status-title">连通性状态</p>
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
          </div>
        </div>

        {/* 生图模型目录 */}
        <div className="models-section">
          <div className="section-header">
            <div>
              <h3 className="section-title">生图模型目录</h3>
              <p className="section-desc">管理可用于创作台画面的生图模型通道与默认选择。</p>
            </div>
            <div className="section-actions">
              <Button type="primary" ghost onClick={() => setAddModalVisible(true)} icon={<Plus size={15} />}>
                新增模型
              </Button>
              <Button loading={savingModels} onClick={handleSaveModels}>
                保存模型调整
              </Button>
            </div>
          </div>

          <Table
            className="models-table"
            dataSource={models}
            columns={columns}
            rowKey="workflow_id"
            pagination={false}
            size="middle"
          />
        </div>
      </div>

      {/* 新增模型弹窗 */}
      <Modal
        className="d2-grs-settings"
        open={addModalVisible}
        title="新增 GRS 生图模型"
        okText="确认添加并保存"
        cancelText="取消"
        onOk={handleCreateModel}
        onCancel={() => setAddModalVisible(false)}
      >
        <div className="modal-form">
          <div className="form-item">
            <label className="form-label">模型标识 (Provider Model)</label>
            <Input
              value={newModel.provider_model}
              onChange={(event) => setNewModel({ ...newModel, provider_model: event.target.value })}
              placeholder="例如：flux-dev, gpt-image-3"
            />
          </div>
          <div className="form-item">
            <label className="form-label">显示名称</label>
            <Input
              value={newModel.display_name}
              onChange={(event) => setNewModel({ ...newModel, display_name: event.target.value })}
              placeholder="例如：FLUX 高清真实写实"
            />
          </div>
          <div className="form-item">
            <label className="form-label">模型类型 (Profile)</label>
            <Select
              value={newModel.profile}
              options={profiles}
              onChange={(value) => setNewModel({ ...newModel, profile: value })}
            />
          </div>
          <div className="form-item">
            <label className="form-label">模型说明</label>
            <Input
              value={newModel.description}
              onChange={(event) => setNewModel({ ...newModel, description: event.target.value })}
              placeholder="用途或特点说明"
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}
