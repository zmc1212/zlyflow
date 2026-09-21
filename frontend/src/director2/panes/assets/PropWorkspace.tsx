// 道具专属工作区：一张 16:9 设定板（左三视 / 右上材质 / 右下细节），交互对齐角色造型卡。
import { Button, Col, Form, Input, Row, Select } from "antd"
import { Edit3, Maximize2, Package, Sparkles, Trash2, Upload } from "lucide-react"
import type { Director2Asset } from "../../api"
import { hasSourceReferences } from "../../asset-source-references"
import { useMediaPreview } from "../../media-preview"
import { copyText, getPropTypeLabel, PROP_TYPE_OPTIONS } from "./shared"
import AssetSourceReferenceStrip from "./AssetSourceReferenceStrip"

interface PropWorkspaceProps {
  asset: Director2Asset
  onFieldChange: (patch: Partial<Director2Asset>) => void
  onExtraChange: (patch: Record<string, any>) => void
  generatingProp: boolean
  onGenerateReference: () => void
  onDeletePropImage: (slot: "reference" | "turnaround" | "detail") => void
  onManualUrl: (target: string) => void
  onOpenEditProp: () => void
  uploadingSourceRef: boolean
  inferringSourcePrompts?: boolean
  onUploadSourceRefs: (files: File[]) => void
  onRemoveSourceRef: (refId: string) => void
  onInferSourcePrompts?: () => void
}

