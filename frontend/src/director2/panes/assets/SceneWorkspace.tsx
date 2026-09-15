// 场景专属工作区（严格参考 source2 scene-asset-card：三大机位 + 空间属性卡）——
// 逐行复刻自 AssetsLibraryPane.vue 模板 B 区（v-else-if="selectedAsset.kind === 'scene'"）。
// 提示词编辑通过 onExtraChange 上抛由父组件统一触发自动保存。
import { Button, Col, Form, Input, Row, Select } from "antd"
import { Camera, Compass, Edit3, ExternalLink, Image as ImageIcon, RefreshCw, Sparkles, Trash2, Upload } from "lucide-react"
import type { Director2Asset } from "../../api"
import { copyText, openImageLightbox, SCENE_TYPE_OPTIONS } from "./shared"

interface SceneWorkspaceProps {
  asset: Director2Asset
  onFieldChange: (patch: Partial<Director2Asset>) => void
  onExtraChange: (patch: Record<string, any>) => void
  generatingMaster: boolean
  generatingReverse: boolean
  generatingPano: boolean
  onGenerateMaster: () => void
  onGenerateReverse: () => void
  onGeneratePano: () => void
  onDeleteSceneImage: (slot: "master" | "reverse" | "pano") => void
  onManualUrl: (target: string) => void
  onOpenPanoViewer: (url: string) => void
  onOpenEditScene: () => void
}

