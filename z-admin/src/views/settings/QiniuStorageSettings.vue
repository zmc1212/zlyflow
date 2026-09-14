<template>
  <div class="qiniu-settings-card">
    <div class="card-header">
      <div class="icon-badge qiniu-badge">
        <CloudCog :size="22" />
      </div>
      <div>
        <h2 class="title">七牛云对象存储 (Kodo)</h2>
        <p class="desc">
          启用后，创作台生成的所有高质量原图与高清成片将自动同步至云端对象存储，并生成高速 CDN 分发链接。
        </p>
      </div>
    </div>

    <div class="card-body">
      <div class="settings-grid">
        <div class="form-col">
          <!-- 启用开关 -->
          <div class="form-item row-item">
            <div>
              <span class="form-label">启用七牛云媒体存储</span>
              <p class="form-sub">开启后媒体资源由云端托管，关闭则保留本地输出</p>
            </div>
            <a-switch v-model:checked="enabled" />
          </div>

          <!-- Access Key -->
          <div class="form-item">
            <label class="form-label">Access Key (AK)</label>
            <a-input-password
              v-model:value="accessKey"
              :placeholder="config?.has_access_key ? '已配置 Access Key (留空保持不变)' : '请输入七牛云 AK'"
            />
          </div>

          <!-- Secret Key -->
          <div class="form-item">
            <label class="form-label">Secret Key (SK)</label>
            <a-input-password
              v-model:value="secretKey"
              :placeholder="config?.has_secret_key ? '已配置 Secret Key (留空保持不变)' : '请输入七牛云 SK'"
            />
          </div>

          <!-- Bucket & Region -->
          <div class="grid-row">
            <div class="form-item">
              <label class="form-label">存储空间名称 (Bucket)</label>
              <a-input v-model:value="bucket" placeholder="例如：my-ai-media" />
            </div>
            <div class="form-item">
              <label class="form-label">存储区域 (Region)</label>
              <a-select v-model:value="region" :options="regionOptions" />
            </div>
          </div>

          <!-- CDN Domain -->
          <div class="form-item">
            <label class="form-label">访问域名 (带 https:// 前缀)</label>
            <a-input v-model:value="domain" placeholder="https://cdn.your-domain.com" />
            <span class="help-text">
              七牛云空间绑定的自定义 CDN 域名或测试域名，必须带协议头且末尾不加斜杠。
            </span>
          </div>

          <!-- Object Prefix -->
          <div class="form-item">
            <label class="form-label">资源前缀目录 (Object Prefix)</label>
            <a-input v-model:value="objectPrefix" placeholder="zly-ai-video-studio/" />
          </div>

          <div v-if="errorMsg" class="form-item">
            <a-alert type="error" show-icon :message="errorMsg" />
          </div>

          <div class="form-actions">
            <a-button type="primary" :loading="saving" @click="handleSave">
              保存存储配置
            </a-button>
            <a-button :loading="testing" @click="handleTest">
              <template #icon><CheckCircle2 :size="15" /></template>
              测试读写连接
            </a-button>
          </div>
        </div>

        <!-- 状态与提示面板 -->
        <div class="status-col">
          <div class="status-panel">
            <p class="status-title">存储读写验证</p>
            <p class="status-badge" :class="statusClass">
              <span class="status-dot"></span>
              {{ statusLabel }}
            </p>
            <p v-if="config?.last_test_message" class="status-msg">
              {{ config.last_test_message }}
            </p>
            <p class="status-time">
              {{ config?.last_test_at ? new Date(config.last_test_at).toLocaleString('zh-CN', { hour12: false }) : '未执行测试' }}
            </p>
          </div>

          <div class="tips-panel mt-3">
            <p class="tips-title">存储使用说明</p>
            <ul class="tips-list">
              <li>AK 与 SK 在服务器端使用对称密钥 <b>加密存储</b>，绝不泄露明文。</li>
              <li>测试连接会自动上传一个探测文件并立刻删除，校验完整的写与删权限。</li>
              <li>如需测试域名，可在七牛云控制台进入对应存储空间「空间概览」中查看。</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { CloudCog, CheckCircle2 } from 'lucide-vue-next'
import {
  getQiniuConfig,
  updateQiniuConfig,
  testQiniuConnection,
} from '../../api/providers'

const regionOptions = [
  { value: 'z0', label: '华东 (z0)' },
  { value: 'cn-east-2', label: '华东-浙江 (cn-east-2)' },
  { value: 'z1', label: '华北 (z1)' },
  { value: 'z2', label: '华南 (z2)' },
  { value: 'na0', label: '北美 (na0)' },
  { value: 'as0', label: '新加坡 (as0)' },
]

const config = ref(null)
const enabled = ref(false)
const accessKey = ref('')
const secretKey = ref('')
const bucket = ref('')
const region = ref('z0')
const domain = ref('')
const objectPrefix = ref('zly-ai-video-studio/')

const saving = ref(false)
const testing = ref(false)
const errorMsg = ref(null)

const statusClass = computed(() => {
  if (config.value?.last_test_status === 'success') return 'status-success'
  if (config.value?.last_test_status === 'failed') return 'status-failed'
  return 'status-idle'
})

const statusLabel = computed(() => {
  if (config.value?.last_test_status === 'success') return '读写正常'
  if (config.value?.last_test_status === 'failed') return '连接失败'
  return '尚未测试'
})

const loadConfig = async () => {
  try {
    const data = await getQiniuConfig()
    config.value = data
    enabled.value = data.enabled
    bucket.value = data.bucket
    region.value = data.region || 'z0'
    domain.value = data.domain
    objectPrefix.value = data.object_prefix || 'zly-ai-video-studio/'
  } catch (err) {
    errorMsg.value = err?.response?.data?.detail || err.message || '加载存储配置失败'
  }
}

const handleSave = async () => {
  errorMsg.value = null
  saving.value = true
  try {
    const updated = await updateQiniuConfig({
      enabled: enabled.value,
      access_key: accessKey.value || null,
      secret_key: secretKey.value || null,
      bucket: bucket.value,
      region: region.value,
      domain: domain.value,
      object_prefix: objectPrefix.value,
    })
    config.value = updated
    accessKey.value = ''
    secretKey.value = ''
    message.success('七牛云存储配置已保存')
  } catch (err) {
    errorMsg.value = err?.response?.data?.detail || err.message || '保存失败'
  } finally {
    saving.value = false
  }
}

const handleTest = async () => {
  errorMsg.value = null
  testing.value = true
  try {
    const updated = await testQiniuConnection({
      access_key: accessKey.value || null,
      secret_key: secretKey.value || null,
      bucket: bucket.value,
      region: region.value,
      domain: domain.value,
      object_prefix: objectPrefix.value,
    })
    config.value = updated
    message.success('七牛云存储读写测试成功！')
  } catch (err) {
    errorMsg.value = err?.response?.data?.detail || err.message || '测试失败'
    await loadConfig()
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.qiniu-settings-card {
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.card-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  padding-bottom: 20px;
}

.icon-badge {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.qiniu-badge {
  background: rgba(6, 182, 212, 0.1);
  color: #0891b2;
}

.title {
  font-size: 16px;
  font-weight: 600;
  color: #111827;
  margin: 0;
}

.desc {
  margin: 4px 0 0;
  font-size: 13px;
  line-height: 20px;
  color: #4b5563;
}

.card-body {
  margin-top: 20px;
}

.settings-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 24px;
}

@media (max-width: 768px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}

.form-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.grid-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.row-item {
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
}

.form-label {
  font-size: 13px;
  font-weight: 500;
  color: #4b5563;
}

.form-sub {
  font-size: 12px;
  color: #9ca3af;
  margin: 2px 0 0;
}

.help-text {
  font-size: 12px;
  color: #6b7280;
}

.form-actions {
  display: flex;
  gap: 12px;
  padding-top: 8px;
}

.status-panel, .tips-panel {
  background: #f9fafb;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px;
  padding: 16px;
}

.status-title, .tips-title {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #6b7280;
  margin: 0 0 12px;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.status-success {
  color: #059669;
}

.status-failed {
  color: #dc2626;
}

.status-idle {
  color: #6b7280;
}

.status-msg {
  font-size: 12px;
  line-height: 18px;
  color: #4b5563;
  margin: 0 0 10px;
}

.status-time {
  font-size: 12px;
  color: #9ca3af;
  margin: 0;
}

.tips-list {
  margin: 0;
  padding-left: 16px;
  font-size: 12px;
  line-height: 20px;
  color: #6b7280;
}

.mt-3 {
  margin-top: 12px;
}
</style>
