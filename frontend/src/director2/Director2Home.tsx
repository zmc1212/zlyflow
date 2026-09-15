// 创作项目首页 —— 逐行复刻自 dev0914 z-admin/src/views/HomeView.vue
// Vue → React 对应：ref→useState、computed→useMemo、onMounted→useEffect。
import { useCallback, useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button, Input, Modal, Popconfirm, Spin, message } from "antd"
import {
  Plus,
  Search,
  FolderPlus,
  Clock,
  Film,
  Edit3,
  Trash2,
  ArrowRight,
} from "lucide-react"
import {
  listProjects,
  createProject,
  updateProject,
  deleteProject,
  director2ErrorDetail,
  type Director2Project,
} from "./api"
import { director2ProjectPath } from "./paths"

interface HomeContext {
  csrfToken: string
}

const PRESET_SPECS = [
  { id: "16:9", ratio: "16:9", label: "横屏电影/长视频" },
  { id: "9:16", ratio: "9:16", label: "竖屏短剧/短视频" },
  { id: "1:1", ratio: "1:1", label: "正方形/插画社媒" },
]

// 随机渐变封面背景生成（基于项目 ID hash，保证每次相同）
function coverBackground(id: string): string {
  const gradients = [
    "linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)",
    "linear-gradient(135deg, #2563eb 0%, #06b6d4 100%)",
    "linear-gradient(135deg, #059669 0%, #10b981 100%)",
    "linear-gradient(135deg, #d97706 0%, #f59e0b 100%)",
    "linear-gradient(135deg, #db2777 0%, #f43f5e 100%)",
    "linear-gradient(135deg, #9333ea 0%, #c084fc 100%)",
    "linear-gradient(135deg, #0284c7 0%, #38bdf8 100%)",
  ]
  let hash = 0
  for (let i = 0; i < (id || "").length; i++) {
    hash = (hash << 5) - hash + id.charCodeAt(i)
    hash |= 0
  }
  return gradients[Math.abs(hash) % gradients.length]
}

// 时间格式化
function formatTime(val: string | null | undefined): string {
  if (!val) return ""
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
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
  } catch {
    return val
  }
}