export default function SceneWorkspace({
  asset,
  onFieldChange,
  onExtraChange,
  generatingMaster,
  generatingReverse,
  generatingPano,
  onGenerateMaster,
  onGenerateReverse,
  onGeneratePano,
  onDeleteSceneImage,
  onManualUrl,
  onOpenPanoViewer,
  onOpenEditScene,
}: SceneWorkspaceProps) {
  return (
    <div className="scene-workspace-layout">
      <div className="section-card">
        {/* 场景头部：标题 + Meta Badges + 状态 Chips (与 source2 CardHeader 一致) */}
        <div className="section-header scene-header-row">
          <div className="section-title-wrap">
            <div className="section-icon-badge scene-badge">
              <Camera size={16} />
            </div>
            <div>
              <div className="title-with-badge">
                <h4 className="section-title">{asset.name}</h4>
                {/* 元信息状态标签组 (参考 source2 ASSET_CARD_META_BADGE_CLASS) */}
                <span className="meta-chip type-chip">
                  {asset.extra?.scene_type === "interior" ? "室内 (Interior)" : "室外 (Exterior)"}
                </span>
                <span className={`meta-chip${asset.extra?.master_url || asset.image_url ? " ok" : ""}`}>
                  Master: {asset.extra?.master_url || asset.image_url ? "已生成" : "缺失"}
                </span>
                <span className={`meta-chip${asset.extra?.reverse_url ? " ok" : ""}`}>
                  Reverse (背面): {asset.extra?.reverse_url ? "已生成" : "缺失"}
                </span>
                <span className={`meta-chip${asset.extra?.pano_url ? " ok" : ""}`}>
                  Pano (360): {asset.extra?.pano_url ? "已生成" : "缺失"}
                </span>
              </div>
              <p className="section-desc">
                {asset.description || asset.extra?.environment_prompt || "影视工业多视角场景设定：包含 Master 主视角、Reverse 背面反打视角与 360° 全景图。"}
              </p>
            </div>
          </div>

          <div className="header-right-actions">
            <Button size="small" className="slot-btn header-edit-btn" icon={<Edit3 size={12} />} onClick={onOpenEditScene}>
              编辑场景
            </Button>
          </div>
        </div>

        {/* 三大机位卡片并排网格 (严格参考 source2 grid md:grid-cols-2 xl:grid-cols-3) */}
        <div className="scene-three-columns-grid">
          {/* 1. Master 列 (正向/主视角 16:9) */}
          <div className="scene-slot-column">
            <div className="asset-image-slot">
              {/* 预览窗口 (带有左上角角标与右上角操作) */}
              <div className="slot-preview-frame">
                {asset.extra?.master_url || asset.image_url ? (
                  <img
                    src={asset.extra?.master_url || asset.image_url}
                    className="slot-image"
                    alt="Master"
                    onClick={() => openImageLightbox(asset.extra?.master_url || asset.image_url, "Master 主视角")}
                  />
                ) : (
                  <div className="slot-empty-state">
                    <ImageIcon size={20} className="slot-empty-icon" />
                    <span className="slot-empty-text">无 Master 视角</span>
                  </div>
                )}

                {/* 左上角覆盖标签 */}
                <span className="slot-overlay-badge">Master</span>

                {/* 右上角悬浮动作 */}
                {asset.extra?.master_url || asset.image_url ? (
                  <div className="slot-actions-bar">
                    <button
                      type="button"
                      className="slot-icon-btn delete-btn"
                      title="删除 Master 视角图"
                      onClick={(event) => {
                        event.stopPropagation()
                        onDeleteSceneImage("master")
                      }}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ) : null}
              </div>
            </div>

            {/* 下方操作按钮栏 (上传 + 生成) */}
            <div className="slot-actions-row">
              <Button
                size="small"
                className="slot-btn"
                icon={<Upload size={12} />}
                onClick={() => onManualUrl("master")}
              >
                上传 Master
              </Button>
              <Button
                size="small"
                type="primary"
                className="slot-btn generate-btn"
                loading={generatingMaster}
                icon={<RefreshCw size={12} />}
                onClick={onGenerateMaster}
              >
                {asset.extra?.master_url || asset.image_url ? "重新生成 Master" : "生成 Master"}
              </Button>
            </div>

            {/* 环境提示词编辑框 */}
            <div className="slot-prompt-wrap">
              <div className="field-title-bar">
                <span className="slot-prompt-lbl">主视角环境提示词 (Environment Prompt)</span>
                <Button type="link" size="small" className="mini-link-btn" onClick={() => copyText(asset.extra?.environment_prompt)}>
                  复制
                </Button>
              </div>
              {asset.extra ? (
                <Input.TextArea
                  value={asset.extra.environment_prompt}
                  rows={3}
                  placeholder="描述主视角的空间构图、建筑样式、室内陈设与自然采光..."
                  className="custom-textarea"
                  onChange={(event) => onExtraChange({ environment_prompt: event.target.value })}
                />
              ) : null}
            </div>
          </div>

          {/* 2. Reverse 列 (背面/反打机位 16:9) */}
          <div className="scene-slot-column">
            <div className="asset-image-slot">
              <div className="slot-preview-frame">
                {asset.extra?.reverse_url ? (
                  <img
                    src={asset.extra.reverse_url}
                    className="slot-image"
                    alt="Reverse"
                    onClick={() => openImageLightbox(asset.extra?.reverse_url, "Reverse 背面反打视角")}
                  />
                ) : (
                  <div className="slot-empty-state">
                    <ImageIcon size={20} className="slot-empty-icon" />
                    <span className="slot-empty-text">无 Reverse 视角</span>
                  </div>
                )}

                <span className="slot-overlay-badge reverse-tag">Reverse (背面)</span>

                {asset.extra?.reverse_url ? (
                  <div className="slot-actions-bar">
                    <button
                      type="button"
                      className="slot-icon-btn delete-btn"
                      title="删除 Reverse 视角图"
                      onClick={(event) => {
                        event.stopPropagation()
                        onDeleteSceneImage("reverse")
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
                type="primary"
                className="slot-btn generate-btn reverse-action-btn"
                loading={generatingReverse}
                icon={<RefreshCw size={12} />}
                onClick={onGenerateReverse}
              >
                {asset.extra?.reverse_url ? "重新生成 Reverse" : "生成 Reverse"}
              </Button>
            </div>

            <div className="slot-prompt-wrap">
              <div className="field-title-bar">
                <span className="slot-prompt-lbl">背面反打机位提示词 (Reverse Prompt)</span>
                <Button type="link" size="small" className="mini-link-btn" onClick={() => copyText(asset.extra?.reverse_prompt)}>
                  复制
                </Button>
              </div>
              {asset.extra ? (
                <Input.TextArea
                  value={asset.extra.reverse_prompt}
                  rows={3}
                  placeholder="描述180度转身反向对立机位的门窗方位与逆光景深透视..."
                  className="custom-textarea"
                  onChange={(event) => onExtraChange({ reverse_prompt: event.target.value })}
                />
              ) : null}
            </div>
          </div>

          {/* 3. Panorama 列 (360 全景图片) */}
          <div className="scene-slot-column">
            <div className="asset-image-slot">
              <div className="slot-preview-frame pano-frame">
                {asset.extra?.pano_url ? (
                  <img
                    src={asset.extra.pano_url}
                    className="slot-image pano-img"
                    alt="Pano"
                    onClick={() => onOpenPanoViewer(asset.extra.pano_url)}
                  />
                ) : (
                  <div className="slot-empty-state">
                    <Compass size={20} className="slot-empty-icon" />
                    <span className="slot-empty-text">无 Pano 360全景</span>
                  </div>
                )}

                <span className="slot-overlay-badge pano-tag">Pano (360°)</span>

                {asset.extra?.pano_url ? (
                  <div className="slot-actions-bar">
                    <button
                      type="button"
                      className="slot-icon-btn delete-btn"
                      title="删除 Pano 图片"
                      onClick={(event) => {
                        event.stopPropagation()
                        onDeleteSceneImage("pano")
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
                type="primary"
                className="slot-btn generate-btn pano-action-btn"
                loading={generatingPano}
                icon={<Sparkles size={12} />}
                onClick={onGeneratePano}
              >
                {asset.extra?.pano_url ? "重新生成 360 全景" : "生成 360 全景图"}
              </Button>
              <Button
                size="small"
                className="slot-btn"
                icon={<Upload size={12} />}
                onClick={() => onManualUrl("pano")}
              >
                上传 Pano
              </Button>
              {asset.extra?.pano_url ? (
                <Button
                  size="small"
                  className="slot-btn viewer-btn"
                  icon={<ExternalLink size={12} />}
                  onClick={() => onOpenPanoViewer(asset.extra.pano_url)}
                >
                  360 全景查看器
                </Button>
              ) : null}
            </div>

            <div className="slot-prompt-wrap">
              <div className="field-title-bar">
                <span className="slot-prompt-lbl">360 全景提示词 (Pano Prompt)</span>
                <Button type="link" size="small" className="mini-link-btn" onClick={() => copyText(asset.extra?.pano_prompt)}>
                  复制
                </Button>
              </div>
              {asset.extra ? (
                <Input.TextArea
                  value={asset.extra.pano_prompt}
                  rows={3}
                  placeholder="描述360度球形无缝等距柱状全景空间与四方环境陈设..."
                  className="custom-textarea"
                  onChange={(event) => onExtraChange({ pano_prompt: event.target.value })}
                />
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* 场景属性与空间设定卡片 */}
      <div className="section-card">
        <div className="field-title-bar" style={{ marginBottom: 12 }}>
          <h4 className="section-title">场景空间属性与剧本背景</h4>
        </div>
        {/* 原版此处为裸 a-form-item（无 a-form 包裹），antd React Form.Item 同样支持独立使用 */}
        <Row gutter={14}>
          <Col span={8}>
            <Form.Item label="场景名称" required>
              <Input value={asset.name} placeholder="例如：沈家正堂" onChange={(event) => onFieldChange({ name: event.target.value })} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item label="场景类型 (Scene Type)">
              {asset.extra ? (
                <Select value={asset.extra.scene_type} options={SCENE_TYPE_OPTIONS} onChange={(value) => onExtraChange({ scene_type: value })} />
              ) : null}
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item label="归属势力 / 地点定位">
              <Input value={asset.role ?? ""} placeholder="例如：沈家老宅、陆府后院" onChange={(event) => onFieldChange({ role: event.target.value })} />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item label="场景陈设与建筑格局描述">
          <Input.TextArea
            value={asset.description ?? ""}
            rows={3}
            placeholder="描述该场景在剧本中的陈设细节、光照氛围、破旧或奢华程度..."
            onChange={(event) => onFieldChange({ description: event.target.value })}
          />
        </Form.Item>
      </div>
    </div>
  )
}
