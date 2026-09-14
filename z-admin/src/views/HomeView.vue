<template>
  <div class="home-projects-container">
    <div class="home-projects-content">
      <!-- 顶部标题与操作栏 -->
      <div class="page-header">
        <div class="header-left">
          <div class="header-title-row">
            <h1 class="page-title">创作项目</h1>
            <span class="project-count-badge">{{ filteredProjects.length }} 个项目</span>
          </div>
          <p class="page-subtitle">
            统一管理剧本创作、分镜生成、AI生图与视频资产。
          </p>
        </div>

        <div class="header-actions">
          <a-input
            v-model:value="searchKeyword"
            placeholder="搜索项目名称或简介..."
            allow-clear
            class="search-input"
          >
            <template #prefix>
              <Search :size="16" class="search-icon" />
            </template>
          </a-input>

          <a-button type="primary" size="large" class="create-btn" @click="openCreateModal">
            <template #icon>
              <Plus :size="18" />
            </template>
            新建项目
          </a-button>
        </div>
      </div>

      <!-- 加载中状态 -->
      <div v-if="loading" class="loading-box">
        <a-spin size="large" tip="正在加载项目列表..." />
      </div>

      <!-- 空状态 -->
      <div v-else-if="filteredProjects.length === 0" class="empty-box">
        <div class="empty-icon-wrap">
          <FolderPlus :size="48" class="empty-icon" />
        </div>
        <h3 class="empty-title">
          {{ searchKeyword ? '未找到匹配的项目' : '还没有任何创作项目' }}
        </h3>
        <p class="empty-desc">
          {{ searchKeyword ? '请尝试更换搜索关键字' : '立即创建您的第一个 AI 媒体创作项目，开启剧本与视频生成' }}
        </p>
        <a-button type="primary" class="empty-create-btn" @click="openCreateModal">
          <Plus :size="16" />
          创建新项目
        </a-button>
      </div>

      <!-- 项目卡片网格 -->
      <div v-else class="projects-grid">
        <div
          v-for="proj in filteredProjects"
          :key="proj.id"
          class="project-card"
          @click="goToProject(proj.id)"
        >
          <!-- 卡片头部背景封面 -->
          <div class="card-cover" :style="getCoverStyle(proj.id)">
            <div class="cover-badge">
              <span class="status-dot"></span>
              {{ proj.status === 'archived' ? '已归档' : '进行中' }}
            </div>
            <div class="cover-icon-bg">
              <Film :size="28" />
            </div>
          </div>

          <!-- 卡片主体信息 -->
          <div class="card-body">
            <h3 class="project-name" :title="proj.name">
              {{ proj.name }}
            </h3>
            <p class="project-desc" :title="proj.description || '暂无项目简介'">
              {{ proj.description || '暂无项目简介' }}
            </p>

            <div class="project-meta">
              <span class="meta-item">
                <Clock :size="13" />
                {{ formatTime(proj.updated_at) }}
              </span>
            </div>
          </div>

          <!-- 卡片操作底栏 -->
          <div class="card-footer">
            <a-button type="link" size="small" class="footer-btn enter-btn" @click.stop="goToProject(proj.id)">
              <ArrowRight :size="14" />
              进入项目
            </a-button>

            <a-button type="link" size="small" class="footer-btn edit-btn" @click.stop="openEditModal(proj)">
              <Edit3 :size="14" />
              编辑
            </a-button>

            <a-popconfirm
              title="确定要删除该项目吗？"
              description="删除后项目配置与相关资产将无法恢复。"
              ok-text="确认删除"
              cancel-text="取消"
              ok-type="danger"
              @confirm="handleDeleteProject(proj.id)"
            >
              <a-button type="link" size="small" danger class="footer-btn delete-btn" @click.stop>
                <Trash2 :size="14" />
                删除
              </a-button>
            </a-popconfirm>
          </div>
        </div>
      </div>
    </div>

    <!-- 创建项目 Modal -->
    <a-modal
      v-model:open="createModalVisible"
      title="新建创作项目"
      :confirm-loading="creating"
      ok-text="立即创建"
      cancel-text="取消"
      :width="520"
      destroy-on-close
      @ok="handleCreateSubmit"
    >
      <div class="modal-form">
        <a-form layout="vertical">
          <a-form-item label="项目名称" required>
            <a-input
              v-model:value="createForm.name"
              placeholder="例如：赛博朋克短剧《星际引力》"
              maxlength="100"
              show-count
              autofocus
              @pressEnter="handleCreateSubmit"
            />
          </a-form-item>

          <a-form-item label="项目描述 / 简介">
            <a-textarea
              v-model:value="createForm.description"
              placeholder="简要描述项目的创作主题、剧本概要或生成目标（选填）..."
              :rows="3"
              maxlength="300"
              show-count
            />
          </a-form-item>

          <a-form-item label="画幅与创作规格">
            <div class="preset-specs">
              <div
                v-for="spec in presetSpecs"
                :key="spec.id"
                class="spec-tag"
                :class="{ active: createForm.aspectRatio === spec.id }"
                @click="createForm.aspectRatio = spec.id"
              >
                <span class="spec-ratio">{{ spec.ratio }}</span>
                <span class="spec-label">{{ spec.label }}</span>
              </div>
            </div>
          </a-form-item>
        </a-form>
      </div>
    </a-modal>

    <!-- 编辑项目 Modal -->
    <a-modal
      v-model:open="editModalVisible"
      title="编辑项目信息"
      :confirm-loading="updating"
      ok-text="保存修改"
      cancel-text="取消"
      :width="520"
      destroy-on-close
      @ok="handleEditSubmit"
    >
      <div class="modal-form">
        <a-form layout="vertical">
          <a-form-item label="项目名称" required>
            <a-input
              v-model:value="editForm.name"
              placeholder="请输入项目名称"
              maxlength="100"
              show-count
              @pressEnter="handleEditSubmit"
            />
          </a-form-item>

          <a-form-item label="项目描述 / 简介">
            <a-textarea
              v-model:value="editForm.description"
              placeholder="简要描述项目的创作主题或剧本概要..."
              :rows="3"
              maxlength="300"
              show-count
            />
          </a-form-item>
        </a-form>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  Plus,
  Search,
  FolderPlus,
  Clock,
  Film,
  Edit3,
  Trash2,
  ArrowRight,
} from 'lucide-vue-next'
import { listProjects, createProject, updateProject, deleteProject } from '../api/projects'

