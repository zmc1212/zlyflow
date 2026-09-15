// 道具专属工作区（严格参考 source2 prop-asset-card：参考图 + 转面三视图 + 细节特写 + 属性卡）——
// 逐行复刻自 AssetsLibraryPane.vue 模板 C 区（v-else-if="selectedAsset.kind === 'prop'"）。
import { Button, Col, Form, Input, Row, Select } from "antd"
import { Edit3, Eye, Layers, Package, RefreshCw, Sparkles, Trash2, Upload } from "lucide-react"
import type { Director2Asset } from "../../api"
import { copyText, getPropTypeLabel, openImageLightbox, PROP_TYPE_OPTIONS } from "./shared"

interface PropWorkspaceProps {
  asset: Director2Asset
  onFieldChange: (patch: Partial<Director2Asset>) => void
  onExtraChange: (patch: Record<string, any>) => void
  generatingProp: boolean
  generatingPropTurnaround: boolean
  generatingPropDetail: boolean
  onGenerateReference: () => void
  onGenerateTurnaround: () => void
  onGenerateDetail: () => void
  onDeletePropImage: (slot: "reference" | "turnaround" | "detail") => void
  onManualUrl: (target: string) => void
  onOpenEditProp: () => void
}

export default function PropWorkspace({
  asset,
  onFieldChange,
  onExtraChange,
  generatingProp,
  generatingPropTurnaround,
  generatingPropDetail,
  onGenerateReference,
  onGenerateTurnaround,
  onGenerateDetail,
  onDeletePropImage,
  onManualUrl,
  onOpenEditProp,
}: PropWorkspaceProps) {
  return (
    <div className="prop-workspace-layout">
      <div className="section-card">
        {/* 道具头部：标题 + Meta Badges + Owner 归属 + 状态 Chips (与 source2 CardHeader 一致) */}
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
                <span className={`meta-chip${asset.extra?.reference_url || asset.image_url ? " ok" : ""}`}>
                  参考图: {asset.extra?.reference_url || asset.image_url ? "已生成" : "缺失"}
                </span>
                <span className={`meta-chip${asset.extra?.turnaround_url ? " ok" : ""}`}>
                  三视图: {asset.extra?.turnaround_url ? "已生成" : "缺失"}
                </span>
                <span className={`meta-chip${asset.extra?.detail_url ? " ok" : ""}`}>
                  细节特写: {asset.extra?.detail_url ? "已生成" : "缺失"}
                </span>
              </div>
              {asset.extra?.owner || asset.role ? (
                <div className="owner-indicator">
                  归属人 (Owner)：<span className="owner-name">{asset.extra?.owner || asset.role}</span>
                </div>
              ) : null}
              <p className="section-desc">
                {asset.description || asset.extra?.visual_prompt || "影视工业全景道具资产：配备 16:9 参考图、转面图 (三视图) 及细节微距特写。"}
              </p>
            </div>
          </div>

          <div className="header-right-actions">
            <Button size="small" className="slot-btn header-edit-btn" icon={<Edit3 size={12} />} onClick={onOpenEditProp}>
              编辑道具
            </Button>
          </div>
        </div>

        {/* 道具三重视角插槽网格 (参考图 16:9 + 转面三视图 16:9 + 细节特写 16:9) */}
        <div className="prop-three-columns-grid">
          {/* 1. 参考图插槽 (Reference Image 16:9) */}
          <div className="prop-slot-column">
            <div className="asset-image-slot">
              <div className="slot-preview-frame">
                {asset.extra?.reference_url || asset.image_url ? (
                  <img
                    src={asset.extra?.reference_url || asset.image_url}
                    className="slot-image"
                    alt="Prop Reference"
                    onClick={() => openImageLightbox(asset.extra?.reference_url || asset.image_url, `${asset.name} 概念参考图`)}
                  />
                ) : (
                  <div className="slot-empty-state">
                    <Package size={22} className="slot-empty-icon" />
                    <span className="slot-empty-text">无参考图 (No Reference)</span>
                  </div>
                )}

                <span className="slot-overlay-badge prop-tag">参考图 (Reference)</span>

                {asset.extra?.reference_url || asset.image_url ? (
                  <div className="slot-actions-bar">
                    <button
                      type="button"
                      className="slot-icon-btn delete-btn"
                      title="删除参考图"
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
            </div>

            <div className="slot-actions-row">
              <Button
                size="small"
                className="slot-btn"
                icon={<Upload size={12} />}
                onClick={() => onManualUrl("prop_reference")}
              >
                上传参考图
              </Button>
              <Button
                size="small"
                type="primary"
                className="slot-btn generate-btn prop-btn"
                loading={generatingProp}
                icon={<RefreshCw size={12} />}
                onClick={onGenerateReference}
              >
                {asset.extra?.reference_url || asset.image_url ? "重新生成参考图" : "生成参考图"}
              </Button>
            </div>

            <div className="slot-prompt-wrap">
              <div className="field-title-bar">
                <span className="slot-prompt-lbl">概念参考图提示词 (Visual Prompt)</span>
                <Button type="link" size="small" className="mini-link-btn" onClick={() => copyText(asset.extra?.visual_prompt || asset.visual_prompt)}>
                  复制
                </Button>
              </div>
              {asset.extra ? (
                <Input.TextArea
                  value={asset.extra.visual_prompt}
                  rows={3}
                  placeholder="描述道具的主体外观形态、材质包浆、使用痕迹与电影级光影..."
                  className="custom-textarea"
                  onChange={(event) => onExtraChange({ visual_prompt: event.target.value })}
                />
              ) : null}
            </div>
          </div>

          {/* 2. 转面图 / 三视图插槽 (Turnaround 16:9) */}
          <div className="prop-slot-column">
            <div className="asset-image-slot">
              <div className="slot-preview-frame">
                {asset.extra?.turnaround_url ? (
                  <img
                    src={asset.extra.turnaround_url}
                    className="slot-image"
                    alt="Turnaround"
                    onClick={() => openImageLightbox(asset.extra?.turnaround_url, `${asset.name} 转面三视图`)}
                  />
                ) : (
                  <div className="slot-empty-state">
                    <Layers size={22} className="slot-empty-icon" />
                    <span className="slot-empty-text">无三视图 (No Turnaround)</span>
                  </div>
                )}

                <span className="slot-overlay-badge turnaround-tag">转面图 (三视图)</span>

                {asset.extra?.turnaround_url ? (
                  <div className="slot-actions-bar">
                    <button
                      type="button"
                      className="slot-icon-btn delete-btn"
                      title="删除转面图"
                      onClick={(event) => {
                        event.stopPropagation()
                        onDeletePropImage("turnaround")
                      }}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="slot-actions-row">
              <Button
                size="small"
                className="slot-btn"
                icon={<Upload size={12} />}
                onClick={() => onManualUrl("prop_turnaround")}
              >
                上传三视图
              </Button>
              <Button
                size="small"
                type="primary"
                className="slot-btn generate-btn turnaround-action-btn"
                loading={generatingPropTurnaround}
                icon={<Sparkles size={12} />}
                onClick={onGenerateTurnaround}
              >
                {asset.extra?.turnaround_url ? "重新生成三视图" : "生成三视图"}
              </Button>
            </div>

            <div className="slot-prompt-wrap">
              <div className="field-title-bar">
                <span className="slot-prompt-lbl">三视图转面设计提示词 (Turnaround)</span>
                <Button type="link" size="small" className="mini-link-btn" onClick={() => copyText(asset.extra?.turnaround_prompt)}>
                  复制
                </Button>
              </div>
              {asset.extra ? (
                <Input.TextArea
                  value={asset.extra.turnaround_prompt}
                  rows={3}
                  placeholder="描述器物的正视图、侧视图、背视图多角度展开与工业结构图纸..."
                  className="custom-textarea"
                  onChange={(event) => onExtraChange({ turnaround_prompt: event.target.value })}
                />
              ) : null}
            </div>
          </div>

          {/* 3. 细节特写插槽 (Detail Close-up 16:9) */}
          <div className="prop-slot-column">
            <div className="asset-image-slot">
              <div className="slot-preview-frame">
                {asset.extra?.detail_url ? (
                  <img
                    src={asset.extra.detail_url}
                    className="slot-image"
                    alt="Detail"
                    onClick={() => openImageLightbox(asset.extra?.detail_url, `${asset.name} 细节特写`)}
                  />
                ) : (
                  <div className="slot-empty-state">
                    <Eye size={22} className="slot-empty-icon" />
                    <span className="slot-empty-text">无细节特写 (No Detail)</span>
                  </div>
                )}

                <span className="slot-overlay-badge detail-tag">细节特写 (Detail)</span>

                {asset.extra?.detail_url ? (
                  <div className="slot-actions-bar">
                    <button
                      type="button"
                      className="slot-icon-btn delete-btn"
                      title="删除特写图"
                      onClick={(event) => {
                        event.stopPropagation()
                        onDeletePropImage("detail")
                      }}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="slot-actions-row">
              <Button
                size="small"
                className="slot-btn"
                icon={<Upload size={12} />}
                onClick={() => onManualUrl("prop_detail")}
              >
                上传特写图
              </Button>
              <Button
                size="small"
                type="primary"
                className="slot-btn generate-btn detail-action-btn"
                loading={generatingPropDetail}
                icon={<Sparkles size={12} />}
                onClick={onGenerateDetail}
              >
                {asset.extra?.detail_url ? "重新生成特写" : "生成细节特写"}
              </Button>
            </div>

            <div className="slot-prompt-wrap">
              <div className="field-title-bar">
                <span className="slot-prompt-lbl">微距特写提示词 (Detail Prompt)</span>
                <Button type="link" size="small" className="mini-link-btn" onClick={() => copyText(asset.extra?.detail_prompt)}>
                  复制
                </Button>
              </div>
              {asset.extra ? (
                <Input.TextArea
                  value={asset.extra.detail_prompt}
                  rows={3}
                  placeholder="描述材质纹理（红木包浆、铜扣生锈、青玉通透）、刻字铭文与微距开刃磨损..."
                  className="custom-textarea"
                  onChange={(event) => onExtraChange({ detail_prompt: event.target.value })}
                />
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* 道具属性与背景故事卡片 */}
      <div className="section-card">
        <div className="field-title-bar" style={{ marginBottom: 12 }}>
          <h4 className="section-title">道具属性、所属角色与剧本出处</h4>
        </div>
        {/* 原版此处为裸 a-form-item（无 a-form 包裹），antd React Form.Item 同样支持独立使用 */}
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
