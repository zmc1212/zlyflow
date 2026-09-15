// 七牛云对象存储设置卡 —— 逐行复刻自 dev0914 z-admin/src/views/settings/QiniuStorageSettings.vue
// Vue → React 对应：ref→useState、computed→渲染期变量、onMounted→useEffect、v-model→受控值；
// ant-design-vue 组件 → antd 同名组件；数据层走工作台 /api/admin 体系（requestJson + jsonMutation），
// 错误提示 → director2ErrorDetail。
import { useCallback, useEffect, useState } from "react"
import { Alert, Button, Input, Select, Switch, message } from "antd"
import { CheckCircle2, CloudCog } from "lucide-react"
import { jsonMutation, requestJson } from "../../api"
import { director2ErrorDetail } from "../api"
import "./qiniu-provider.css"

// 对应后端 QiniuProviderResponse（backend/app/models.py）
interface QiniuProviderConfig {
  enabled: boolean
  bucket: string
  region: string
  domain: string
  object_prefix: string
  has_access_key: boolean
  has_secret_key: boolean
  credential_ready: boolean
  available: boolean
  last_test_status: string | null
  last_test_message: string | null
  last_test_at: string | null
}

const regionOptions = [
  { value: "z0", label: "华东 (z0)" },
  { value: "cn-east-2", label: "华东-浙江 (cn-east-2)" },
  { value: "z1", label: "华北 (z1)" },
  { value: "z2", label: "华南 (z2)" },
  { value: "na0", label: "北美 (na0)" },
  { value: "as0", label: "新加坡 (as0)" },
]

export default function QiniuStorageSettings({ csrfToken }: { csrfToken: string }) {
  const [config, setConfig] = useState<QiniuProviderConfig | null>(null)
  const [enabled, setEnabled] = useState(false)
  const [accessKey, setAccessKey] = useState("")
  const [secretKey, setSecretKey] = useState("")
  const [bucket, setBucket] = useState("")
  const [region, setRegion] = useState("z0")
  const [domain, setDomain] = useState("")
  const [objectPrefix, setObjectPrefix] = useState("zly-ai-video-studio/")

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
      ? "读写正常"
      : config?.last_test_status === "failed"
        ? "连接失败"
        : "尚未测试"

  const loadConfig = useCallback(async () => {
    try {
      const data = await requestJson<QiniuProviderConfig>("/api/admin/providers/qiniu")
      setConfig(data)
      setEnabled(data.enabled)
      setBucket(data.bucket)
      setRegion(data.region || "z0")
      setDomain(data.domain)
      setObjectPrefix(data.object_prefix || "zly-ai-video-studio/")
    } catch (err) {
      setErrorMsg(director2ErrorDetail(err, "加载存储配置失败"))
    }
  }, [])

  async function handleSave() {
    setErrorMsg(null)
    setSaving(true)
    try {
      const updated = await requestJson<QiniuProviderConfig>(
        "/api/admin/providers/qiniu",
        jsonMutation(csrfToken, {
          enabled,
          access_key: accessKey || null,
          secret_key: secretKey || null,
          bucket,
          region,
          domain,
          object_prefix: objectPrefix,
        }, "PUT"),
      )
      setConfig(updated)
      setAccessKey("")
      setSecretKey("")
      message.success("七牛云存储配置已保存")
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
      const updated = await requestJson<QiniuProviderConfig>(
        "/api/admin/providers/qiniu/test",
        jsonMutation(csrfToken, {
          access_key: accessKey || null,
          secret_key: secretKey || null,
          bucket,
          region,
          domain,
          object_prefix: objectPrefix,
        }, "POST"),
      )
      setConfig(updated)
      message.success("七牛云存储读写测试成功！")
    } catch (err) {
      setErrorMsg(director2ErrorDetail(err, "测试失败"))
      await loadConfig()
    } finally {
      setTesting(false)
    }
  }

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  return (
    <div className="d2-qiniu-settings qiniu-settings-card">
      <div className="card-header">
        <div className="icon-badge qiniu-badge">
          <CloudCog size={22} />
        </div>
        <div>
          <h2 className="title">七牛云对象存储 (Kodo)</h2>
          <p className="desc">
            启用后，创作台生成的所有高质量原图与高清成片将自动同步至云端对象存储，并生成高速 CDN 分发链接。
          </p>
        </div>
      </div>

      <div className="card-body">
        <div className="settings-grid">
          <div className="form-col">
            {/* 启用开关 */}
            <div className="form-item row-item">
              <div>
                <span className="form-label">启用七牛云媒体存储</span>
                <p className="form-sub">开启后媒体资源由云端托管，关闭则保留本地输出</p>
              </div>
              <Switch checked={enabled} onChange={setEnabled} />
            </div>

            {/* Access Key */}
            <div className="form-item">
              <label className="form-label">Access Key (AK)</label>
              <Input.Password
                value={accessKey}
                onChange={(event) => setAccessKey(event.target.value)}
                placeholder={config?.has_access_key ? "已配置 Access Key (留空保持不变)" : "请输入七牛云 AK"}
              />
            </div>

            {/* Secret Key */}
            <div className="form-item">
              <label className="form-label">Secret Key (SK)</label>
              <Input.Password
                value={secretKey}
                onChange={(event) => setSecretKey(event.target.value)}
                placeholder={config?.has_secret_key ? "已配置 Secret Key (留空保持不变)" : "请输入七牛云 SK"}
              />
            </div>

            {/* Bucket & Region */}
            <div className="grid-row">
              <div className="form-item">
                <label className="form-label">存储空间名称 (Bucket)</label>
                <Input
                  value={bucket}
                  onChange={(event) => setBucket(event.target.value)}
                  placeholder="例如：my-ai-media"
                />
              </div>
              <div className="form-item">
                <label className="form-label">存储区域 (Region)</label>
                <Select value={region} options={regionOptions} onChange={setRegion} />
              </div>
            </div>

            {/* CDN Domain */}
            <div className="form-item">
              <label className="form-label">访问域名 (带 https:// 前缀)</label>
              <Input
                value={domain}
                onChange={(event) => setDomain(event.target.value)}
                placeholder="https://cdn.your-domain.com"
              />
              <span className="help-text">
                七牛云空间绑定的自定义 CDN 域名或测试域名，必须带协议头且末尾不加斜杠。
              </span>
            </div>

            {/* Object Prefix */}
            <div className="form-item">
              <label className="form-label">资源前缀目录 (Object Prefix)</label>
              <Input
                value={objectPrefix}
                onChange={(event) => setObjectPrefix(event.target.value)}
                placeholder="zly-ai-video-studio/"
              />
            </div>

            {errorMsg ? (
              <div className="form-item">
                <Alert type="error" showIcon message={errorMsg} />
              </div>
            ) : null}

            <div className="form-actions">
              <Button type="primary" loading={saving} onClick={handleSave}>
                保存存储配置
              </Button>
              <Button loading={testing} onClick={handleTest} icon={<CheckCircle2 size={15} />}>
                测试读写连接
              </Button>
            </div>
          </div>

          {/* 状态与提示面板 */}
          <div className="status-col">
            <div className="status-panel">
              <p className="status-title">存储读写验证</p>
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
              <p className="tips-title">存储使用说明</p>
              <ul className="tips-list">
                <li>
                  AK 与 SK 在服务器端使用对称密钥 <b>加密存储</b>，绝不泄露明文。
                </li>
                <li>测试连接会自动上传一个探测文件并立刻删除，校验完整的写与删权限。</li>
                <li>如需测试域名，可在七牛云控制台进入对应存储空间「空间概览」中查看。</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