const router = useRouter()

function goToProject(id) {
  router.push(`/projects/${id}`)
}

// 状态
const projects = ref([])
const loading = ref(false)
const searchKeyword = ref('')

// 预设画幅
const presetSpecs = [
  { id: '16:9', ratio: '16:9', label: '横屏电影/长视频' },
  { id: '9:16', ratio: '9:16', label: '竖屏短剧/短视频' },
  { id: '1:1', ratio: '1:1', label: '正方形/插画社媒' },
]

// 创建模态框
const createModalVisible = ref(false)
const creating = ref(false)
const createForm = ref({
  name: '',
  description: '',
  aspectRatio: '16:9',
})

// 编辑模态框
const editModalVisible = ref(false)
const updating = ref(false)
const editForm = ref({
  id: '',
  name: '',
  description: '',
})

// 过滤列表
const filteredProjects = computed(() => {
  const kw = (searchKeyword.value || '').trim().toLowerCase()
  if (!kw) return projects.value
  return projects.value.filter(
    (p) =>
      (p.name && p.name.toLowerCase().includes(kw)) ||
      (p.description && p.description.toLowerCase().includes(kw))
  )
})

// 随机渐变封面背景生成（基于项目 ID hash，保证每次相同）
function getCoverStyle(id) {
  const gradients = [
    'linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)',
    'linear-gradient(135deg, #2563eb 0%, #06b6d4 100%)',
    'linear-gradient(135deg, #059669 0%, #10b981 100%)',
    'linear-gradient(135deg, #d97706 0%, #f59e0b 100%)',
    'linear-gradient(135deg, #db2777 0%, #f43f5e 100%)',
    'linear-gradient(135deg, #9333ea 0%, #c084fc 100%)',
    'linear-gradient(135deg, #0284c7 0%, #38bdf8 100%)',
  ]
  let hash = 0
  for (let i = 0; i < (id || '').length; i++) {
    hash = (hash << 5) - hash + id.charCodeAt(i)
    hash |= 0
  }
  const index = Math.abs(hash) % gradients.length
  return {
    background: gradients[index],
  }
}

