<template>
  <div class="grs-settings-card">
    <div class="card-header">
      <div class="icon-badge grs-badge">
        <Cloud :size="22" />
      </div>
      <div>
        <h2 class="title">GRS 极速生图供应商</h2>
        <p class="desc">
          提供 NanoBanana、FLUX 等极速画质大模型，用于人物、场景与分镜资产快速生成。
        </p>
      </div>
    </div>

    <div class="card-body">
      <!-- 基础配置 -->
      <div class="settings-grid">
        <div class="form-col">
          <div class="form-item row-item">
            <div>
              <span class="form-label">启用 GRS 服务</span>
              <p class="form-sub">开启后系统可调用 GRS 进行云端文生图与图生图</p>
            </div>
            <a-switch v-model:checked="enabled" />
          </div>

          <div class="form-item">
            <label class="form-label">Base URL (API 服务地址)</label>
            <a-input v-model:value="baseUrl" placeholder="https://grsai.dakka.com.cn" />
          </div>

          <div class="form-item">
            <label class="form-label">API Key / Token</label>
            <a-input-password
              v-model:value="apiKey"
              :placeholder="config?.has_api_key ? (config.api_key_masked || '已配置密钥 (留空保持不变)') : '请输入 GRS API Key'"
            />
            <span v-if="config?.has_api_key" class="help-text text-success">
              已安全加密存储，再次保存如留空则保留原密钥。
            </span>
          </div>

          <div class="form-item">
            <label class="form-label">生图最大并发数</label>
            <a-input-number v-model:value="maxStoryboardConcurrency" :min="1" :max="20" :precision="0" />
            <span class="help-text">角色头像、造型图与分镜草图/渲染图共用该上限，默认 5。</span>
          </div>

          <div v-if="errorMsg" class="form-item">
            <a-alert type="error" show-icon :message="errorMsg" />
          </div>

          <div class="form-actions">
            <a-button type="primary" :loading="saving" @click="handleSave">
              保存供应商配置
            </a-button>
            <a-button :loading="testing" @click="handleTest">
              <template #icon><CheckCircle2 :size="15" /></template>
              测试连接
            </a-button>
          </div>
        </div>

        <!-- 余额与状态面板 -->
        <div class="status-col">
          <div class="balance-panel">
            <div class="panel-header">
              <span class="panel-title">账户点数余额</span>
              <a-button type="link" size="small" :loading="refreshingBalance" @click="handleRefreshBalance">
                <template #icon><RefreshCw :size="13" /></template>
                刷新
              </a-button>
            </div>
            <div class="balance-value">
              {{ config?.last_balance != null ? config.last_balance.toLocaleString() : '--' }}
              <span class="balance-unit">点</span>
            </div>
            <p class="panel-time">
              {{ config?.last_balance_at ? `更新于 ${new Date(config.last_balance_at).toLocaleTimeString()}` : '点击测试或刷新获取' }}
            </p>
          </div>

          <div class="status-panel mt-3">
            <p class="status-title">连通性状态</p>
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
        </div>
      </div>

      <!-- 生图模型目录 -->
      <div class="models-section">
        <div class="section-header">
          <div>
            <h3 class="section-title">生图模型目录</h3>
            <p class="section-desc">管理可用于创作台画面的生图模型通道与默认选择。</p>
          </div>
          <div class="section-actions">
            <a-button type="primary" ghost @click="addModalVisible = true">
              <template #icon><Plus :size="15" /></template>
              新增模型
            </a-button>
            <a-button :loading="savingModels" @click="handleSaveModels">
              保存模型调整
            </a-button>
          </div>
        </div>

        <a-table
          :data-source="models"
          :columns="columns"
          row-key="workflow_id"
          :pagination="false"
          size="middle"
          class="models-table"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'display_name'">
              <div>
                <span class="font-medium">{{ record.display_name }}</span>
                <p class="text-xs text-gray-500 m-0">{{ record.provider_model }}</p>
              </div>
            </template>
            <template v-else-if="column.key === 'profile'">
              <a-tag color="purple">{{ getProfileLabel(record.profile) }}</a-tag>
            </template>
            <template v-else-if="column.key === 'enabled'">
              <a-switch v-model:checked="record.enabled" size="small" />
            </template>
            <template v-else-if="column.key === 'is_default'">
              <a-radio :checked="record.is_default" @click="handleSetDefault(record)">
                默认
              </a-radio>
            </template>
          </template>
        </a-table>
      </div>
    </div>

    <!-- 新增模型弹窗 -->
    <a-modal
      v-model:open="addModalVisible"
      title="新增 GRS 生图模型"
      ok-text="确认添加并保存"
      cancel-text="取消"
      @ok="handleCreateModel"
    >
      <div class="modal-form">
        <div class="form-item">
          <label class="form-label">模型标识 (Provider Model)</label>
          <a-input v-model:value="newModel.provider_model" placeholder="例如：flux-dev, gpt-image-3" />
        </div>
        <div class="form-item">
          <label class="form-label">显示名称</label>
          <a-input v-model:value="newModel.display_name" placeholder="例如：FLUX 高清真实写实" />
        </div>
        <div class="form-item">
          <label class="form-label">模型类型 (Profile)</label>
          <a-select v-model:value="newModel.profile" :options="profiles" />
        </div>
        <div class="form-item">
          <label class="form-label">模型说明</label>
          <a-input v-model:value="newModel.description" placeholder="用途或特点说明" />
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { Cloud, CheckCircle2, RefreshCw, Plus } from 'lucide-vue-next'
import {
  getGrsConfig,
  updateGrsConfig,
  testGrsConnection,
  queryGrsBalance,
  getGrsModels,
  updateGrsModels,
  createGrsModel,
} from '../../api/providers'

