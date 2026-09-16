<template>
  <div class="jobs-pane">
    <div class="sub-pane-header">
      <div>
        <h2 class="sub-pane-title">全部任务</h2>
        <p class="sub-pane-subtitle">
          监控项目下所有异步生图、大模型剧本分析、分镜渲染与视频合成任务的执行进度。
        </p>
      </div>

      <a-space>
        <a-popconfirm
          title="确定取消当前项目下所有排队中和执行中的任务？"
          ok-text="全部取消"
          cancel-text="返回"
          ok-type="danger"
          :disabled="!hasCancellableJobs"
          @confirm="handleCancelAll"
        >
          <a-button danger :loading="cancellingAll" :disabled="!hasCancellableJobs">
            <template #icon><Ban :size="15" /></template>
            取消全部任务
          </a-button>
        </a-popconfirm>
        <a-button :loading="loading" @click="fetchJobs">
          <template #icon><RefreshCw :size="15" /></template>
          刷新任务
        </a-button>
      </a-space>
    </div>

    <!-- 任务表格 -->
    <div class="jobs-table-card">
      <a-table
        :loading="loading"
        :data-source="jobs"
        :columns="columns"
        row-key="id"
        :pagination="pagination"
        :show-sorter-tooltip="false"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <!-- 任务名称 -->
          <template v-if="column.key === 'title'">
            <div class="job-title-cell">
              <span class="job-name">{{ record.title }}</span>
              <span class="job-id">{{ record.id }}</span>
            </div>
          </template>

          <!-- 类型 -->
          <template v-else-if="column.key === 'job_type'">
            <a-tag :color="record.job_type === 'video_generation' ? 'purple' : (record.job_type === 'h3_prompt' ? 'cyan' : (record.job_type === 'llm_analysis' ? 'green' : 'blue'))">
              {{ getJobTypeText(record.job_type) }}
            </a-tag>
          </template>

          <!-- 状态 -->
          <template v-else-if="column.key === 'status'">
            <a-tag :color="getStatusTag(record.status).color">
              {{ getStatusTag(record.status).text }}
            </a-tag>
          </template>

          <!-- 进度 -->
          <template v-else-if="column.key === 'progress'">
            <a-progress
              :percent="record.progress"
              size="small"
              :status="record.status === 'failed' || record.status === 'cancelled' ? 'exception' : (record.progress === 100 ? 'success' : 'active')"
            />
          </template>

          <!-- 结果图片缩略图 -->
          <template v-else-if="column.key === 'result'">
            <a
              v-if="record.result_url"
              :href="record.result_url"
              target="_blank"
            >
              <video
                v-if="record.job_type === 'video_generation'"
                :src="record.result_url"
                class="result-thumb"
                muted
                preload="metadata"
              />
              <img v-else :src="record.result_url" class="result-thumb" alt="结果图" />
            </a>
            <span v-else-if="record.job_type === 'h3_prompt' || record.payload?.target_type === 'h3_prompt'" class="text-muted">
              <a-tag v-if="record.status === 'completed'" color="cyan" size="small">提示词就绪</a-tag>
              <span v-else>—</span>
            </span>
            <span v-else class="text-muted">—</span>
          </template>

          <!-- 操作 -->
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a-button
                size="small"
                type="primary"
                ghost
                @click="openDetail(record)"
              >
                查看详情
              </a-button>
              <a-button
                v-if="record.status === 'failed'"
                size="small"
                type="link"
                @click="handleRetry(record.id)"
              >
                重试
              </a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </div>

    <!-- 任务详情弹窗 -->
    <a-modal
      v-model:open="detailVisible"
      title="任务详情"
      width="860px"
      :footer="null"
      destroy-on-close
    >
      <div v-if="selectedJob" class="detail-modal-body">
        <!-- 顶部状态栏 -->
        <div class="detail-status-bar">
          <div class="detail-title-block">
            <span class="detail-job-name">{{ selectedJob.title }}</span>
            <a-tag :color="getStatusTag(selectedJob.status).color" style="margin-left: 8px;">
              {{ getStatusTag(selectedJob.status).text }}
            </a-tag>
          </div>
          <span class="detail-job-id">{{ selectedJob.id }}</span>
        </div>

        <!-- 基本信息 -->
        <div class="detail-section">
          <div class="detail-section-title">📋 基本信息</div>
          <div class="detail-grid">
            <div class="detail-row">
              <span class="detail-key">任务类型</span>
              <span class="detail-val"><a-tag color="blue">{{ getJobTypeText(selectedJob.job_type) }}</a-tag></span>
            </div>
            <div class="detail-row">
              <span class="detail-key">创建时间</span>
              <span class="detail-val">{{ selectedJob.created_at }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-key">完成时间</span>
              <span class="detail-val">{{ selectedJob.completed_at || selectedJob.updated_at }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-key">执行进度</span>
              <span class="detail-val">
                <a-progress :percent="selectedJob.progress" size="small" style="width: 200px" />
              </span>
            </div>
          </div>
        </div>

        <div v-if="isVideoJob(selectedJob)" class="detail-section">
          <div class="detail-section-title">视频生成参数</div>
          <div class="detail-grid">
            <div class="detail-row"><span class="detail-key">分集</span><span class="detail-val">第 {{ selectedJob.payload?.episode_number }} 集 · {{ selectedJob.payload?.episode_title }}</span></div>
            <div class="detail-row"><span class="detail-key">生成规格</span><span class="detail-val">{{ selectedJob.payload?.shot_count }} 镜 × 8 秒 · {{ selectedJob.payload?.total_duration_seconds }} 秒 · {{ selectedJob.payload?.fps }} fps</span></div>
            <div class="detail-row"><span class="detail-key">输出分辨率</span><span class="detail-val">{{ selectedJob.payload?.width }} × {{ selectedJob.payload?.height }} px</span></div>
            <div class="detail-row"><span class="detail-key">音频模式</span><span class="detail-val">{{ selectedJob.payload?.audio_mode }}</span></div>
            <div class="detail-row"><span class="detail-key">Comfy Prompt</span><span class="detail-val mono">{{ selectedJob.payload?.prompt_id || '尚未提交' }}</span></div>
            <div class="detail-row"><span class="detail-key">队列序号</span><span class="detail-val">{{ selectedJob.payload?.queue_number ?? '—' }}</span></div>
            <div class="detail-row"><span class="detail-key">当前阶段</span><span class="detail-val">{{ selectedJob.payload?.runtime_stage || selectedJob.status }}</span></div>
          </div>
        </div>

        <div v-if="isVideoJob(selectedJob) && videoShots(selectedJob).length" class="detail-section">
          <div class="detail-section-title">镜头参考图与 H3 提示词</div>
          <div class="video-shot-list">
            <section v-for="shot in videoShots(selectedJob)" :key="shot.beat_id" class="video-shot-item">
              <div class="video-shot-head">Beat {{ shot.sequence }} · {{ shot.heading || shot.scene }}</div>
              <div class="video-ref-grid">
                <div v-for="(url, idx) in shot.reference_urls" :key="url" class="video-ref-item">
                  <a :href="url" target="_blank"><img :src="url" :alt="`Picture ${idx + 1}`" /></a>
                  <span>Picture {{ idx + 1 }} · {{ videoReferenceLabel(shot, idx) }}</span>
                </div>
              </div>
              <div v-if="shot.prompt" class="prompt-block">
                <div class="prompt-label">MiniMax H3 Ref2VA Prompt</div>
                <pre class="prompt-text">{{ shot.prompt }}</pre>
              </div>
              <div v-else class="text-muted">提示词尚未生成</div>
            </section>
          </div>
        </div>

        <div v-if="isVideoJob(selectedJob) && llmAttempts(selectedJob).length" class="detail-section">
          <div class="detail-section-title">LLM 提示词生成记录</div>
          <div class="attempt-list">
            <details v-for="(attempt, idx) in llmAttempts(selectedJob)" :key="`${attempt.beat_id}-${attempt.attempt}-${idx}`" class="attempt-item">
              <summary>
                Beat {{ attempt.sequence }} · 第 {{ attempt.attempt }} 次
                <a-tag :color="attempt.status === 'passed' ? 'green' : 'red'">
                  {{ attempt.status === 'passed' ? '通过' : '失败' }}
                </a-tag>
              </summary>
              <div v-if="attempt.errors?.length" class="attempt-errors">{{ attempt.errors.join('\n') }}</div>
              <pre class="prompt-text">{{ attempt.raw_response || '无原始响应' }}</pre>
            </details>
          </div>
        </div>

        <div v-if="isVideoJob(selectedJob) && selectedJob.payload?.director_report" class="detail-section">
          <div class="detail-section-title">MiniMax H3 Director 报告</div>
          <div class="prompt-block">
            <pre class="prompt-text">{{ selectedJob.payload.director_report }}</pre>
          </div>
        </div>

        <!-- 调用参数 -->
        <div v-if="!isVideoJob(selectedJob) && selectedJob.payload && Object.keys(selectedJob.payload).length" class="detail-section">
          <div class="detail-section-title">⚙️ 调用参数</div>
          <div class="detail-grid">
            <div class="detail-row">
              <span class="detail-key">调用模型</span>
              <span class="detail-val model-tag">{{ selectedJob.payload.model || '—' }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-key">API 接口</span>
              <span class="detail-val mono">{{ selectedJob.payload.api_endpoint || '—' }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-key">目标类型</span>
              <span class="detail-val"><a-tag>{{ selectedJob.payload.target_type || '—' }}</a-tag></span>
            </div>
            <div class="detail-row">
              <span class="detail-key">宽高比</span>
              <span class="detail-val">{{ selectedJob.payload.aspect_ratio || '—' }}</span>
            </div>
            <div v-if="selectedJob.payload.image_size" class="detail-row">
              <span class="detail-key">imageSize</span>
              <span class="detail-val">{{ selectedJob.payload.image_size }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-key">replyType</span>
              <span class="detail-val">{{ selectedJob.payload.reply_type || selectedJob.payload.request_body?.replyType || 'async' }}</span>
            </div>
            <div v-if="selectedJob.payload.visual_style" class="detail-row">
              <span class="detail-key">画风 visual_style</span>
              <span class="detail-val">{{ selectedJob.payload.visual_style }}</span>
            </div>
            <div v-if="selectedJob.payload.art_style_id" class="detail-row">
              <span class="detail-key">art_style_id</span>
              <span class="detail-val">{{ selectedJob.payload.art_style_id }}</span>
            </div>
            <div v-if="selectedJob.payload.ethnicity" class="detail-row">
              <span class="detail-key">族裔</span>
              <span class="detail-val">{{ selectedJob.payload.ethnicity }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-key">输出分辨率</span>
              <span class="detail-val">{{ selectedJob.payload.width || '—' }} × {{ selectedJob.payload.height || '—' }} px</span>
            </div>
            <div v-if="selectedJob.payload.asset_name" class="detail-row">
              <span class="detail-key">关联资产</span>
              <span class="detail-val">{{ selectedJob.payload.asset_name }} <span class="text-muted">{{ selectedJob.payload.asset_id }}</span></span>
            </div>
            <div v-if="selectedJob.payload.identity_id" class="detail-row">
              <span class="detail-key">造型 ID</span>
              <span class="detail-val mono">{{ selectedJob.payload.identity_id }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-key">参考图数量</span>
              <span class="detail-val">{{ referenceUrls(selectedJob).length }}</span>
            </div>
          </div>
        </div>

        <!-- 参考图 -->
        <div v-if="!isVideoJob(selectedJob)" class="detail-section">
          <div class="detail-section-title">🖼 传入参考图 (images)</div>
          <div v-if="referenceUrls(selectedJob).length" class="ref-grid">
            <div v-for="(url, idx) in referenceUrls(selectedJob)" :key="url + idx" class="ref-item">
              <a :href="url" target="_blank">
                <img :src="url" class="ref-thumb" :alt="`参考图 ${idx + 1}`" />
              </a>
              <div class="ref-meta">
                <span class="prompt-label">REFERENCE {{ idx + 1 }}{{ idx === 0 && selectedJob.payload?.identity_anchor ? ' · 身份锚点' : '' }}</span>
                <a :href="url" target="_blank" class="url-link">{{ url }}</a>
              </div>
            </div>
          </div>
          <div v-else class="text-muted ref-empty">
            本次请求未传入参考图（images 为空）。造型图应对齐 source1，把头像作为 REFERENCE 1。
          </div>
        </div>

        <!-- H3 视频生成提示词展示 -->
        <div v-if="(selectedJob.job_type === 'h3_prompt' || selectedJob.payload?.target_type === 'h3_prompt') && (selectedJob.payload?.h3_prompt || selectedJob.payload?.result_prompt)" class="detail-section">
          <div class="detail-section-title" style="display: flex; justify-content: space-between; align-items: center;">
            <span>🎬 生成的 MiniMax H3 视频生成提示词</span>
            <a-button type="link" size="small" @click="copyPrompt(selectedJob.payload?.h3_prompt || selectedJob.payload?.result_prompt)">
              <template #icon><Copy :size="13" /></template>
              复制提示词
            </a-button>
          </div>
          <div class="prompt-block">
            <pre class="prompt-text">{{ selectedJob.payload?.h3_prompt || selectedJob.payload?.result_prompt }}</pre>
          </div>
        </div>

        <!-- Prompt -->
        <div v-if="selectedJob.job_type !== 'h3_prompt' && (selectedJob.payload?.prompt || selectedJob.payload?.clean_prompt)" class="detail-section">
          <div class="detail-section-title">✍️ 生图提示词 (Prompt)</div>
          <div v-if="selectedJob.payload.prompt" class="prompt-block">
            <div class="prompt-label">原始 Prompt</div>
            <pre class="prompt-text">{{ selectedJob.payload.prompt }}</pre>
          </div>
          <div v-if="selectedJob.payload.clean_prompt" class="prompt-block" style="margin-top: 10px;">
            <div class="prompt-label">发送给 API 的完整 Prompt</div>
            <pre class="prompt-text">{{ selectedJob.payload.clean_prompt }}</pre>
          </div>
        </div>

        <!-- GRS 请求体 -->
        <div v-if="!isVideoJob(selectedJob) && selectedJob.job_type !== 'h3_prompt'" class="detail-section">
          <div class="detail-section-title">📤 提交给 GRS 的完整参数</div>
          <div class="prompt-block">
            <div class="prompt-label">POST /v1/api/generate JSON（images 为参考图 URL，实际上传为 data URI）</div>
            <pre class="prompt-text">{{ formatRequestBody(selectedJob) }}</pre>
          </div>
        </div>

        <!-- 完整请求 URL -->
        <div v-if="selectedJob.payload?.api_url" class="detail-section">
          <div class="detail-section-title">🔗 完整请求 URL</div>
          <div class="url-block">
            <a :href="selectedJob.payload.api_url" target="_blank" class="url-link">
              {{ selectedJob.payload.api_url }}
            </a>
          </div>
        </div>

        <!-- 结果图片 -->
        <div v-if="selectedJob.result_url" class="detail-section">
          <div class="detail-section-title">🎉 生成结果</div>
          <div class="result-box">
            <video
              v-if="isVideoJob(selectedJob)"
              :src="selectedJob.result_url"
              controls
              class="result-video"
              preload="metadata"
            />
            <img v-else :src="selectedJob.result_url" class="result-img" alt="生成结果" />
            <div class="result-meta">
              <a-button type="link" size="small" @click="openResultUrl(selectedJob.result_url)">
                在新标签页打开原图/视频
              </a-button>
            </div>
          </div>
        </div>

        <!-- 错误信息 -->
        <div v-if="selectedJob.error_message" class="detail-section error-section">
          <div class="detail-section-title">❌ 失败原因</div>
          <div class="error-box">
            {{ selectedJob.error_message }}
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { message } from 'ant-design-vue'
import { Ban, RefreshCw, ExternalLink, Copy } from 'lucide-vue-next'
import { listJobs, retryJob, cancelAllJobs } from '../../api/projects'

const props = defineProps({
  projectId: { type: String, required: true },
})

const jobs = ref([])
const pagination = { pageSize: 20, showSizeChanger: false, hideOnSinglePage: false }
const loading = ref(false)
const cancellingAll = ref(false)
const detailVisible = ref(false)
const selectedJob = ref(null)

const TERMINAL_JOB_STATUSES = ['completed', 'succeeded', 'failed', 'cancelled']
const hasCancellableJobs = computed(() =>
  jobs.value.some((job) => !TERMINAL_JOB_STATUSES.includes(job.status)),
)

const columns = [
  { title: '任务名称 / ID', key: 'title', width: 280 },
  { title: '类型', key: 'job_type', width: 120 },
  { title: '状态', key: 'status', width: 100 },
  { title: '进度', key: 'progress', width: 180 },
  { title: '结果', key: 'result', width: 80 },
  { title: '创建时间', dataIndex: 'created_at', width: 160 },
  { title: '操作', key: 'action', width: 140 },
]

function getStatusTag(s) {
  const map = {
    queued: { color: 'default', text: '排队中' },
    preparing: { color: 'processing', text: '准备数据' },
    prompt_generation: { color: 'processing', text: '生成提示词' },
    uploading: { color: 'processing', text: '上传素材' },
    comfy_queued: { color: 'cyan', text: 'ComfyUI 排队' },
    running: { color: 'processing', text: '执行中' },
    succeeded: { color: 'green', text: '已完成' },
    completed: { color: 'green', text: '已完成' },
    failed: { color: 'red', text: '失败' },
    cancelled: { color: 'default', text: '已取消' },
  }
  return map[s] || { color: 'default', text: s }
}

function getJobTypeText(type) {
  const map = {
    image_generation: '图片生成',
    video_generation: '视频生成',
    llm_analysis: '大模型补全',
    h3_prompt: 'H3提示词生成',
  }
  return map[type] || type
}

function copyPrompt(text) {
  if (!text) return
  navigator.clipboard.writeText(text).then(() => {
    message.success('H3 提示词已复制到剪贴板')
  })
}

function isVideoJob(job) {
  return job?.job_type === 'video_generation'
}

function videoShots(job) {
  const shots = job?.payload?.shots?.length ? job.payload.shots : job?.payload?.source_shots
  return Array.isArray(shots) ? shots : []
}

function llmAttempts(job) {
  return Array.isArray(job?.payload?.llm_attempts) ? job.payload.llm_attempts : []
}

function videoReferenceLabel(shot, index) {
  const characters = Array.isArray(shot?.character_references) ? shot.character_references : []
  if (index < characters.length) {
    const character = characters[index]
    return `${character.character_name || '角色'}造型${character.look_id ? ` (${character.look_id})` : ''}`
  }
  return '场景'
}

function referenceUrls(job) {
  const p = job?.payload || {}
  const list = p.reference_urls || p.request_body?.images || p.images || []
  return (Array.isArray(list) ? list : []).filter(
    (u) => typeof u === 'string' && /^https?:\/\//.test(u) && !u.startsWith('data:'),
  )
}

function formatRequestBody(job) {
  const p = job?.payload || {}
  const refs = referenceUrls(job)
  const body = p.request_body && typeof p.request_body === 'object'
    ? { ...p.request_body, images: refs.length ? refs : (p.request_body.images || []) }
    : {
        model: p.model,
        prompt: p.clean_prompt || p.prompt,
        images: refs,
        aspectRatio: p.aspect_ratio,
        imageSize: p.image_size || '1K',
        replyType: p.reply_type || 'async',
      }
  return JSON.stringify(body, null, 2)
}

function openDetail(job) {
  selectedJob.value = job
  detailVisible.value = true
}

function openResultUrl(url) {
  window.open(url, '_blank')
}

async function fetchJobs(silent = false) {
  if (!silent) loading.value = true
  try {
    const res = await listJobs(props.projectId)
    const rows = Array.isArray(res) ? res : []
    jobs.value = rows.slice().sort((a, b) => {
      const created = String(b.created_at || '').localeCompare(String(a.created_at || ''))
      if (created) return created
      return String(b.id || '').localeCompare(String(a.id || ''))
    })
    if (selectedJob.value) {
      selectedJob.value = jobs.value.find(job => job.id === selectedJob.value.id) || selectedJob.value
    }
    pollDelay = 3000
  } catch (err) {
    if (!silent) message.error('加载任务列表失败，请确认后端服务已启动（9010）')
    pollDelay = Math.min(pollDelay * 2, 15000)
  } finally {
    if (!silent) loading.value = false
  }
}

async function handleRetry(id) {
  try {
    await retryJob(props.projectId, id)
    message.success('任务已重新启动')
    await fetchJobs()
  } catch (err) {
    message.error('重试失败')
  }
}

async function handleCancelAll() {
  cancellingAll.value = true
  try {
    const res = await cancelAllJobs(props.projectId)
    const count = res?.cancelled || 0
    message.success(count ? `已取消 ${count} 个未完成任务` : '没有可取消的任务')
    await fetchJobs()
  } catch (err) {
    message.error(err?.response?.data?.detail || '取消全部任务失败')
  } finally {
    cancellingAll.value = false
  }
}

let pollTimer = null
let pollDelay = 3000
function schedulePoll() {
  if (pollTimer) window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(async () => {
    await fetchJobs(true)
    schedulePoll()
  }, pollDelay)
}

onMounted(() => {
  fetchJobs()
  schedulePoll()
})
onUnmounted(() => {
  if (pollTimer) window.clearTimeout(pollTimer)
})
</script>

<style scoped>
.jobs-pane {
  padding: 4px 0;
}

.sub-pane-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.sub-pane-title {
  font-size: 20px;
  font-weight: 700;
  color: #111827;
  margin: 0 0 4px;
}

.sub-pane-subtitle {
  font-size: 13px;
  color: #6b7280;
  margin: 0;
}

.jobs-table-card {
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.job-title-cell {
  display: flex;
  flex-direction: column;
}

.job-name {
  font-weight: 600;
  color: #1f2937;
  font-size: 13px;
}

.job-id {
  font-size: 11px;
  color: #94a3b8;
  font-family: monospace;
}

.result-thumb {
  width: 48px;
  height: 36px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid #e5e7eb;
  cursor: pointer;
  transition: transform 0.2s;
}

.result-thumb:hover {
  transform: scale(1.05);
}

.text-muted {
  font-size: 12px;
  color: #94a3b8;
}

/* ---- 详情弹窗 ---- */
.detail-modal-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding-bottom: 8px;
}

.detail-status-bar {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 16px;
  background: #f9fafb;
  border-radius: 10px;
  border: 1px solid #f3f4f6;
}

.detail-title-block {
  display: flex;
  align-items: center;
}

.detail-job-name {
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}

.detail-job-id {
  font-size: 11px;
  color: #94a3b8;
  font-family: monospace;
}

.detail-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-section-title {
  font-size: 13px;
  font-weight: 700;
  color: #374151;
  padding-bottom: 6px;
  border-bottom: 1px solid #f3f4f6;
}

.detail-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.detail-key {
  width: 110px;
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 500;
  color: #6b7280;
  padding-top: 2px;
}

.detail-val {
  font-size: 13px;
  color: #1f2937;
  word-break: break-all;
}

.model-tag {
  font-weight: 600;
  color: #7047f6;
  background: rgba(112, 71, 246, 0.08);
  padding: 1px 8px;
  border-radius: 6px;
  font-size: 12px;
}

.mono {
  font-family: monospace;
  font-size: 12px;
  color: #0284c7;
  background: #f0f9ff;
  padding: 2px 8px;
  border-radius: 4px;
}

.prompt-block {
  background: #f9fafb;
  border: 1px solid #f3f4f6;
  border-radius: 8px;
  padding: 10px 12px;
}

.prompt-label {
  font-size: 11px;
  font-weight: 600;
  color: #9ca3af;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  margin-bottom: 6px;
}

.prompt-text {
  font-family: monospace;
  font-size: 12px;
  line-height: 1.7;
  color: #374151;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.url-block {
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 8px;
  padding: 10px 12px;
  word-break: break-all;
}

.url-link {
  font-family: monospace;
  font-size: 11px;
  color: #0284c7;
  text-decoration: none;
  line-height: 1.6;
}

.url-link:hover {
  text-decoration: underline;
}

.ref-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ref-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px;
}

.ref-thumb {
  width: 96px;
  height: 96px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  background: #111827;
  flex-shrink: 0;
}

.ref-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.ref-empty {
  font-size: 13px;
  padding: 8px 0;
}

.result-preview {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}

.result-img {
  max-width: 100%;
  max-height: 300px;
  object-fit: contain;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  cursor: pointer;
}

.result-video {
  width: 100%;
  max-height: 420px;
  background: #111827;
  border-radius: 6px;
}

.video-shot-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.video-shot-item {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
  background: #fff;
}

.video-shot-head {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.video-ref-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 10px;
}

.video-ref-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: 12px;
  color: #4b5563;
}

.video-ref-item img {
  width: 72px;
  height: 72px;
  border-radius: 4px;
  object-fit: cover;
  border: 1px solid #e5e7eb;
}

.attempt-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.attempt-item {
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 9px 11px;
  background: #fff;
}

.attempt-item summary {
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: #374151;
}

.attempt-errors {
  margin: 8px 0;
  padding: 8px;
  white-space: pre-wrap;
  font-size: 12px;
  color: #b91c1c;
  background: #fef2f2;
  border-radius: 4px;
}

.result-open-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #6b7280;
  text-decoration: none;
}

.result-open-link:hover {
  color: #7047f6;
}
</style>