// 时间格式化
function formatTime(val) {
  if (!val) return ''
  try {
    const d = new Date(val)
    if (isNaN(d.getTime())) return val
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const diffHours = diffMs / (1000 * 60 * 60)
    if (diffHours < 1) {
      const mins = Math.max(1, Math.floor(diffMs / (1000 * 60)))
      return `${mins} 分钟前`
    }
    if (diffHours < 24) {
      return `${Math.floor(diffHours)} 小时前`
    }
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  } catch {
    return val
  }
}

// 加载项目
async function fetchProjects() {
  loading.value = true
  try {
    const data = await listProjects()
    projects.value = Array.isArray(data) ? data : []
  } catch (err) {
    message.error(err?.response?.data?.detail || '加载项目列表失败')
  } finally {
    loading.value = false
  }
}

// 打开创建弹窗
function openCreateModal() {
  createForm.value = {
    name: '',
    description: '',
    aspectRatio: '16:9',
  }
  createModalVisible.value = true
}

// 提交创建
async function handleCreateSubmit() {
  const name = createForm.value.name.trim()
  if (!name) {
    message.warning('请输入项目名称')
    return
  }

  creating.value = true
  try {
    await createProject({
      name,
      description: createForm.value.description.trim(),
      settings: {
        aspectRatio: createForm.value.aspectRatio,
      },
    })
    message.success('项目创建成功')
    createModalVisible.value = false
    await fetchProjects()
  } catch (err) {
    message.error(err?.response?.data?.detail || '创建项目失败')
  } finally {
    creating.value = false
  }
}

// 打开编辑弹窗
function openEditModal(proj) {
  editForm.value = {
    id: proj.id,
    name: proj.name,
    description: proj.description || '',
  }
  editModalVisible.value = true
}

// 提交编辑
async function handleEditSubmit() {
  const name = editForm.value.name.trim()
  if (!name) {
    message.warning('项目名称不能为空')
    return
  }

  updating.value = true
  try {
    await updateProject(editForm.value.id, {
      name,
      description: editForm.value.description.trim(),
    })
    message.success('项目信息已更新')
    editModalVisible.value = false
    await fetchProjects()
  } catch (err) {
    message.error(err?.response?.data?.detail || '更新项目失败')
  } finally {
    updating.value = false
  }
}

// 删除项目
async function handleDeleteProject(id) {
  try {
    await deleteProject(id)
    message.success('项目已删除')
    await fetchProjects()
  } catch (err) {
    message.error(err?.response?.data?.detail || '删除项目失败')
  }
}

onMounted(() => {
  fetchProjects()
})
</script>

<style scoped>
.home-projects-container {
  min-height: calc(100vh - 64px);
  background-color: #f9fafb;
  padding: 32px 24px 64px;
}

.home-projects-content {
}

/* 头部栏 */
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 28px;
  gap: 20px;
  flex-wrap: wrap;
}

.header-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: #111827;
  margin: 0;
  letter-spacing: -0.4px;
}

