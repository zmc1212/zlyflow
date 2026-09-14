<template>
  <div class="llm-settings-card">
    <div class="card-header">
      <div class="icon-badge llm-badge">
        <Bot :size="22" />
      </div>
      <div>
        <h2 class="title">LLM 大语言模型服务</h2>
        <p class="desc">
          驱动剧本拆解、分镜创作、导演提示词优化与角色分析。兼容所有标准 OpenAI 格式接口。
        </p>
      </div>
    </div>

    <div class="card-body">
      <div class="settings-grid">
        <div class="form-col">
          <!-- 启用开关 -->
          <div class="form-item row-item">
            <div>
              <span class="form-label">启用 LLM 大模型</span>
              <p class="form-sub">关闭后系统将暂停所有大模型分析与提示词生成任务</p>
            </div>
            <a-switch v-model:checked="enabled" />
          </div>

          <!-- 预设厂商选择 -->
          <div class="form-item">
            <label class="form-label">服务商预设方案</label>
            <a-select
              v-model:value="selectedPreset"
              :options="providerPresets.map(p => ({ label: p.label, value: p.value }))"
              @change="handlePresetChange"
            />
          </div>

          <!-- Base URL -->
          <div class="form-item">
            <label class="form-label">Base URL (接口地址)</label>
            <a-input v-model:value="baseUrl" placeholder="https://api-inference.modelscope.cn/v1" />
          </div>

          <!-- Model Name -->
          <div class="form-item">
            <div class="flex justify-between items-center">
              <label class="form-label">模型名称 (Model)</label>
              <a-button type="link" size="small" :loading="fetchingCatalog" @click="handleFetchCatalog">
                <template #icon><RefreshCw :size="12" /></template>
                拉取可用模型
              </a-button>
            </div>
            <a-auto-complete
              v-model:value="model"
              :options="modelOptions"
              placeholder="例如：deepseek-ai/DeepSeek-V4-Flash-0731"
            />
            <!-- 推荐模型快捷填入 -->
            <div v-if="currentPreset?.recommendedModels?.length" class="quick-tags">
              <span class="tags-label">推荐快捷填入：</span>
              <span
                v-for="rm in currentPreset.recommendedModels"
                :key="rm.id"
                class="quick-tag"
                @click="model = rm.id"
              >
                {{ rm.name }}
              </span>
            </div>
          </div>

          <!-- API Key -->
          <div class="form-item">
            <div class="flex justify-between items-center">
              <label class="form-label">API Key / Token</label>
              <a v-if="currentPreset?.docUrl" :href="currentPreset.docUrl" target="_blank" class="doc-link">
                获取 Token <ExternalLink :size="12" />
              </a>
            </div>
            <a-input-password
              v-model:value="apiKey"
              :placeholder="config?.has_api_key ? (config.api_key_masked || '已配置密钥 (留空保持不变)') : '请输入 API Key'"
            />
            <span v-if="config?.has_api_key" class="help-text text-success">
              已加密存储；如不修改 API Key 请保持此输入框留空。
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

        <!-- 状态面板 -->
        <div class="status-col">
          <div class="status-panel">
            <p class="status-title">大模型连通测试</p>
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
            <p class="tips-title">配置提示</p>
            <ul class="tips-list">
              <li>若使用 <b>本地 Ollama</b>，地址填 <code>http://127.0.0.1:11434/v1</code>，密钥可留空或填 <code>ollama</code>。</li>
              <li>通义千问兼容地址：<code>https://dashscope.aliyuncs.com/compatible-mode/v1</code>。</li>
              <li>点击「拉取可用模型」可在线读取服务商支持的模型列表并自动补全。</li>
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
import { Bot, CheckCircle2, RefreshCw, ExternalLink } from 'lucide-vue-next'
import {
  getLlmConfig,
  updateLlmConfig,
  testLlmConnection,
  listLlmModels,
} from '../../api/providers'

