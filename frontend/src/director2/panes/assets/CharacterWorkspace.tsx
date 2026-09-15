// 角色专属工作区（板块一：角色基础头像 + 板块二：身份与造型设定）——
// 逐行复刻自 AssetsLibraryPane.vue 模板 A 区（v-if="selectedAsset.kind === 'character'"）。
// 原版通过 v-model 直接深改 selectedAsset 并由深度 watch 触发自动保存；
// React 中改为 onFieldChange / onExtraChange / onIdentityChange 回调上抛，由父组件统一更新状态与自动保存。
import { Button, Input, Popconfirm, Select, Space, message } from "antd"
import { ExternalLink, Plus, Shirt, Sparkles, Trash2, User } from "lucide-react"
import type { Director2Asset } from "../../api"
import { copyText, getAssetGradient, type AssetIdentity } from "./shared"

interface CharacterWorkspaceProps {
  asset: Director2Asset
  onFieldChange: (patch: Partial<Director2Asset>) => void
  onExtraChange: (patch: Record<string, any>) => void
  onIdentityChange: (idx: number, patch: Record<string, any>) => void
  generatingAvatar: boolean
  generatingIdentityId: string | null
  onGenerateAvatar: () => void
  onGenerateIdentity: (ident: AssetIdentity) => void
  onRemoveIdentity: (idx: number) => void
  onOpenAddIdentity: () => void
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
  generatingAvatar,
  generatingIdentityId,
  onGenerateAvatar,
  onGenerateIdentity,
  onRemoveIdentity,
  onOpenAddIdentity,
}: CharacterWorkspaceProps) {
  function resetAvatarPrompt() {
    onExtraChange({
      avatar_prompt: `${asset.name}，面部肖像特写，五官分明，眼神清澈坚毅，中国古代少年，极简中性灰色背景，柔和电影级布光，8k`,
    })
    message.success("已重置为推荐特写提示词")
  }

  return (
    <div className="character-workspace-layout">
      {/* 板块一：角色基础头像区 (PortraitBlock 1:1) */}
      <div className="section-card portrait-section-card">
        <div className="section-header">
          <div className="section-title-wrap">
            <div className="section-icon-badge avatar-badge">
              <User size={16} />
            </div>
            <div>
              <h4 className="section-title">角色基础头像 (Portrait 1:1)</h4>
              <p className="section-desc">
                用于剧集人物列表、对话头像、角色演员表与特写识别，1:1 正方形纯净背景特写。
              </p>
            </div>
          </div>
        </div>

        <div className="portrait-content-grid">
          {/* 左侧：1:1 头像预览与生成按钮 */}
          <div className="portrait-preview-col">
            <div className="avatar-box">
              {asset.extra?.avatar_url || asset.image_url ? (
                <img
                  src={asset.extra?.avatar_url || asset.image_url}
                  className="avatar-img-view"
                  alt=""
                />
              ) : (
                <div className="avatar-placeholder" style={getAssetGradient(asset.name)}>
                  <span className="placeholder-char">{asset.name?.slice(0, 1) || "?"}</span>
                  <span className="placeholder-tip">暂无头像</span>
                </div>
              )}

              {asset.extra?.avatar_url || asset.image_url ? (
                <a
                  href={asset.extra?.avatar_url || asset.image_url}
                  target="_blank"
                  className="float-view-btn"
                  title="查看大图"
                >
                  <ExternalLink size={13} />
                </a>
              ) : null}
            </div>

            <div className="avatar-actions">
              <Button
                type="primary"
                className="avatar-gen-btn"
                loading={generatingAvatar}
                icon={<Sparkles size={15} />}
                onClick={onGenerateAvatar}
              >
                {asset.extra?.avatar_url || asset.image_url ? "重新生成头像" : "✨ 生成头像"}
              </Button>

            </div>
          </div>

          {/* 右侧：头像生图提示词与容貌小传 */}
          <div className="portrait-prompt-col">
            <div className="prompt-field-wrap">
              <div className="field-title-bar">
                <span className="field-label">
                  <Sparkles size={14} className="text-purple" />
                  头像生图特写提示词 (Avatar Visual Prompt)
                </span>
                <Space>
                  <Button type="link" size="small" onClick={resetAvatarPrompt}>
                    重置为推荐
                  </Button>
                  <Button type="link" size="small" onClick={() => copyText(asset.extra?.avatar_prompt)}>
                    复制 Prompt
                  </Button>
                </Space>
              </div>
              {asset.extra ? (
                <Input.TextArea
                  value={asset.extra.avatar_prompt}
                  rows={3}
                  placeholder="描述面容特征、发型、眼神气质、特写镜头感..."
                  className="custom-textarea"
                  onChange={(event) => onExtraChange({ avatar_prompt: event.target.value })}
                />
              ) : null}
              <span className="field-hint">
                💡 头像将强化人物五官和肖像眼神表现，生成 1024x1024 高清特写。
              </span>
            </div>


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
                角色随剧情经历不同时期与社会身份。每套造型具备独立立绘形象与服装 Prompt，用于分镜头精准视觉赋予。
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
                        alt=""
                      />
                    ) : (
                      <div className="ident-img-empty">
                        <Shirt size={28} className="empty-shirt-icon" />
                        <span className="empty-shirt-text">尚未生成造型图</span>
                      </div>
                    )}

                    {ident.image_url ? (
                      <a
                        href={ident.image_url}
                        target="_blank"
                        className="float-view-btn"
                        title="查看大图"
                      >
                        <ExternalLink size={13} />
                      </a>
                    ) : null}
                  </div>

                  <Button
                    type="primary"
                    className="ident-gen-btn"
                    loading={generatingIdentityId === ident.id}
                    icon={<Sparkles size={14} />}
                    onClick={() => onGenerateIdentity(ident)}
                  >
                    {ident.image_url ? "重新生成造型图" : "✨ 生成造型图"}
                  </Button>
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
