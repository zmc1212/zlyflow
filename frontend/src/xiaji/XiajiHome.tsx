import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button, Card, Empty, Input, Modal, Popconfirm, Space, Spin, Typography, message } from "antd"
import { ArrowLeft, FolderPlus, Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import ThemeToggle from "../components/ThemeToggle"
import { director2ProjectPath, PATHS } from "../paths"
import { createXiajiProject, deleteXiajiProject, listXiajiProjects, type XiajiProject } from "./xiaji-api"

function formatUpdatedAt(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
}

export default function XiajiHome({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState("")
  const listQuery = useQuery({ queryKey: ["xiaji-projects"], queryFn: listXiajiProjects })

  const createMutation = useMutation({
    mutationFn: () => createXiajiProject(csrfToken, name.trim() || "未命名项目"),
    onSuccess: (project) => {
      setCreateOpen(false)
      setName("")
      void queryClient.invalidateQueries({ queryKey: ["xiaji-projects"] })
      navigate(director2ProjectPath(project.id))
    },
    onError: (error: Error) => message.error(error.message),
  })

  const deleteMutation = useMutation({
    mutationFn: (projectId: string) => deleteXiajiProject(csrfToken, projectId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["xiaji-projects"] })
    },
  })

  const items = listQuery.data ?? []

  return (
    <div className="director-library xiaji-home">
      <header className="director-mobile-header">
        <button type="button" aria-label="返回创作工作台" onClick={() => navigate(PATHS.generateVideo)}>
          <ArrowLeft size={20} />
        </button>
        <strong>导台2</strong>
        <div className="director-mobile-header-actions">
          <ThemeToggle />
          <button type="button" aria-label="新建项目" onClick={() => setCreateOpen(true)}>
            <Plus size={20} />
          </button>
        </div>
      </header>

      <header className="director-library-header">
        <div>
          <h1>导台2 项目</h1>
          <p>先新建或打开项目。内容库、资产库、剧集工坊、风格中心和制作助手都挂在同一个项目下。</p>
        </div>
        <Space>
          <ThemeToggle />
          <Button type="primary" icon={<FolderPlus size={15} />} onClick={() => setCreateOpen(true)}>
            新建项目
          </Button>
        </Space>
      </header>

      {listQuery.isLoading ? (
        <div className="director-library-loading">
          <Spin />
          <span>正在加载项目</span>
        </div>
      ) : items.length === 0 ? (
        <div className="director-library-empty">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div className="director-library-empty-copy">
                <strong>还没有导台2 项目</strong>
                <span>新建后即可导入剧本、沉淀资产，并进入后续工坊模块。</span>
              </div>
            }
          >
            <Button type="primary" icon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
              新建项目
            </Button>
          </Empty>
        </div>
      ) : (
        <div className="director-library-grid">
          {items.map((item: XiajiProject) => (
            <Card
              key={item.id}
              className="director-library-card"
              hoverable
              actions={[
                <Popconfirm
                  key="delete"
                  title="删除这个项目？"
                  description="内容库文档和资产会一并删除。"
                  okText="删除"
                  cancelText="取消"
                  onConfirm={() => deleteMutation.mutate(item.id)}
                >
                  <button type="button" className="xiaji-home-card-action" onClick={(event) => event.stopPropagation()}>
                    <Trash2 size={14} /> 删除
                  </button>
                </Popconfirm>,
              ]}
            >
              <button type="button" className="director-library-card-main" onClick={() => navigate(director2ProjectPath(item.id))}>
                <div className="director-library-card-top">
                  <Typography.Title level={5} className="director-library-card-title">
                    {item.name}
                  </Typography.Title>
                </div>
                <p className="director-library-card-summary">内容库 · 资产库 · 剧集工坊 · 风格中心 · 制作助手</p>
                <span className="director-library-card-updated">更新于 {formatUpdatedAt(item.updated_at)}</span>
              </button>
            </Card>
          ))}
        </div>
      )}

      <Modal
        title="新建导台2 项目"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createMutation.mutate()}
        confirmLoading={createMutation.isPending}
        okText="创建并打开"
        destroyOnClose
      >
        <Input
          autoFocus
          placeholder="项目名称，例如剧名"
          value={name}
          onChange={(event) => setName(event.target.value)}
          onPressEnter={() => createMutation.mutate()}
        />
      </Modal>
    </div>
  )
}
