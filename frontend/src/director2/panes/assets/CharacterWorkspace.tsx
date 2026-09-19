// 角色专属工作区（角色定义 + 参考音 + 身份与造型设定板）——
// 原片参考条仍可锁真人脸；造型图为 16:9 设定板，不再单独生成 1:1 头像。
import { Button, Input, Popconfirm, Select, Slider, Space, Upload, message } from "antd"
import { Maximize2, Mic, Plus, Shirt, Sparkles, Trash2, User } from "lucide-react"
import { useEffect, useState } from "react"
import { listVoiceBank, type Director2Asset } from "../../api"
import { hasSourceReferences } from "../../asset-source-references"
import { groupedVoicePresetOptions, type VoicePreset } from "../../voice-bank"
import {
  INDEXTTS_EMOTIONS,
  MAX_VOICE_AUDIO_BYTES,
  VOICE_AUDIO_ACCEPT,
  hasRefAudio,
  isVoiceAudioFile,
  voiceOf,
} from "../../voice-profile"
import { useMediaPreview } from "../../media-preview"
import { copyText, type AssetIdentity } from "./shared"
import AssetSourceReferenceStrip from "./AssetSourceReferenceStrip"

interface CharacterWorkspaceProps {
  asset: Director2Asset
  onFieldChange: (patch: Partial<Director2Asset>) => void
  onExtraChange: (patch: Record<string, any>) => void
  onIdentityChange: (idx: number, patch: Record<string, any>) => void
  generatingIdentityId: string | null
  onGenerateIdentity: (ident: AssetIdentity) => void
  onRemoveIdentity: (idx: number) => void
  onOpenAddIdentity: () => void
  uploadingSourceRef: boolean
  inferringSourcePrompts?: boolean
  onUploadSourceRefs: (files: File[]) => void
  onRemoveSourceRef: (refId: string) => void
  onInferSourcePrompts?: () => void
  uploadingVoice?: boolean
  previewingVoice?: boolean
  applyingVoicePreset?: boolean
  onUploadVoice?: (file: File) => void
  onApplyVoicePreset?: (presetId: string) => void
  onDeleteVoice?: () => void
  onPreviewVoice?: () => void
  extractingVoice?: boolean
  onExtractVoiceFromShot?: () => void
}

function useVoiceBank() {
  const [voices, setVoices] = useState<VoicePreset[]>([])
  useEffect(() => {
    void listVoiceBank()
      .then((payload) => setVoices(payload.voices || []))
      .catch(() => setVoices([]))
  }, [])
  return voices
}

const ROLE_POSITION_OPTIONS = [
  { value: "主角", label: "主角" },
  { value: "反派/观察", label: "反派/观察" },
  { value: "配角", label: "配角" },
  { value: "龙套", label: "龙套" },
  { value: "旁白", label: "旁白" },
]

const AGE_GROUP_OPTIONS = [
  { value: "幼年", label: "幼年" },
  { value: "少年", label: "少年" },
  { value: "青年", label: "青年" },
  { value: "中年", label: "中年" },
  { value: "老年", label: "老年" },
]

const GENDER_OPTIONS = [
  { value: "男", label: "男" },
  { value: "女", label: "女" },
  { value: "未指定", label: "未指定" },
]

const BODY_TYPE_OPTIONS = [
  { value: "纤细", label: "纤细" },
  { value: "苗条", label: "苗条" },
  { value: "标准", label: "标准" },
  { value: "精悍", label: "精悍" },
  { value: "健壮", label: "健壮" },
  { value: "魁梧", label: "魁梧" },
]

const ART_STYLE_OPTIONS = [
  { value: "chinese_period_drama", label: "写实古装剧" },
  { value: "chinese_modern_drama", label: "写实现代剧" },
  { value: "guoman_fantasy", label: "国漫奇幻" },
  { value: "anime", label: "日漫风" },
  { value: "western_realistic", label: "欧美写实" },
  { value: "western_cartoon", label: "欧美卡通" },
]