const providerPresets = [
  {
    label: 'ModelScope 魔搭社区 (默认推荐)',
    value: 'modelscope',
    baseUrl: 'https://api-inference.modelscope.cn/v1',
    model: 'deepseek-ai/DeepSeek-V4-Flash-0731',
    docUrl: 'https://modelscope.cn/my/access/token',
    recommendedModels: [
      { name: 'DeepSeek-V4-Flash (极速推荐)', id: 'deepseek-ai/DeepSeek-V4-Flash-0731' },
      { name: 'MiniMax-M1-80k', id: 'MiniMax/MiniMax-M1-80k' },
    ],
  },
  {
    label: '阿里云百炼 / 通义千问 (DashScope)',
    value: 'dashscope',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-plus',
    docUrl: 'https://bailian.console.aliyun.com/?apiKey=1',
    recommendedModels: [
      { name: 'qwen-plus (通用优选)', id: 'qwen-plus' },
      { name: 'qwen-turbo (极速)', id: 'qwen-turbo' },
      { name: 'deepseek-v3', id: 'deepseek-v3' },
    ],
  },
  {
    label: 'SiliconFlow 硅基流动 (超多免费大模型)',
    value: 'siliconflow',
    baseUrl: 'https://api.siliconflow.cn/v1',
    model: 'Qwen/Qwen2.5-7B-Instruct',
    docUrl: 'https://cloud.siliconflow.cn/account/ak',
    recommendedModels: [
      { name: 'Qwen2.5-7B (永久免费)', id: 'Qwen/Qwen2.5-7B-Instruct' },
      { name: 'DeepSeek-R1-8B (免费推理)', id: 'deepseek-ai/DeepSeek-R1-0528-Qwen3-8B' },
    ],
  },
  {
    label: 'DeepSeek 官方平台',
    value: 'deepseek',
    baseUrl: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    docUrl: 'https://platform.deepseek.com/api_keys',
    recommendedModels: [
      { name: 'deepseek-chat (V3)', id: 'deepseek-chat' },
      { name: 'deepseek-reasoner (R1)', id: 'deepseek-reasoner' },
    ],
  },
  {
    label: 'Ollama 本地部署 (100% 离线隐私)',
    value: 'ollama',
    baseUrl: 'http://127.0.0.1:11434/v1',
    model: 'qwen2.5:7b',
    docUrl: 'https://ollama.com',
    recommendedModels: [
      { name: 'qwen2.5:7b (轻量推荐)', id: 'qwen2.5:7b' },
      { name: 'deepseek-r1:7b', id: 'deepseek-r1:7b' },
    ],
  },
]

const config = ref(null)
const enabled = ref(false)
const baseUrl = ref('https://api-inference.modelscope.cn/v1')
const model = ref('deepseek-ai/DeepSeek-V4-Flash-0731')
const apiKey = ref('')
const selectedPreset = ref('modelscope')
const onlineModels = ref([])

const saving = ref(false)
const testing = ref(false)
const fetchingCatalog = ref(false)
const errorMsg = ref(null)

const currentPreset = computed(() => providerPresets.find(p => p.value === selectedPreset.value))

const modelOptions = computed(() => {
  const list = new Set()
  onlineModels.value.forEach(m => list.add(m))
  currentPreset.value?.recommendedModels.forEach(m => list.add(m.id))
  return Array.from(list).map(val => ({ value: val }))
})

const statusClass = computed(() => {
  if (config.value?.last_test_status === '成功') return 'status-success'
  if (config.value?.last_test_status === '失败') return 'status-failed'
  return 'status-idle'
})

const statusLabel = computed(() => {
  if (config.value?.last_test_status === '成功') return '已连通'
  if (config.value?.last_test_status === '失败') return '连接失败'
  return '尚未测试'
})

const loadConfig = async () => {
  try {
    const data = await getLlmConfig()
    config.value = data
    enabled.value = data.enabled
    baseUrl.value = data.base_url
    model.value = data.model

    const matched = providerPresets.find(p => p.baseUrl === data.base_url)
    if (matched) selectedPreset.value = matched.value
  } catch (err) {
    errorMsg.value = err?.response?.data?.detail || err.message || '加载配置失败'
  }
}

const handlePresetChange = (val) => {
  const p = providerPresets.find(item => item.value === val)
  if (p) {
    baseUrl.value = p.baseUrl
    model.value = p.model
  }
}

const handleSave = async () => {
  errorMsg.value = null
  saving.value = true
  try {
    const updated = await updateLlmConfig({
      enabled: enabled.value,
      base_url: baseUrl.value,
      model: model.value,
      api_key: apiKey.value || null,
    })
    config.value = updated
    apiKey.value = ''
    message.success('大模型配置已保存')
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
    const updated = await testLlmConnection({
      base_url: baseUrl.value,
      model: model.value,
      api_key: apiKey.value || null,
    })
    config.value = updated
    message.success('大模型连接测试成功！')
  } catch (err) {
    errorMsg.value = err?.response?.data?.detail || err.message || '测试失败'
    await loadConfig()
  } finally {
    testing.value = false
  }
}

const handleFetchCatalog = async () => {
  fetchingCatalog.value = true
  try {
    const res = await listLlmModels({
      base_url: baseUrl.value,
      api_key: apiKey.value || null,
    })
    onlineModels.value = res.models.map(m => m.id)
    message.success(res.message || `成功获取 ${res.models.length} 个可用模型`)
  } catch (err) {
    message.error(err?.response?.data?.detail || err.message || '获取模型列表失败')
  } finally {
    fetchingCatalog.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.llm-settings-card {
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

.llm-badge {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
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
  grid-template-columns: minmax(0, 1fr) 300px;
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

.quick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-top: 4px;
}

.tags-label {
  font-size: 11px;
  color: #9ca3af;
}

.quick-tag {
  font-size: 11px;
  background: #f3f4f6;
  color: #4b5563;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.quick-tag:hover {
  background: #e5e7eb;
  color: #111827;
}

.doc-link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: #7047f6;
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

.tips-list code {
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 3px;
  padding: 1px 4px;
}

.mt-3 {
  margin-top: 12px;
}
</style>
