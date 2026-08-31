import { useRef } from "react"
import { Button, Card, Empty, Popconfirm, Space, Spin, Tag, Typography } from "antd"
import { ArrowLeft, Clapperboard, Copy, Layers, Plus, Trash2, Wand2 } from "lucide-react"
import ThemeToggle from "../components/ThemeToggle"
import { DirectorProjectListItem, DirectorGenerationStatus, DirectorPayloadKind } from "./director-api"

const CARD_OPEN_SUPPRESS_MS = 400

function generationLabel(status: DirectorGenerationStatus): { text: string; color: string } {
  if (status === "complete") return { text: "已完成", color: "success" }
  if (status === "partial") return { text: "部分完成", color: "warning" }
  return { text: "待生成", color: "default" }
}

function kindLabel(kind: DirectorPayloadKind): { text: string; color: string } {
  if (kind === "director_recipe") return { text: "导演创作", color: "blue" }
  if (kind === "batch_run") return { text: "短视频批量", color: "purple" }
  return { text: "旧时间轴", color: "default" }
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
}

interface DirectorHomeProps {
  items: DirectorProjectListItem[]
  loading: boolean
  onCreateDirector: () => void
  onCreateBatch: () => void
  onOpen: (item: DirectorProjectListItem) => void
  onCopy: (projectId: string) => void
  onDelete: (projectId: string) => void
  onExitDirector?: () => void
}

export default function DirectorHome({
  items,
  loading,
  onCreateDirector,
  onCreateBatch,
  onOpen,
  onCopy,
  onDelete,
  onExitDirector,
}: DirectorHomeProps) {
  const suppressOpenUntilRef = useRef(0)

  function suppressCardOpen() {
    suppressOpenUntilRef.current = Date.now() + CARD_OPEN_SUPPRESS_MS
  }

  function openProject(item: DirectorProjectListItem) {
    if (Date.now() < suppressOpenUntilRef.current) return
    onOpen(item)
  }

  return (
    <div className="director-library">
      <header className="director-mobile-header">
        <button type="button" aria-label="返回创作工作台" onClick={onExitDirector}><ArrowLeft size={20} /></button>
        <strong>导演台</strong>
        <div className="director-mobile-header-actions">
          <ThemeToggle />
          <button type="button" aria-label="新建导演创作" onClick={onCreateDirector}><Plus size={20} /></button>
        </div>
      </header>

      <header className="director-library-header">
        <div>
          <h1>导演台</h1>
          <p>一句话做完整短片，或按主题批量裂变多条 H3 文生视频。媒体仍走 GRS 定妆与本机 MiniMax H3。</p>
        </div>
        <ThemeToggle />
      </header>

      <div className="director-engine-grid">
        <button type="button" className="director-engine-card" onClick={onCreateDirector}>
          <span className="director-engine-icon"><Clapperboard size={22} /></span>
          <strong>导演创作</strong>
          <span>一句话 → 9 Agent Recipe → 人物/场景定妆 → 分镜出片</span>
        </button>
        <button type="button" className="director-engine-card" onClick={onCreateBatch}>
          <span className="director-engine-icon is-batch"><Layers size={22} /></span>
          <strong>短视频批量</strong>
          <span>主题裂变多条脚本，并行排队 MiniMax H3 文生视频</span>
        </button>
      </div>

      {loading ? (
        <div className="director-library-loading"><Spin /><span>正在加载工程</span></div>
      ) : items.length === 0 ? (
        <div className="director-library-empty">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div className="director-library-empty-copy">
                <strong>还没有导演工程</strong>
                <span>从导演创作或短视频批量开始。旧时间轴工程仍可打开并转为 Recipe。</span>
              </div>
            }
          >
            <Space>
              <Button icon={<Wand2 size={15} />} onClick={onCreateDirector}>导演创作</Button>
              <Button onClick={onCreateBatch}>短视频批量</Button>
            </Space>
          </Empty>
        </div>
      ) : (
        <div className="director-library-grid">
          {items.map((item) => {
            const gen = generationLabel(item.generation_status)
            const kind = kindLabel(item.kind)
            return (
              <Card
                key={item.id}
                className="director-library-card"
                hoverable
                actions={[
                  <span key="copy" onClick={(event) => event.stopPropagation()} onMouseDown={(event) => event.stopPropagation()}>
                    <button type="button" className="director-library-card-action" onClick={() => onCopy(item.id)}>
                      <Copy size={14} />复制
                    </button>
                  </span>,
                  <span key="delete" onClick={(event) => event.stopPropagation()} onMouseDown={(event) => event.stopPropagation()}>
                    <Popconfirm
                      title="删除这个工程？"
                      description="工程文档会从服务器移除，已生成的视频任务仍保留在任务列表。"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onPopupClick={(event) => event.stopPropagation()}
                      onOpenChange={(open) => { if (!open) suppressCardOpen() }}
                      onConfirm={(event) => {
                        event?.stopPropagation()
                        suppressCardOpen()
                        onDelete(item.id)
                      }}
                      onCancel={(event) => {
                        event?.stopPropagation()
                        suppressCardOpen()
                      }}
                    >
                      <button type="button" className="director-library-card-action is-danger" onClick={(event) => event.stopPropagation()}>
                        <Trash2 size={14} />删除
                      </button>
                    </Popconfirm>
                  </span>,
                ]}
              >
                <button
                  type="button"
                  className="director-library-card-main"
                  onClick={() => openProject(item)}
                  aria-label={`打开工程 ${item.title}`}
                >
                  <div className="director-library-card-top">
                    {item.kind === "batch_run" ? <Layers size={16} /> : <Clapperboard size={16} />}
                    <Typography.Text strong className="director-library-card-title" ellipsis>
                      {item.title}
                    </Typography.Text>
                  </div>
                  <p className="director-library-card-summary">{item.summary || "暂无梗概"}</p>
                  <div className="director-library-card-meta">
                    <Tag color={kind.color}>{kind.text}</Tag>
                    <Tag color={gen.color}>{gen.text}</Tag>
                    <Tag>{item.shot_count} 镜</Tag>
                  </div>
                  <div className="director-library-card-updated">{formatUpdatedAt(item.updated_at)}</div>
                </button>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
