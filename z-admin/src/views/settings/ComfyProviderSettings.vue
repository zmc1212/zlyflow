<template>
  <div class="comfy-settings-card">
    <div class="card-header">
      <div class="icon-badge comfy-badge">
        <MonitorPlay :size="22" />
      </div>
      <div>
        <h2 class="title">ComfyUI 视频后端</h2>
        <p class="desc">
          工作台只连接一个 ComfyUI 实例。保存后立即对后续视频任务生效，无需重启。宿主机浏览器直连交付使用本机
          <code class="code-tag">http://127.0.0.1:8188/view</code>。
        </p>
      </div>
    </div>

    <div class="card-body">
      <div class="form-col">
        <div class="form-item">
          <label class="form-label">常用预设地址</label>
          <a-select
            v-model:value="selectedPreset"
            style="width: 100%"
            :options="urlPresets"
            @change="handlePresetChange"
          />
        </div>

        <div class="form-item">
          <label class="form-label">ComfyUI 连接地址</label>
          <a-input
            v-model:value="baseUrl"
            placeholder="http://127.0.0.1:8188"
            allow-clear
          />
          <span v-if="config?.env_default" class="help-text">
            默认配置值：{{ config.env_default }}
          </span>
        </div>

        <div v-if="errorMsg" class="form-item">
          <a-alert type="error" show-icon :message="errorMsg" />
        </div>

        <div class="form-actions">
          <a-button type="primary" :loading="saving" @click="handleSave">
            保存配置
          </a-button>
          <a-button :loading="testing" @click="handleTest">
            <template #icon><CheckCircle2 :size="15" /></template>
            测试连接
          </a-button>
        </div>
      </div>

      <div class="status-col">
        <div class="status-panel">
          <p class="status-title">最近连接状态</p>
          <p class="status-badge" :class="statusClass">
            <span class="status-dot"></span>
            {{ statusLabel }}
          </p>
          <p v-if="config?.last_test_message" class="status-msg">
            {{ config.last_test_message }}
          </p>
          <p class="status-time">
            {{ config?.last_test_at ? new Date(config.last_test_at).toLocaleString('zh-CN', { hour12: false }) : '保存或测试后记录结果' }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { MonitorPlay, CheckCircle2 } from 'lucide-vue-next'
import { getComfyConfig, updateComfyConfig, testComfyConnection } from '../../api/providers'

const urlPresets = [
  { label: '本机默认 8188', value: 'http://127.0.0.1:8188' },
  { label: '服务器 FRP 18188', value: 'http://127.0.0.1:18188' },
  { label: '自定义地址', value: 'custom' },
]

const config = ref(null)
const baseUrl = ref('http://127.0.0.1:8188')
const selectedPreset = ref('http://127.0.0.1:8188')
const saving = ref(false)
const testing = ref(false)
const errorMsg = ref(null)

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

const loadConfig = async () => {
  try {
    const data = await getComfyConfig()
    config.value = data
    baseUrl.value = data.base_url
    if (urlPresets.some(p => p.value === data.base_url)) {
      selectedPreset.value = data.base_url
    } else {
      selectedPreset.value = 'custom'
    }
  } catch (err) {
    errorMsg.value = err?.response?.data?.detail || err.message || '加载 ComfyUI 配置失败'
  }
}

const handlePresetChange = (val) => {
  if (val !== 'custom') {
    baseUrl.value = val
  }
}

const handleSave = async () => {
  errorMsg.value = null
  saving.value = true
  try {
    const updated = await updateComfyConfig(baseUrl.value)
    config.value = updated
    message.success('ComfyUI 连接地址已保存，后续视频任务立即使用新地址')
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
    const updated = await testComfyConnection(baseUrl.value)
    config.value = updated
    message.success('ComfyUI 连接测试成功')
  } catch (err) {
    errorMsg.value = err?.response?.data?.detail || err.message || '连接测试失败'
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
.comfy-settings-card {
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

.comfy-badge {
  background: rgba(112, 71, 246, 0.1);
  color: #7047f6;
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

.code-tag {
  background: #f3f4f6;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  color: #111827;
}

.card-body {
  margin-top: 20px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 24px;
}

@media (max-width: 768px) {
  .card-body {
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

.form-label {
  font-size: 13px;
  font-weight: 500;
  color: #4b5563;
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
</style>