export default function PropWorkspace({
  asset,
  onFieldChange,
  onExtraChange,
  generatingProp,
  onGenerateReference,
  onDeletePropImage,
  onManualUrl,
  onOpenEditProp,
  uploadingSourceRef,
  inferringSourcePrompts,
  onUploadSourceRefs,
  onRemoveSourceRef,
  onInferSourcePrompts,
}: PropWorkspaceProps) {
  const { openMediaPreview } = useMediaPreview()
  const sheetUrl = String(asset.extra?.reference_url || asset.image_url || "").trim()
  const turnaroundUrl = String(asset.extra?.turnaround_url || "").trim()
  const detailUrl = String(asset.extra?.detail_url || "").trim()

  return (
    <div className="prop-workspace-layout">
      <div className="section-card">
        <div className="section-header prop-header-row">
          <div className="section-title-wrap">
            <div className="section-icon-badge prop-badge">
              <Package size={16} />
            </div>
            <div>
              <div className="title-with-badge">
                <h4 className="section-title">{asset.name}</h4>
                <span className="meta-chip type-chip prop-chip">
                  {getPropTypeLabel(asset.extra?.prop_type)}
                </span>
                <span className={`meta-chip${sheetUrl ? " ok" : ""}`}>
                  设定板: {sheetUrl ? "已生成" : "缺失"}
                </span>
              </div>
              {asset.extra?.owner || asset.role ? (
                <div className="owner-indicator">
                  归属人 (Owner)：<span className="owner-name">{asset.extra?.owner || asset.role}</span>
                </div>
              ) : null}
              <p className="section-desc">
                {asset.description
                  || "一张 16:9 道具设定板：左为正 / 3/4 / 背，右上材质结构，右下标志细节。出片只锁外形与材质，不把分格抄进镜头。"}
              </p>
            </div>
          </div>

          <div className="header-right-actions">
            <Button size="small" className="slot-btn header-edit-btn" icon={<Edit3 size={12} />} onClick={onOpenEditProp}>
              编辑道具
            </Button>
          </div>
        </div>

        <div className="ident-card-body prop-sheet-body">
          <div className="ident-image-col">
            <div className="ident-img-frame">
              {sheetUrl ? (
                <img
                  src={sheetUrl}
                  className="ident-img-view"
                  alt={`${asset.name} 设定板`}
                  onClick={() => openMediaPreview({ src: sheetUrl, title: `${asset.name} 道具设定板` })}
                />
              ) : (
                <div className="ident-img-empty">
                  <Package size={28} className="empty-shirt-icon" />
                  <span className="empty-shirt-text">尚未生成设定板</span>
                </div>
              )}

              {sheetUrl ? (
                <button
                  type="button"
                  className="float-view-btn"
                  title="放大查看"
                  aria-label={`放大查看${asset.name}设定板`}
                  onClick={() => openMediaPreview({ src: sheetUrl, title: `${asset.name} 道具设定板` })}
                >
                  <Maximize2 size={13} />
                </button>
              ) : null}

              {sheetUrl ? (
                <div className="slot-actions-bar">
                  <button
                    type="button"
                    className="slot-icon-btn delete-btn"
                    title="删除设定板"
                    onClick={(event) => {
                      event.stopPropagation()
                      onDeletePropImage("reference")
                    }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ) : null}
            </div>

            <div className="slot-actions-row">
              <Button
                size="small"
                className="slot-btn"
                icon={<Upload size={12} />}
                onClick={() => onManualUrl("prop_reference")}
              >
                上传设定板
              </Button>
              <Button
                type="primary"
                className="ident-gen-btn"
                loading={generatingProp}
                icon={<Sparkles size={14} />}
                onClick={onGenerateReference}
              >
                {sheetUrl ? "重新生成设定板" : "生成设定板"}
              </Button>
            </div>
            {hasSourceReferences(asset) ? (
              <span className="avatar-ref-hint">将按原片截图的外形与材质生成，忽略下方旧外观描述</span>
            ) : null}
            <AssetSourceReferenceStrip
              asset={asset}
              uploading={uploadingSourceRef}
              inferring={inferringSourcePrompts}
              onUpload={onUploadSourceRefs}
              onRemove={onRemoveSourceRef}
              onInferPrompts={onInferSourcePrompts}
            />
            {turnaroundUrl || detailUrl ? (
              <div className="prop-legacy-thumbs">
                {turnaroundUrl ? (
                  <button
                    type="button"
                    className="prop-legacy-thumb"
                    title="历史三视图（仅回退预览）"
                    onClick={() => openMediaPreview({ src: turnaroundUrl, title: `${asset.name} 历史三视图` })}
                  >
                    <img src={turnaroundUrl} alt="历史三视图" />
                    <span>历史三视图</span>
                  </button>
                ) : null}
                {detailUrl ? (
                  <button
                    type="button"
                    className="prop-legacy-thumb"
                    title="历史细节图（仅回退预览）"
                    onClick={() => openMediaPreview({ src: detailUrl, title: `${asset.name} 历史细节图` })}
                  >
                    <img src={detailUrl} alt="历史细节图" />
                    <span>历史细节图</span>
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="ident-info-col">
            <div className="ident-field">
              <div className="field-title-bar">
                <label className="ident-field-label">外形与材质 (Appearance)</label>
                <Button
                  type="link"
                  size="small"
                  className="mini-link-btn"
                  onClick={() => copyText(asset.extra?.visual_prompt || asset.visual_prompt)}
                >
                  复制
                </Button>
              </div>
              {asset.extra ? (
                <Input.TextArea
                  value={asset.extra.visual_prompt}
                  rows={4}
                  placeholder="描述主体外形、材质包浆、使用痕迹与标志细节..."
                  className="custom-textarea"
                  onChange={(event) => onExtraChange({ visual_prompt: event.target.value })}
                />
              ) : null}
            </div>
          </div>
        </div>
      </div>

      <div className="section-card">
        <div className="field-title-bar" style={{ marginBottom: 12 }}>
          <h4 className="section-title">道具属性、所属角色与剧本出处</h4>
        </div>
        <Row gutter={14}>
          <Col span={8}>
            <Form.Item label="道具名称" required>
              <Input value={asset.name} placeholder="例如：旧木书箱" onChange={(event) => onFieldChange({ name: event.target.value })} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item label="所属角色 (Owner)">
              {asset.extra ? (
                <Input
                  value={asset.extra.owner}
                  placeholder="例如：沈砚 专属信物"
                  onChange={(event) => onExtraChange({ owner: event.target.value })}
                />
              ) : (
                <Input
                  value={asset.role ?? ""}
                  placeholder="例如：沈砚 专属信物"
                  onChange={(event) => onFieldChange({ role: event.target.value })}
                />
              )}
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item label="道具类型 (Prop Type)">
              {asset.extra ? (
                <Select value={asset.extra.prop_type} options={PROP_TYPE_OPTIONS} onChange={(value) => onExtraChange({ prop_type: value })} />
              ) : null}
            </Form.Item>
          </Col>
        </Row>

        <Form.Item label="道具背景故事与剧本出处描述">
          <Input.TextArea
            value={asset.description ?? ""}
            rows={3}
            placeholder="记录该道具在剧本故事中的起源、象征意义或重要剧情推动作用..."
            onChange={(event) => onFieldChange({ description: event.target.value })}
          />
        </Form.Item>
      </div>
    </div>
  )
}