export default function Director2Home({ csrfToken }: HomeContext) {
  const navigate = useNavigate()

  const [projects, setProjects] = useState<Director2Project[]>([])
  const [loading, setLoading] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState("")

  const [createModalVisible, setCreateModalVisible] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createForm, setCreateForm] = useState({ name: "", description: "", aspectRatio: "16:9" })

  const [editModalVisible, setEditModalVisible] = useState(false)
  const [updating, setUpdating] = useState(false)
  const [editForm, setEditForm] = useState({ id: "", name: "", description: "" })

  const filteredProjects = useMemo(() => {
    const kw = (searchKeyword || "").trim().toLowerCase()
    if (!kw) return projects
    return projects.filter(
      (p) =>
        (p.name && p.name.toLowerCase().includes(kw)) ||
        (p.description && p.description.toLowerCase().includes(kw)),
    )
  }, [projects, searchKeyword])

  const fetchProjects = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listProjects()
      setProjects(Array.isArray(data) ? data : [])
    } catch (err) {
      message.error(director2ErrorDetail(err, "加载项目列表失败"))
    } finally {
      setLoading(false)
    }
  }, [])

  function goToProject(id: string) {
    navigate(director2ProjectPath(id, "content"))
  }

  function openCreateModal() {
    setCreateForm({ name: "", description: "", aspectRatio: "16:9" })
    setCreateModalVisible(true)
  }

  // 提交创建
  async function handleCreateSubmit() {
    const name = createForm.name.trim()
    if (!name) {
      message.warning("请输入项目名称")
      return
    }
    setCreating(true)
    try {
      await createProject(csrfToken, {
        name,
        description: createForm.description.trim(),
        settings: { aspectRatio: createForm.aspectRatio },
      })
      message.success("项目创建成功")
      setCreateModalVisible(false)
      await fetchProjects()
    } catch (err) {
      message.error(director2ErrorDetail(err, "创建项目失败"))
    } finally {
      setCreating(false)
    }
  }

  // 提交编辑
  async function handleEditSubmit() {
    const name = editForm.name.trim()
    if (!name) {
      message.warning("项目名称不能为空")
      return
    }
    setUpdating(true)
    try {
      await updateProject(csrfToken, editForm.id, {
        name,
        description: editForm.description.trim(),
      })
      message.success("项目信息已更新")
      setEditModalVisible(false)
      await fetchProjects()
    } catch (err) {
      message.error(director2ErrorDetail(err, "更新项目失败"))
    } finally {
      setUpdating(false)
    }
  }

  // 删除项目
  async function handleDeleteProject(id: string) {
    try {
      await deleteProject(csrfToken, id)
      message.success("项目已删除")
      await fetchProjects()
    } catch (err) {
      message.error(director2ErrorDetail(err, "删除项目失败"))
    }
  }

  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  return (
    <div className="home-projects-container">
      <div className="home-projects-content">
        {/* 顶部标题与操作栏 */}
        <div className="page-header">
          <div className="header-left">
            <div className="header-title-row">
              <h1 className="page-title">创作项目</h1>
              <span className="project-count-badge">{filteredProjects.length} 个项目</span>
            </div>
            <p className="page-subtitle">统一管理剧本创作、分镜生成、AI生图与视频资产。</p>
          </div>

          <div className="header-actions">
            <Input
              value={searchKeyword}
              onChange={(event) => setSearchKeyword(event.target.value)}
              placeholder="搜索项目名称或简介..."
              allowClear
              className="search-input"
              prefix={<Search size={16} className="search-icon" />}
            />

            <Button type="primary" size="large" className="create-btn" onClick={openCreateModal}>
              <Plus size={18} />
              新建项目
            </Button>
          </div>
        </div>

        {/* 加载中状态 */}
        {loading ? (
          <div className="loading-box">
            <Spin size="large" tip="正在加载项目列表..." />
          </div>
        ) : filteredProjects.length === 0 ? (
          // 空状态
          <div className="empty-box">
            <div className="empty-icon-wrap">
              <FolderPlus size={48} className="empty-icon" />
            </div>
            <h3 className="empty-title">
              {searchKeyword ? "未找到匹配的项目" : "还没有任何创作项目"}
            </h3>
            <p className="empty-desc">
              {searchKeyword
                ? "请尝试更换搜索关键字"
                : "立即创建您的第一个 AI 媒体创作项目，开启剧本与视频生成"}
            </p>
            <Button type="primary" className="empty-create-btn" onClick={openCreateModal}>
              <Plus size={16} />
              创建新项目
            </Button>
          </div>
        ) : (
          // 项目卡片网格
          <div className="projects-grid">
            {filteredProjects.map((proj) => (
              <div key={proj.id} className="project-card" onClick={() => goToProject(proj.id)}>
                {/* 卡片头部背景封面 */}
                <div className="card-cover" style={{ background: coverBackground(proj.id) }}>
                  <div className="cover-badge">
                    <span className="status-dot" />
                    {proj.status === "archived" ? "已归档" : "进行中"}
                  </div>
                  <div className="cover-icon-bg">
                    <Film size={28} />
                  </div>
                </div>

                {/* 卡片主体信息 */}
                <div className="card-body">
                  <h3 className="project-name" title={proj.name}>
                    {proj.name}
                  </h3>
                  <p className="project-desc" title={proj.description || "暂无项目简介"}>
                    {proj.description || "暂无项目简介"}
                  </p>

                  <div className="project-meta">
                    <span className="meta-item">
                      <Clock size={13} />
                      {formatTime(proj.updated_at)}
                    </span>
                  </div>
                </div>

                {/* 卡片操作底栏 */}
                <div className="card-footer">
                  <Button
                    type="link"
                    size="small"
                    className="footer-btn enter-btn"
                    onClick={(event) => {
                      event.stopPropagation()
                      goToProject(proj.id)
                    }}
                  >
                    <ArrowRight size={14} />
                    进入项目
                  </Button>

                  <Button
                    type="link"
                    size="small"
                    className="footer-btn edit-btn"
                    onClick={(event) => {
                      event.stopPropagation()
                      setEditForm({ id: proj.id, name: proj.name, description: proj.description || "" })
                      setEditModalVisible(true)
                    }}
                  >
                    <Edit3 size={14} />
                    编辑
                  </Button>

                  <Popconfirm
                    title="确定要删除该项目吗？"
                    description="删除后项目配置与相关资产将无法恢复。"
                    okText="确认删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => handleDeleteProject(proj.id)}
                  >
                    <Button
                      type="link"
                      size="small"
                      danger
                      className="footer-btn delete-btn"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <Trash2 size={14} />
                      删除
                    </Button>
                  </Popconfirm>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 创建项目 Modal */}
      <Modal
        className="director2-app d2-modal-scope"
        open={createModalVisible}
        title="新建创作项目"
        confirmLoading={creating}
        okText="立即创建"
        cancelText="取消"
        width={520}
        destroyOnClose
        onOk={handleCreateSubmit}
        onCancel={() => setCreateModalVisible(false)}
      >
        <div className="modal-form">
          <div className="d2-form">
            <div className="d2-form-item">
              <label className="d2-form-label">
                <span className="d2-required">项目名称</span>
              </label>
              <Input
                value={createForm.name}
                onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })}
                placeholder="例如：赛博朋克短剧《星际引力》"
                maxLength={100}
                showCount
                autoFocus
                onPressEnter={handleCreateSubmit}
              />
            </div>

            <div className="d2-form-item">
              <label className="d2-form-label">项目描述 / 简介</label>
              <Input.TextArea
                value={createForm.description}
                onChange={(event) => setCreateForm({ ...createForm, description: event.target.value })}
                placeholder="简要描述项目的创作主题、剧本概要或生成目标（选填）..."
                rows={3}
                maxLength={300}
                showCount
              />
            </div>

            <div className="d2-form-item">
              <label className="d2-form-label">画幅与创作规格</label>
              <div className="preset-specs">
                {PRESET_SPECS.map((spec) => (
                  <div
                    key={spec.id}
                    className={`spec-tag${createForm.aspectRatio === spec.id ? " active" : ""}`}
                    onClick={() => setCreateForm({ ...createForm, aspectRatio: spec.id })}
                  >
                    <span className="spec-ratio">{spec.ratio}</span>
                    <span className="spec-label">{spec.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </Modal>

      {/* 编辑项目 Modal */}
      <Modal
        className="director2-app d2-modal-scope"
        open={editModalVisible}
        title="编辑项目信息"
        confirmLoading={updating}
        okText="保存修改"
        cancelText="取消"
        width={520}
        destroyOnClose
        onOk={handleEditSubmit}
        onCancel={() => setEditModalVisible(false)}
      >
        <div className="modal-form">
          <div className="d2-form">
            <div className="d2-form-item">
              <label className="d2-form-label">
                <span className="d2-required">项目名称</span>
              </label>
              <Input
                value={editForm.name}
                onChange={(event) => setEditForm({ ...editForm, name: event.target.value })}
                placeholder="请输入项目名称"
                maxLength={100}
                showCount
                onPressEnter={handleEditSubmit}
              />
            </div>

            <div className="d2-form-item">
              <label className="d2-form-label">项目描述 / 简介</label>
              <Input.TextArea
                value={editForm.description}
                onChange={(event) => setEditForm({ ...editForm, description: event.target.value })}
                placeholder="简要描述项目的创作主题或剧本概要..."
                rows={3}
                maxLength={300}
                showCount
              />
            </div>
          </div>
        </div>
      </Modal>
    </div>
  )
}
