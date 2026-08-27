import { Button, Card, Dropdown, Empty, Popconfirm, Space, Spin, Tag, Typography } from "antd"
import { ArrowLeft, Clapperboard, Copy, FolderPlus, Plus, Trash2, Wand2 } from "lucide-react"
import { DirectorProjectListItem, DirectorGenerationStatus } from "./director-api"

function generationLabel(status: DirectorGenerationStatus): { text: string; color: string } {
  if (status === "complete") return { text: "已完成", color: "success" }
  if (status === "partial") return { text: "部分完成", color: "warning" }
  return { text: "待生成", color: "default" }
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
}

interface DirectorProjectLibraryProps {
  items: DirectorProjectListItem[]
  loading: boolean
  onCreateBlank: () => void
  onCreateFromScript: () => void
  onCreateExample: () => void
  onOpen: (projectId: string) => void
  onCopy: (projectId: string) => void
  onDelete: (projectId: string) => void
  onExitDirector?: () => void
}

export default function DirectorProjectLibrary({
  items,
  loading,
  onCreateBlank,
  onCreateFromScript,
  onCreateExample,
  onOpen,
  onCopy,
  onDelete,
  onExitDirector,
}: DirectorProjectLibraryProps) {
  return (
    <div className="director-library">
      <header className="director-mobile-header">
        <button type="button" aria-label="返回创作工作台" onClick={onExitDirector}><ArrowLeft size={20} /></button>
        <strong>项目库</strong>
        <Dropdown
          trigger={["click"]}
          menu={{
            items: [
              { key: "blank", label: "新建空白工程", icon: <Plus size={14} />, onClick: onCreateBlank },
              { key: "script", label: "从剧本创建", icon: <Wand2 size={14} />, onClick: onCreateFromScript },
            ],
          }}
        >
          <button type="button" aria-label="新建工程"><Plus size={20} /></button>
        </Dropdown>
      </header>

      <header className="director-library-header">
        <div>
          <h1>项目库</h1>
          <p>先选择或创建工程，再进入时间轴。剧本原文会随工程一起保存。</p>
        </div>
        <Space wrap>
          <Button icon={<Wand2 size={15} />} onClick={onCreateFromScript}>从剧本创建</Button>
          <Button type="primary" icon={<Plus size={15} />} onClick={onCreateBlank} className="director-primary-button">
            新建空白工程
          </Button>
        </Space>
      </header>

      {loading ? (
        <div className="director-library-loading"><Spin /><span>正在加载工程</span></div>
      ) : items.length === 0 ? (
        <div className="director-library-empty">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div className="director-library-empty-copy">
                <strong>还没有导演工程</strong>
                <span>从空白时间轴开始，或让 AI 按剧本拆出分镜。不再预置三条演示镜头。</span>
              </div>
            }
          >
            <Space wrap>
              <Button type="primary" icon={<Plus size={15} />} onClick={onCreateBlank} className="director-primary-button">新建空白工程</Button>
              <Button icon={<Wand2 size={15} />} onClick={onCreateFromScript}>从剧本创建</Button>
              <Button icon={<Clapperboard size={15} />} onClick={onCreateExample}>用示例创建</Button>
            </Space>
          </Empty>
        </div>
      ) : (
        <div className="director-library-grid">
          {items.map((item) => {
            const progress = generationLabel(item.generation_status)
            return (
              <Card
                key={item.id}
                hoverable
                className="director-library-card"
                onClick={() => onOpen(item.id)}
                actions={[
                  <span key="open" onClick={(event) => event.stopPropagation()}>
                    <button type="button" className="director-library-card-action" onClick={() => onOpen(item.id)}>打开</button>
                  </span>,
                  <span key="copy" onClick={(event) => event.stopPropagation()}>
                    <button type="button" className="director-library-card-action" onClick={() => onCopy(item.id)}><Copy size={13} /> 复制</button>
                  </span>,
                  <span key="delete" onClick={(event) => event.stopPropagation()}>
                    <Popconfirm
                      title="删除这个工程？"
                      description="分镜、原文和生成记录会从项目库移除，不可恢复。"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => onDelete(item.id)}
                    >
                      <button type="button" className="director-library-card-action is-danger"><Trash2 size={13} /> 删除</button>
                    </Popconfirm>
                  </span>,
                ]}
              >
                <div className="director-library-card-top">
                  <FolderPlus size={16} />
                  <Typography.Title level={5} ellipsis={{ tooltip: item.title }} className="director-library-card-title">
                    {item.title}
                  </Typography.Title>
                </div>
                <p className="director-library-card-summary">{item.summary?.trim() || "尚未填写梗概"}</p>
                <div className="director-library-card-meta">
                  <Tag>{item.shot_count} 镜</Tag>
                  <Tag color={item.has_source_script ? "blue" : "default"}>{item.has_source_script ? "有原文" : "无原文"}</Tag>
                  <Tag color={progress.color}>{progress.text}</Tag>
                </div>
                <div className="director-library-card-updated">更新于 {formatUpdatedAt(item.updated_at)}</div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
