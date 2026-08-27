import { Button, Input, Modal, Select, Tag, Tooltip, message } from "antd"
import {
  Archive,
  Check,
  Clapperboard,
  Copy,
  Download,
  ExternalLink,
  FileCode,
  FolderOpen,
  Image as ImageIcon,
  Play,
  Trash2,
  Video,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import {
  downloadJianyingJsonFiles,
  exportJianyingDraftZip,
  JianyingDraftOptions,
  JianyingMediaItem,
} from "./jianying-draft-builder"

export interface JianyingExportModalProps {
  open: boolean
  onClose: () => void
  items: JianyingMediaItem[]
  onRemoveItem?: (id: string) => void
  defaultAspectRatio?: JianyingDraftOptions["aspectRatio"]
}

const JIANYING_WINDOWS_DRAFT_PATH = `%LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\com.lveditor.draft\\`

export default function JianyingExportModal({
  open,
  onClose,
  items,
  onRemoveItem,
  defaultAspectRatio = "16:9",
}: JianyingExportModalProps) {
  const [draftName, setDraftName] = useState(() => {
    const d = new Date()
    const pad = (n: number) => String(n).padStart(2, "0")
    return `ZLY_剪映草稿_${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}`
  })
  const [aspectRatio, setAspectRatio] = useState<JianyingDraftOptions["aspectRatio"]>(defaultAspectRatio)
  const [exportingZip, setExportingZip] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    setAspectRatio(defaultAspectRatio)
  }, [defaultAspectRatio])

  const selectedItems = useMemo(() => items, [items])

  const totalDurationSeconds = useMemo(() => {
    return selectedItems.reduce((acc, item) => {
      const dur = item.durationSeconds && item.durationSeconds > 0
        ? item.durationSeconds
        : item.kind === "image" ? 3.0 : 5.0
      return acc + dur
    }, 0)
  }, [selectedItems])

  const handleExportZip = async () => {
    if (!selectedItems.length) {
      message.warning("请至少保留一个素材以导出草稿")
      return
    }
    setExportingZip(true)
    try {
      await exportJianyingDraftZip(selectedItems, {
        draftName: draftName.trim() || "ZLY_Studio_草稿",
        aspectRatio,
      })
      message.success("已生成并下载剪映草稿包 (.zip)")
    } catch (err) {
      const msg = err instanceof Error ? err.message : "导出失败"
      message.error(`导出草稿失败: ${msg}`)
    } finally {
      setExportingZip(false)
    }
  }

  const handleDownloadJson = () => {
    if (!selectedItems.length) {
      message.warning("请至少保留一个素材以导出草稿")
      return
    }
    try {
      downloadJianyingJsonFiles(selectedItems, {
        draftName: draftName.trim() || "ZLY_Studio_草稿",
        aspectRatio,
      })
      message.success("已下载 draft_content.json 与 draft_meta_info.json")
    } catch (err) {
      const msg = err instanceof Error ? err.message : "下载失败"
      message.error(`下载草稿文件失败: ${msg}`)
    }
  }

  const handleDownloadAllMedia = () => {
    if (!selectedItems.length) {
      message.warning("无可下载素材")
      return
    }
    selectedItems.forEach((item, index) => {
      setTimeout(() => {
        const a = document.createElement("a")
        a.href = item.url
        a.download = item.title || `asset_${index + 1}.${item.kind === "image" ? "png" : "mp4"}`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
      }, index * 200)
    })
    message.success(`已触发 ${selectedItems.length} 个素材文件的下载`)
  }

  const handleCopyPath = async () => {
    try {
      await navigator.clipboard.writeText(JIANYING_WINDOWS_DRAFT_PATH)
      setCopied(true)
      message.success("已复制剪映草稿路径到剪贴板")
      setTimeout(() => setCopied(false), 2500)
    } catch {
      message.info(`剪映草稿路径: ${JIANYING_WINDOWS_DRAFT_PATH}`)
    }
  }

  const handleLaunchJianyingApp = () => {
    window.location.href = "jianying://"
    message.info("正在尝试唤起剪映电脑版客户端...")
  }

  const handleOpenJianyingWeb = () => {
    window.open("https://www.capcut.cn/editor", "_blank")
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={
        <div className="flex items-center gap-2 text-base font-semibold text-[#111827]">
          <div className="grid size-7 place-items-center rounded-lg bg-[#4d6bfe]/10 text-[#4d6bfe]">
            <Clapperboard size={16} />
          </div>
          <span>导出到剪映 / 快捷剪辑</span>
        </div>
      }
      width={680}
      footer={null}
      destroyOnClose
      centered
      className="jianying-export-modal"
    >
      <div className="mt-4 space-y-5 text-sm text-[#374151]">
        {/* 草稿参数配置 */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[#4b5563]">
              草稿工程名称
            </label>
            <Input
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              placeholder="输入草稿工程名称"
              className="rounded-lg"
              maxLength={64}
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[#4b5563]">
              画幅比例
            </label>
            <Select
              value={aspectRatio}
              onChange={setAspectRatio}
              className="w-full"
              options={[
                { value: "16:9", label: "16:9 横屏 (1920 × 1080) - 影视/长视频" },
                { value: "9:16", label: "9:16 竖屏 (1080 × 1920) - 抖音/短视频" },
                { value: "1:1", label: "1:1 方形 (1080 × 1080) - 社交媒体" },
                { value: "4:3", label: "4:3 标清 (1440 × 1080) - 经典画幅" },
                { value: "21:9", label: "21:9 宽画幅 (2560 × 1080) - 电影感" },
              ]}
            />
          </div>
        </div>

        {/* 选中的素材列表 */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium text-[#4b5563]">
              包含素材 ({selectedItems.length} 项 · 预估总时长约 {totalDurationSeconds.toFixed(1)} 秒)
            </span>
            {selectedItems.length > 0 && (
              <Button
                type="link"
                size="small"
                icon={<Download size={13} />}
                onClick={handleDownloadAllMedia}
                className="h-auto p-0 text-xs text-[#4d6bfe]"
              >
                下载全部素材文件
              </Button>
            )}
          </div>
          <div className="max-h-48 space-y-1.5 overflow-y-auto rounded-lg border border-black/[0.08] bg-[#f9fafb] p-2">
            {selectedItems.length === 0 ? (
              <div className="py-6 text-center text-xs text-[#9ca3af]">
                未选择任何素材，请返回资产库勾选素材后重试
              </div>
            ) : (
              selectedItems.map((item, idx) => (
                <div
                  key={item.id}
                  className="flex items-center gap-3 rounded-md bg-white p-1.5 pr-2.5 shadow-sm transition hover:bg-black/[0.02]"
                >
                  <span className="w-5 text-center text-xs font-mono text-[#9ca3af]">
                    {idx + 1}
                  </span>
                  <div className="relative size-10 shrink-0 overflow-hidden rounded bg-black/5">
                    {item.kind === "image" ? (
                      <img src={item.url} alt={item.title} className="h-full w-full object-cover" />
                    ) : (
                      <video src={item.url} className="h-full w-full object-cover" muted />
                    )}
                    <span className="absolute bottom-0 right-0 rounded-tl bg-black/60 px-1 py-0.5 text-[9px] text-white">
                      {item.kind === "image" ? "图" : "视"}
                    </span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-[#1f2937]">
                      {item.title || `素材_${idx + 1}`}
                    </p>
                    <p className="text-[11px] text-[#6b7280]">
                      {item.kind === "video" ? "视频片段" : "静态图片"} ·{" "}
                      {item.durationSeconds ? `${item.durationSeconds.toFixed(1)}s` : item.kind === "image" ? "3.0s" : "5.0s"}
                    </p>
                  </div>
                  {onRemoveItem && (
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<Trash2 size={13} />}
                      onClick={() => onRemoveItem(item.id)}
                      title="从导出列表中移除"
                      className="size-7"
                    />
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* 导出操作区域 */}
        <div className="rounded-xl border border-black/[0.06] bg-[#f8f9fa] p-3.5">
          <h4 className="mb-2.5 text-xs font-semibold text-[#111827]">
            导出剪映草稿
          </h4>
          <div className="flex flex-wrap items-center gap-2.5">
            <Button
              type="primary"
              icon={<Archive size={15} />}
              loading={exportingZip}
              onClick={handleExportZip}
              disabled={!selectedItems.length}
              className="bg-[#4d6bfe] hover:!bg-[#3b59e9]"
            >
              下载剪映草稿包 (.zip)
            </Button>
            <Button
              icon={<FileCode size={15} />}
              onClick={handleDownloadJson}
              disabled={!selectedItems.length}
            >
              仅下载草稿 JSON
            </Button>
          </div>
        </div>

        {/* 快捷直达与客户端联动 */}
        <div className="rounded-xl border border-black/[0.06] bg-[#f8f9fa] p-3.5">
          <h4 className="mb-2.5 text-xs font-semibold text-[#111827]">
            快速进入剪映
          </h4>
          <div className="flex flex-wrap items-center gap-2.5">
            <Button
              icon={<Play size={14} />}
              onClick={handleLaunchJianyingApp}
              className="border-[#4d6bfe]/30 text-[#4d6bfe] hover:!border-[#4d6bfe] hover:!text-[#3b59e9]"
            >
              启动剪映电脑客户端
            </Button>
            <Button
              icon={<ExternalLink size={14} />}
              onClick={handleOpenJianyingWeb}
            >
              打开剪映网页版
            </Button>
          </div>
        </div>

        {/* 剪映草稿路径说明指引 */}
        <div className="rounded-xl border border-dashed border-black/[0.12] bg-white p-3.5">
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-xs font-semibold text-[#111827]">
                💡 如何将导出的草稿导入剪映电脑版？
              </p>
              <ol className="mt-1.5 list-decimal space-y-1 pl-4 text-xs text-[#4b5563]">
                <li>下载并解压草稿 ZIP 包（文件夹包含 <code className="rounded bg-black/[0.05] px-1 text-[11px]">draft_content.json</code>）。</li>
                <li>将解压出的工程文件夹复制到剪映默认草稿目录：</li>
              </ol>
            </div>
          </div>
          <div className="mt-2 flex items-center justify-between gap-2 rounded-lg bg-[#f3f4f6] px-2.5 py-1.5 font-mono text-[11px] text-[#1f2937]">
            <span className="truncate">{JIANYING_WINDOWS_DRAFT_PATH}</span>
            <Button
              type="text"
              size="small"
              icon={copied ? <Check size={13} className="text-emerald-600" /> : <Copy size={13} />}
              onClick={handleCopyPath}
              className="shrink-0 text-xs text-[#4d6bfe]"
            >
              {copied ? "已复制" : "复制路径"}
            </Button>
          </div>
          <p className="mt-1.5 text-[11px] text-[#6b7280]">
            3. 打开剪映电脑版，主页即可直接看到该工程并进入时间线剪辑。
          </p>
        </div>
      </div>
    </Modal>
  )
}