const VISUAL_STYLE_OPTIONS = [
  { value: "realistic", label: "写实" },
  { value: "ancient", label: "古风" },
  { value: "modern", label: "现代" },
  { value: "fantasy", label: "奇幻" },
  { value: "cyberpunk", label: "赛博朋克" },
]

const ETHNICITY_OPTIONS = [
  { value: "中国人", label: "中国人" },
  { value: "日本人", label: "日本人" },
  { value: "韩国人", label: "韩国人" },
  { value: "欧美人", label: "欧美人" },
  { value: "混血", label: "混血" },
  { value: "其他", label: "其他" },
]

export default function CharacterWorkspace({
  asset,
  onFieldChange,
  onExtraChange,
  onIdentityChange,
  generatingIdentityId,
  onGenerateIdentity,
  onRemoveIdentity,
  onOpenAddIdentity,
  uploadingSourceRef,
  inferringSourcePrompts,
  onUploadSourceRefs,
  onRemoveSourceRef,
  onInferSourcePrompts,
  uploadingVoice,
  previewingVoice,
  applyingVoicePreset,
  onUploadVoice,
  onApplyVoicePreset,
  onDeleteVoice,
  onPreviewVoice,
  extractingVoice,
  onExtractVoiceFromShot,
}: CharacterWorkspaceProps) {
  const { openMediaPreview } = useMediaPreview()
  const voice = voiceOf(asset.extra)
  const bound = hasRefAudio(asset.extra)
  const voiceBank = useVoiceBank()

  return (
    <div className="character-workspace-layout">
      <div className="section-card character-definition-card">
        <div className="section-header">
          <div className="section-title-wrap">
            <div className="section-icon-badge avatar-badge">
              <User size={16} />
            </div>
            <div>
              <h4 className="section-title">角色定义</h4>
              <p className="section-desc">
                填写姓名、五官与身形。有原片截图时生成设定板会按截图锁脸和服装。
              </p>
            </div>
          </div>
        </div>

        <div className="character-definition-body">
            <AssetSourceReferenceStrip
              asset={asset}
              uploading={uploadingSourceRef}
              inferring={inferringSourcePrompts}
              onUpload={onUploadSourceRefs}
              onRemove={onRemoveSourceRef}
              onInferPrompts={onInferSourcePrompts}
            />

            <div className="char-definition-form">
              <div className="def-form-title">
                <span>角色定义 (Character Definition)</span>
              </div>

              {/* 行1: 姓名 / 别名 / 描述 */}
              <div className="def-row">
                <div className="def-field def-field-sm">
                  <label className="def-label">* 姓名</label>
                  <Input
                    value={asset.name}
                    placeholder="角色姓名"
                    size="small"
                    onChange={(event) => onFieldChange({ name: event.target.value })}
                  />
                </div>
                <div className="def-field def-field-sm">
                  <label className="def-label">别名</label>
                  {asset.extra ? (
                    <Input
                      value={asset.extra.aliases}
                      placeholder="陈先生、陈总，用英文逗号分隔"
                      size="small"
                      onChange={(event) => onExtraChange({ aliases: event.target.value })}
                    />
                  ) : null}
                </div>
                <div className="def-field def-field-lg">
                  <label className="def-label">描述</label>
                  {asset.extra ? (
                    <Input.TextArea
                      value={asset.extra.description}
                      rows={2}
                      placeholder="身手敏捷，气质阴冷，常年习武，指节厚重，面露凶相。"
                      className="custom-textarea"
                      onChange={(event) => onExtraChange({ description: event.target.value })}
                    />
                  ) : null}
                </div>
              </div>

              {/* 行2: 角色定位 / 年龄段 / 面部提示词 */}
              <div className="def-row">
                <div className="def-field def-field-sm">
                  <label className="def-label">角色定位</label>
                  {asset.extra ? (
                    <Select
                      value={asset.extra.role_position}
                      size="small"
                      style={{ width: "100%" }}
                      placeholder="请选择"
                      allowClear
                      options={ROLE_POSITION_OPTIONS}
                      onChange={(value) => onExtraChange({ role_position: value })}
                    />
                  ) : null}
                </div>
                <div className="def-field def-field-sm">
                  <label className="def-label">年龄段</label>
                  {asset.extra ? (
                    <Select
                      value={asset.extra.age_group}
                      size="small"
                      style={{ width: "100%" }}
                      placeholder="请选择"
                      allowClear
                      options={AGE_GROUP_OPTIONS}
                      onChange={(value) => onExtraChange({ age_group: value })}
                    />
                  ) : null}
                </div>
                <div className="def-field def-field-lg">
                  <label className="def-label">面部提示词</label>
                  {asset.extra ? (
                    <Input.TextArea
                      value={asset.extra.face_prompt}
                      rows={2}
                      placeholder="男性，青年，黑色短发，黑色眼眸，苍白肤色，棱角分明"
                      className="custom-textarea"
                      onChange={(event) => onExtraChange({ face_prompt: event.target.value })}
                    />
                  ) : null}
                </div>
              </div>

              {/* 行3: 性别 / 身形 */}
              <div className="def-row">
                <div className="def-field def-field-sm">
                  <label className="def-label">性别</label>
                  {asset.extra ? (
                    <Select
                      value={asset.extra.gender}
                      size="small"
                      style={{ width: "100%" }}
                      placeholder="请选择"
                      allowClear
                      options={GENDER_OPTIONS}
                      onChange={(value) => onExtraChange({ gender: value })}
                    />
                  ) : null}
                </div>
                <div className="def-field def-field-sm">
                  <label className="def-label">身形</label>
                  {asset.extra ? (
                    <Select
                      value={asset.extra.body_type}
                      size="small"
                      style={{ width: "100%" }}
                      placeholder="请选择"
                      allowClear
                      options={BODY_TYPE_OPTIONS}
                      onChange={(value) => onExtraChange({ body_type: value })}
                    />
                  ) : null}
                </div>
              </div>

              {/* 行4: 风格 / 画风 */}
              <div className="def-row">
                <div className="def-field def-field-sm">
                  <label className="def-label">风格</label>
                  {asset.extra ? (
                    <Select
                      value={asset.extra.art_style_id}
                      size="small"
                      style={{ width: "100%" }}
                      placeholder="请选择"
                      allowClear
                      options={ART_STYLE_OPTIONS}
                      onChange={(value) => onExtraChange({ art_style_id: value })}
                    />
                  ) : null}
                </div>
                <div className="def-field def-field-sm">
                  <label className="def-label">画风</label>
                  {asset.extra ? (
                    <Select
                      value={asset.extra.visual_style}
                      size="small"
                      style={{ width: "100%" }}
                      placeholder="可不选"
                      allowClear
                      options={VISUAL_STYLE_OPTIONS}
                      onChange={(value) => onExtraChange({ visual_style: value })}
                    />
                  ) : null}
                </div>
              </div>

              {/* 行5: 族裔 */}
              <div className="def-row">
                <div className="def-field def-field-sm">
                  <label className="def-label">族裔</label>
                  {asset.extra ? (
                    <Select
                      value={asset.extra.ethnicity}
                      size="small"
                      style={{ width: "100%" }}
                      placeholder="请选择"
                      allowClear
                      options={ETHNICITY_OPTIONS}
                      onChange={(value) => onExtraChange({ ethnicity: value })}
                    />
                  ) : null}
                </div>
              </div>
            </div>
        </div>
      </div>

      <div className="section-card voice-section-card">
        <div className="section-header">
          <div className="section-title-wrap">
            <div className="section-icon-badge voice-badge">
              <Mic size={16} />
            </div>
            <div>
              <h4 className="section-title">角色参考音</h4>
              <p className="section-desc">
                可先选内置短剧声线，上传一句干净口播，或从成片框选该角色单独说话的片段。配音台用 IndexTTS 克隆。旁白角色同样适用。
              </p>
            </div>
          </div>
        </div>
        <div className="voice-profile-grid">
          <div className="voice-bind-col">
            {bound ? (
              <audio className="voice-audio" src={voice.ref_audio_url} controls preload="metadata" />
            ) : (
              <p className="voice-unbound">尚未绑定参考音，可先选内置短剧声线。</p>
            )}
            <Select
              placeholder="选用内置短剧声线"
              value={voice.preset_id || undefined}
              options={groupedVoicePresetOptions(voiceBank)}
              onChange={(value) => { if (value) onApplyVoicePreset?.(value) }}
              loading={applyingVoicePreset}
              disabled={!onApplyVoicePreset}
              showSearch
              optionFilterProp="label"
              size="small"
              style={{ width: "100%" }}
            />
            <Space wrap>
              <Upload
                accept={VOICE_AUDIO_ACCEPT}
                showUploadList={false}
                beforeUpload={(file) => {
                  if (!isVoiceAudioFile(file)) {
                    message.warning("请上传 wav / mp3 / m4a / flac / ogg")
                    return Upload.LIST_IGNORE
                  }
                  if (file.size > MAX_VOICE_AUDIO_BYTES) {
                    message.warning("参考音不能超过 20 MB")
                    return Upload.LIST_IGNORE
                  }
                  onUploadVoice?.(file)
                  return false
                }}
              >
                <Button loading={uploadingVoice}>{bound ? "更换参考音" : "上传参考音"}</Button>
              </Upload>
              <Button loading={extractingVoice} onClick={() => onExtractVoiceFromShot?.()}>
                从成片提取
              </Button>
              {bound ? (
                <Popconfirm title="删除角色参考音？" okText="删除" cancelText="取消" onConfirm={() => onDeleteVoice?.()}>
                  <Button danger>删除</Button>
                </Popconfirm>
              ) : null}
              <Button loading={previewingVoice} disabled={!bound} onClick={() => onPreviewVoice?.()}>
                试听声线
              </Button>
            </Space>
            {voice.preview_url ? (
              <audio className="voice-audio" src={voice.preview_url} controls preload="metadata" />
            ) : null}
          </div>
          <div className="voice-director-col">
            <div className="def-field">
              <label className="def-label">默认情绪</label>
              <Select
                value={voice.default_emotion}
                size="small"
                style={{ width: "100%" }}
                options={INDEXTTS_EMOTIONS.map((item) => ({ value: item.id, label: item.label }))}
                onChange={(value) => onExtraChange({ voice: { ...voice, default_emotion: value } })}
              />
            </div>
            <div className="def-field">
              <label className="def-label">情绪强度 {voice.emo_alpha.toFixed(2)}</label>
              <Slider
                min={0}
                max={1}
                step={0.05}
                value={voice.emo_alpha}
                onChange={(value) => onExtraChange({ voice: { ...voice, emo_alpha: value } })}
              />
            </div>
            <div className="def-field">
              <label className="def-label">语速 {voice.duration_factor.toFixed(2)}x</label>
              <Slider
                min={0.5}
                max={2}
                step={0.05}
                value={voice.duration_factor}
                onChange={(value) => onExtraChange({ voice: { ...voice, duration_factor: value } })}
              />
            </div>
          </div>
        </div>
      </div>

      {/* 板块二：角色身份与造型设定 (IdentitiesGridSection - 参考 source2) */}
      <div className="section-card identities-section-card">
        <div className="section-header">
          <div className="section-title-wrap">
            <div className="section-icon-badge costume-badge">
              <Shirt size={16} />
            </div>
            <div>
              <div className="title-with-badge">
                <h4 className="section-title">身份与造型设定 (Identities & Costumes)</h4>
                <span className="identity-count-tag">
                  {asset.extra?.identities?.length || 0} 套服装造型
                </span>
              </div>
              <p className="section-desc">
                每套造型生成一张 16:9 设定板（左三视图、右上头型、右下服装细节），用于分镜头锁脸锁装。
              </p>
            </div>
          </div>

          <Button type="primary" className="add-costume-btn" icon={<Plus size={14} />} onClick={onOpenAddIdentity}>
            新增身份/造型
          </Button>
        </div>

        {/* 造型卡片网格 */}
        <div className="identities-grid">
          {((asset.extra?.identities as AssetIdentity[]) || []).map((ident, idx) => (
            <div
              key={ident.id || idx}
              className="identity-card"
            >
              {/* 卡片顶部：造型名称与操作 */}
              <div className="ident-card-header">
                <div className="ident-name-row">
                  <span className="ident-index-badge">造型 {idx + 1}</span>
                  <input
                    value={ident.name}
                    className="ident-name-input"
                    placeholder="造型名称 (例如：伴读常服)"
                    onChange={(event) => onIdentityChange(idx, { name: event.target.value })}
                  />
                </div>

                <Popconfirm
                  title="确定删除此套造型设定？"
                  okText="删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => onRemoveIdentity(idx)}
                >
                  <Button size="small" type="text" danger className="delete-ident-btn" icon={<Trash2 size={13} />} />
                </Popconfirm>
              </div>

              {/* 卡片主体：左图 (16:9 四宫格造型图) + 右文 */}
              <div className="ident-card-body">
                {/* 左边：造型图展示与独立生图按钮 (16:9，对齐 source1 look sheet) */}
                <div className="ident-image-col">
                  <div className="ident-img-frame">
                    {ident.image_url ? (
                      <img
                        src={ident.image_url}
                        className="ident-img-view"
                        alt={`${ident.name || "造型"}`}
                        onClick={() => openMediaPreview({ src: ident.image_url, title: `${asset.name} · ${ident.name || "造型图"}` })}
                      />
                    ) : (
                      <div className="ident-img-empty">
                        <Shirt size={28} className="empty-shirt-icon" />
                        <span className="empty-shirt-text">尚未生成设定板</span>
                      </div>
                    )}

                    {ident.image_url ? (
                      <button
                        type="button"
                        className="float-view-btn"
                        title="放大查看"
                        aria-label={`放大查看${ident.name || "造型图"}`}
                        onClick={() => openMediaPreview({ src: ident.image_url, title: `${asset.name} · ${ident.name || "造型图"}` })}
                      >
                        <Maximize2 size={13} />
                      </button>
                    ) : null}
                  </div>

                  <Button
                    type="primary"
                    className="ident-gen-btn"
                    loading={generatingIdentityId === ident.id}
                    icon={<Sparkles size={14} />}
                    onClick={() => onGenerateIdentity(ident)}
                  >
                    {ident.image_url ? "重新生成设定板" : "✨ 生成设定板"}
                  </Button>
                  {hasSourceReferences(asset) ? (
                    <span className="avatar-ref-hint">将按原片截图的服装生成，忽略下方旧衣装描述</span>
                  ) : null}
                </div>

                {/* 右边：外观描述与专属提示词 */}
                <div className="ident-info-col">
                  <div className="ident-field">
                    <label className="ident-field-label">服装与外观特征 (Appearance)</label>
                    <Input.TextArea
                      value={ident.description}
                      rows={2}
                      placeholder="如：洗得发白的青灰粗布长衫、腰束旧布带、旧布鞋..."
                      className="custom-textarea"
                      onChange={(event) => onIdentityChange(idx, { description: event.target.value })}
                    />
                  </div>

                  <div className="ident-field">
                    <div className="field-title-bar">
                      <label className="ident-field-label">AI 造型生图提示词 (Visual Prompt)</label>
                      <Button
                        type="link"
                        size="small"
                        className="mini-link-btn"
                        onClick={() => copyText(ident.visual_prompt)}
                      >
                        复制
                      </Button>
                    </div>
                    <Input.TextArea
                      value={ident.visual_prompt}
                      rows={3}
                      placeholder="用于生成该造型立绘的详细提示词..."
                      className="custom-textarea"
                      onChange={(event) => onIdentityChange(idx, { visual_prompt: event.target.value })}
                    />
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