.project-count-badge {
  font-size: 12px;
  color: #7047f6;
  background: rgba(112, 71, 246, 0.1);
  padding: 3px 10px;
  border-radius: 20px;
  font-weight: 600;
}

.page-subtitle {
  font-size: 14px;
  color: #6b7280;
  margin: 6px 0 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.search-input {
  width: 260px;
  border-radius: 8px;
}

.search-icon {
  color: #9ca3af;
}

.create-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: linear-gradient(135deg, #7047f6 0%, #8b5cf6 100%);
  border: none;
  font-weight: 600;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(112, 71, 246, 0.28);
  transition: all 0.2s;
}

.create-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(112, 71, 246, 0.35);
  background: linear-gradient(135deg, #7c58f8 0%, #9065f7 100%) !important;
}

/* 加载状态 */
.loading-box {
  padding: 100px 0;
  text-align: center;
}

/* 空状态 */
.empty-box {
  background: #ffffff;
  border: 1px dashed rgba(0, 0, 0, 0.12);
  border-radius: 16px;
  padding: 72px 24px;
  text-align: center;
  margin-top: 16px;
}

.empty-icon-wrap {
  width: 80px;
  height: 80px;
  border-radius: 24px;
  background: rgba(112, 71, 246, 0.08);
  display: grid;
  place-items: center;
  color: #7047f6;
  margin: 0 auto 20px;
}

.empty-title {
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
  margin: 0 0 8px;
}

.empty-desc {
  font-size: 14px;
  color: #6b7280;
  margin: 0 auto 24px;
  max-width: 420px;
  line-height: 22px;
}

.empty-create-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #7047f6;
  border-radius: 8px;
  height: 40px;
  padding: 0 20px;
}

/* 卡片网格 */
.projects-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 22px;
}

.project-card {
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.07);
  border-radius: 14px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.project-card:hover {
  transform: translateY(-3px);
  border-color: rgba(112, 71, 246, 0.3);
  box-shadow: 0 10px 24px rgba(112, 71, 246, 0.1);
}

/* 卡片封面图 */
.card-cover {
  height: 120px;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.85);
  overflow: hidden;
}

.cover-badge {
  position: absolute;
  top: 12px;
  left: 12px;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(8px);
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
  color: #ffffff;
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}

.cover-icon-bg {
  opacity: 0.7;
  transition: transform 0.3s;
}

.project-card:hover .cover-icon-bg {
  transform: scale(1.1);
  opacity: 0.95;
}

/* 卡片内容 */
.card-body {
  padding: 16px 18px 12px;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.project-name {
  font-size: 16px;
  font-weight: 600;
  color: #111827;
  margin: 0 0 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.project-name:hover {
  color: #7047f6;
}

.project-desc {
  font-size: 13px;
  color: #6b7280;
  margin: 0 0 14px;
  line-height: 20px;
  height: 40px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.project-meta {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #9ca3af;
  padding-top: 10px;
  border-top: 1px solid #f3f4f6;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 5px;
}

/* 卡片底栏 */
.card-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 8px 14px;
  background: #fafafa;
  border-top: 1px solid rgba(0, 0, 0, 0.05);
  gap: 6px;
}

.footer-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 0 6px;
}

.edit-btn {
  color: #4b5563;
}

.edit-btn:hover {
  color: #7047f6;
}

/* 规格选择 */
.preset-specs {
  display: flex;
  gap: 10px;
}

.spec-tag {
  flex: 1;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 8px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  background: #ffffff;
}

.spec-tag:hover {
  border-color: #7047f6;
}

.spec-tag.active {
  border-color: #7047f6;
  background: rgba(112, 71, 246, 0.05);
}

.spec-ratio {
  display: block;
  font-size: 14px;
  font-weight: 700;
  color: #111827;
}

.spec-tag.active .spec-ratio {
  color: #7047f6;
}

.spec-label {
  display: block;
  font-size: 11px;
  color: #6b7280;
  margin-top: 2px;
}
</style>