const config = ref(null)
const enabled = ref(false)
const baseUrl = ref('https://grsai.dakka.com.cn')
const apiKey = ref('')
const maxStoryboardConcurrency = ref(5)
const models = ref([])
const profiles = ref([])

const saving = ref(false)
const testing = ref(false)
const refreshingBalance = ref(false)
const savingModels = ref(false)
const errorMsg = ref(null)

const addModalVisible = ref(false)
const newModel = ref({
  provider_model: '',
  display_name: '',
  profile: 'nano_banana',
  description: '',
})

const columns = [
  { title: '模型名称', key: 'display_name' },
  { title: '规格类型', key: 'profile', width: 220 },
  { title: '状态', key: 'enabled', width: 90 },
  { title: '默认模型', key: 'is_default', width: 100 },
]

const statusClass = computed(() => {
  if (config.value?.last_test_status === 'success') return 'status-success'
  if (config.value?.last_test_status === 'failed') return 'status-failed'
  return 'status-idle'
})

const statusLabel = computed(() => {
  if (config.value?.last_test_status === 'success') return '已连通'
  if (config.value?.last_test_status === 'failed') return '连接失败'
  return '尚未测试'
})

const getProfileLabel = (p) => {
  const item = profiles.value.find(i => i.value === p)
  return item?.label || p
}

const loadData = async () => {
  try {
    const [cfg, modelsData] = await Promise.all([getGrsConfig(), getGrsModels()])
    config.value = cfg
    enabled.value = cfg.enabled
    baseUrl.value = cfg.base_url
    maxStoryboardConcurrency.value = cfg.max_storyboard_concurrency || 5
    models.value = modelsData.models
    profiles.value = modelsData.profiles
  } catch (err) {
    errorMsg.value = err?.response?.data?.detail || err.message || '加载 GRS 配置失败'
  }
}

const handleSave = async () => {
  errorMsg.value = null
  saving.value = true
  try {
    const updated = await updateGrsConfig({
      enabled: enabled.value,
      base_url: baseUrl.value,
      api_key: apiKey.value || null,
      max_storyboard_concurrency: maxStoryboardConcurrency.value,
    })
    config.value = updated
    apiKey.value = ''
    message.success('GRS 配置已保存')
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
    const updated = await testGrsConnection({
      base_url: baseUrl.value,
      api_key: apiKey.value || null,
    })
    config.value = updated
    message.success(`连接测试成功，当前点数: ${updated.last_balance}`)
  } catch (err) {
    errorMsg.value = err?.response?.data?.detail || err.message || '测试失败'
    await loadData()
  } finally {
    testing.value = false
  }
}

const handleRefreshBalance = async () => {
  refreshingBalance.value = true
  try {
    const res = await queryGrsBalance()
    if (res.error) {
      message.error(res.error)
    } else {
      if (config.value) {
        config.value.last_balance = res.credits
        config.value.last_balance_at = res.queried_at
      }
      message.success(`余额已更新: ${res.credits} 点`)
    }
  } catch (err) {
    message.error(err?.response?.data?.detail || err.message || '刷新余额失败')
  } finally {
    refreshingBalance.value = false
  }
}

const handleSetDefault = (record) => {
  models.value.forEach(m => {
    m.is_default = m.workflow_id === record.workflow_id
  })
}

const handleSaveModels = async () => {
  savingModels.value = true
  try {
    const res = await updateGrsModels(models.value)
    models.value = res.models
    message.success('生图模型配置已保存')
  } catch (err) {
    message.error(err?.response?.data?.detail || err.message || '模型更新失败')
  } finally {
    savingModels.value = false
  }
}

const handleCreateModel = async () => {
  if (!newModel.value.provider_model || !newModel.value.display_name) {
    message.warning('请填写模型标识和显示名称')
    return
  }
  try {
    const res = await createGrsModel(newModel.value)
    models.value = res.models
    addModalVisible.value = false
    newModel.value = { provider_model: '', display_name: '', profile: 'nano_banana', description: '' }
    message.success('模型已添加并保存')
  } catch (err) {
    message.error(err?.response?.data?.detail || err.message || '创建模型失败')
  }
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.grs-settings-card {
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
  margin-top: 20px;
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

.grs-badge {
  background: rgba(14, 165, 233, 0.1);
  color: #0ea5e9;
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
}

.text-success {
  color: #059669;
}

.form-actions {
  display: flex;
  gap: 12px;
  padding-top: 8px;
}

.balance-panel {
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.05), rgba(99, 102, 241, 0.05));
  border: 1px solid rgba(14, 165, 233, 0.15);
  border-radius: 12px;
  padding: 16px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-title {
  font-size: 12px;
  font-weight: 600;
  color: #0284c7;
}

.balance-value {
  font-size: 28px;
  font-weight: 700;
  color: #0369a1;
  margin: 8px 0 4px;
}

.balance-unit {
  font-size: 14px;
  font-weight: normal;
  color: #64748b;
  margin-left: 4px;
}

.panel-time {
  font-size: 11px;
  color: #94a3b8;
  margin: 0;
}

.status-panel {
  background: #f9fafb;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px;
  padding: 16px;
}

.status-title {
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

.models-section {
  margin-top: 32px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  padding-top: 24px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding: 0 8px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: #111827;
  margin: 0;
}

.section-desc {
  font-size: 12px;
  color: #6b7280;
  margin: 2px 0 0;
}

.section-actions {
  display: flex;
  gap: 10px;
}

.models-table {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid rgba(0, 0, 0, 0.06);
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-top: 12px;
}

.mt-3 {
  margin-top: 12px;
}
</style>
