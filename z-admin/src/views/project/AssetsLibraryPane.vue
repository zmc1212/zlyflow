<template>
  <div class="assets-library-pane">
    <!-- 顶部操作栏 -->
    <div class="sub-pane-header">
      <div class="header-copy">
        <h2 class="sub-pane-title">资产库</h2>
        <p class="sub-pane-subtitle">
          严格参考 source2 影视工业流水线：管理角色肖像与身份造型、场景三大机位（Master主视角 / Reverse反打背面 / Pano 360全景）及道具特写参考。
        </p>
      </div>

      <div class="header-actions">
        <div class="stats-pills">
          <span class="stat-pill" :class="{ active: currentTab === 'character' }" @click="handleTabChange('character')">
            <Users :size="13" /> 角色 {{ getCountByKind('character') }}
          </span>
          <span class="stat-pill" :class="{ active: currentTab === 'scene' }" @click="handleTabChange('scene')">
            <MapPin :size="13" /> 场景 {{ getCountByKind('scene') }}
          </span>
          <span class="stat-pill" :class="{ active: currentTab === 'prop' }" @click="handleTabChange('prop')">
            <Package :size="13" /> 道具 {{ getCountByKind('prop') }}
          </span>
        </div>
        <a-button type="primary" class="primary-btn" @click="openCreateModal">
          <template #icon><Plus :size="16" /></template>
          新增{{ kindLabel(currentTab) }}
        </a-button>
      </div>
    </div>
    <div v-if="currentTab === 'character'" class="batch-generate-bar">
      <a-button
        type="primary"
        :loading="batchGeneratingAvatars"
        :disabled="batchGenerationActive && !batchGeneratingAvatars"
        @click="handleBatchGenerateAvatars"
      >
        <template #icon><Sparkles :size="15" /></template>
        一键生成所有头像
      </a-button>
      <a-button
        type="primary"
        :loading="batchGeneratingLooks"
        :disabled="batchGenerationActive && !batchGeneratingLooks"
        @click="handleBatchGenerateLooks"
      >
        <template #icon><Shirt :size="15" /></template>
        一键生成所有造型图
      </a-button>
      <span class="batch-generate-hint">仅处理尚未出图的角色头像 / 已有头像的造型图，任务中心可查看进度</span>
    </div>
    <div v-else-if="currentTab === 'scene'" class="batch-generate-bar">
      <a-button
        type="primary"
        :loading="batchGeneratingSceneMasters"
        :disabled="batchGenerationActive && !batchGeneratingSceneMasters"
        @click="handleBatchGenerateSceneMasters"
      >
        <template #icon><Sparkles :size="15" /></template>
        一键生成所有正面
      </a-button>
      <a-button
        type="primary"
        :loading="batchGeneratingSceneReverses"
        :disabled="batchGenerationActive && !batchGeneratingSceneReverses"
        @click="handleBatchGenerateSceneReverses"
      >
        <template #icon><RefreshCw :size="15" /></template>
        一键生成所有背面
      </a-button>
      <a-button
        type="primary"
        :loading="batchGeneratingScenePanos"
        :disabled="batchGenerationActive && !batchGeneratingScenePanos"
        @click="handleBatchGenerateScenePanos"
      >
        <template #icon><Compass :size="15" /></template>
        一键生成所有360图
      </a-button>
      <span class="batch-generate-hint">仅处理尚未出图的场景；背面和 360 图需已有正面图</span>
    </div>
    <div v-else-if="currentTab === 'prop'" class="batch-generate-bar">
      <a-button
        type="primary"
        :loading="batchGeneratingPropReferences"
        :disabled="batchGenerationActive && !batchGeneratingPropReferences"
        @click="handleBatchGeneratePropReferences"
      >
        <template #icon><Sparkles :size="15" /></template>
        一键生成所有参考图
      </a-button>
      <a-button
        type="primary"
        :loading="batchGeneratingPropTurnarounds"
        :disabled="batchGenerationActive && !batchGeneratingPropTurnarounds"
        @click="handleBatchGeneratePropTurnarounds"
      >
        <template #icon><Layers :size="15" /></template>
        一键生成所有三视图
      </a-button>
      <a-button
        type="primary"
        :loading="batchGeneratingPropDetails"
        :disabled="batchGenerationActive && !batchGeneratingPropDetails"
        @click="handleBatchGeneratePropDetails"
      >
        <template #icon><Eye :size="15" /></template>
        一键生成所有细节图
      </a-button>
      <span class="batch-generate-hint">仅处理尚未出图的道具；三视图和细节图需已有参考图</span>
    </div>

    <a-spin :spinning="loading">
      <div v-if="assets.length === 0" class="empty-asset-box">
        <Boxes :size="48" class="empty-icon" />
        <h3>资产库暂无资产</h3>
        <p>可前往「内容库」一键导入剧本并抽取资产，或点击右上角手动新增。</p>
        <a-button type="primary" @click="openCreateModal">立即新增第一个资产</a-button>
      </div>

      <!-- 左右结构：左边选择名称，右边显示详细与生成 (参考 source2) -->
      <div v-else class="assets-split-container">
        <!-- 左侧：分类、搜索与资产名称列表 -->
        <div class="assets-sidebar-list">
          <!-- 分类 Tabs (去掉全部，默认角色) -->
          <div class="sidebar-tabs">
            <div
              v-for="tab in tabs"
              :key="tab.key"
              class="sidebar-tab-item"
              :class="{ active: currentTab === tab.key }"
              @click="handleTabChange(tab.key)"
            >
              <component :is="getKindIcon(tab.key)" :size="13" />
              <span>{{ tab.label }}</span>
              <span class="tab-count-badge">{{ getCountByKind(tab.key) }}</span>
            </div>
          </div>

          <!-- 搜索过滤 -->
          <div class="sidebar-search-box">
            <a-input
              v-model:value="searchKeyword"
              :placeholder="`搜索${kindLabel(currentTab)}名称 / 设定...`"
              allow-clear
              size="small"
            >
              <template #prefix><Search :size="13" class="text-gray" /></template>
            </a-input>
          </div>

          <!-- 资产列表滚动区 -->
          <div class="sidebar-items-scroll">
            <div v-if="filteredAssets.length === 0" class="no-filter-match">
              暂无{{ kindLabel(currentTab) }}数据
            </div>
            <div
              v-for="ast in filteredAssets"
              :key="ast.id"
              class="asset-list-item"
              :class="{ active: selectedAsset && selectedAsset.id === ast.id }"
              @click="selectAsset(ast)"
            >
              <!-- 缩略图或单字头像 -->
              <div class="item-avatar" :class="ast.kind" :style="getAssetGradient(ast.name)">
                <img
                  v-if="getAssetDisplayAvatar(ast)"
                  :src="getAssetDisplayAvatar(ast)"
                  class="avatar-img"
                  alt=""
                />
                <span v-else class="avatar-char">
                  {{ ast.name ? ast.name.slice(0, 1) : '?' }}
                </span>
                <span v-if="getAssetDisplayAvatar(ast)" class="has-image-dot" title="已有视觉图"></span>
              </div>

              <!-- 名称与定位 -->
              <div class="item-info">
                <div class="item-name-row">
                  <span class="item-name" :title="ast.name">{{ ast.name }}</span>
                  <a-tag :color="getKindColor(ast.kind)" size="small" class="kind-tag">
                    {{ getKindMetaBadge(ast) }}
                  </a-tag>
                </div>
                <div class="item-sub-row">
                  <span class="item-role" :title="ast.role || '无定位'">
                    {{ getSubRoleDisplay(ast) }}
                  </span>
                  <!-- 角色显示造型数，场景显示全景/机位状态，道具显示归属人 -->
                  <span
                    v-if="ast.kind === 'character' && ast.extra?.identities?.length"
                    class="extra-count-chip"
                  >
                    {{ ast.extra.identities.length }}造型
                  </span>
                  <span
                    v-else-if="ast.kind === 'scene'"
                    class="extra-count-chip scene-chip"
                  >
                    {{ ast.extra?.pano_url ? '360°就绪' : (ast.extra?.reverse_url ? '正反打就绪' : '主视角') }}
                  </span>
                  <span
                    v-else-if="ast.kind === 'prop' && ast.extra?.owner"
                    class="extra-count-chip prop-chip"
                  >
                    {{ ast.extra.owner.slice(0, 4) }}
                  </span>
                </div>
              </div>

              <!-- 选中激活指示条 -->
              <div v-if="selectedAsset && selectedAsset.id === ast.id" class="item-active-bar"></div>
            </div>
          </div>
        </div>

        <!-- 右侧：详细信息与 AI 形象生成工作区 (参考 source2) -->
        <div class="asset-detail-workspace">
          <div v-if="!selectedAsset" class="empty-detail-state">
            <div class="empty-detail-icon">
              <Boxes :size="36" />
            </div>
            <h4>请在左侧选择一个{{ kindLabel(currentTab) }}</h4>
            <p>点击左侧名称即可查看详细配置、AI 生图提示词及在线生成视觉形象。</p>
          </div>

          <div v-else class="detail-content-wrap">
            <!-- 顶部操作栏 -->
            <div class="detail-header-card">
              <div class="header-left">
                <div class="header-title-row">
                  <h3 class="detail-asset-name">{{ selectedAsset.name }}</h3>
                  <a-tag :color="getKindColor(selectedAsset.kind)">
                    {{ kindLabel(selectedAsset.kind) }}
                  </a-tag>
                  <a-tag v-if="selectedAsset.role" color="blue">
                    {{ selectedAsset.role }}
                  </a-tag>
                  <span class="update-time">更新于 {{ (selectedAsset.updated_at || '').slice(5, 16) }}</span>
                </div>
              </div>

              <a-space>
                <a-button
                  v-if="selectedAsset.kind === 'character'"
                  type="dashed"
                  class="add-identity-btn"
                  @click="openAddIdentityModal"
                >
                  <template #icon><Shirt :size="15" /></template>
                  + 新增身份/造型
                </a-button>
                <a-button
                  v-if="selectedAsset.kind === 'scene'"
                  class="edit-action-btn"
                  @click="openEditSceneModal"
                >
                  <template #icon><Edit3 :size="15" /></template>
                  编辑场景
                </a-button>
                <a-button
                  v-if="selectedAsset.kind === 'prop'"
                  class="edit-action-btn"
                  @click="openEditPropModal"
                >
                  <template #icon><Edit3 :size="15" /></template>
                  编辑道具
                </a-button>
                <span class="auto-save-status" :class="`is-${autoSaveState}`">
                  <Save :size="14" />
                  {{ autoSaveStatusText }}
                </span>
                <a-popconfirm
                  title="确定删除此资产？"
                  ok-text="删除"
                  cancel-text="取消"
                  ok-type="danger"
                  @confirm="handleDeleteAsset(selectedAsset.id)"
                >
                  <a-button danger type="text">
                    <template #icon><Trash2 :size="15" /></template>
                    删除
                  </a-button>
                </a-popconfirm>
              </a-space>
            </div>

            <!-- ========================= A. 角色专属工作区 (参考 source2) ========================= -->
            <div v-if="selectedAsset.kind === 'character'" class="character-workspace-layout">
              <!-- 板块一：角色基础头像区 (PortraitBlock 1:1) -->
              <div class="section-card portrait-section-card">
                <div class="section-header">
                  <div class="section-title-wrap">
                    <div class="section-icon-badge avatar-badge">
                      <User :size="16" />
                    </div>
                    <div>
                      <h4 class="section-title">角色基础头像 (Portrait 1:1)</h4>
                      <p class="section-desc">
                        用于剧集人物列表、对话头像、角色演员表与特写识别，1:1 正方形纯净背景特写。
                      </p>
                    </div>
                  </div>
                </div>

                <div class="portrait-content-grid">
                  <!-- 左侧：1:1 头像预览与生成按钮 -->
                  <div class="portrait-preview-col">
                    <div class="avatar-box">
                      <img
                        v-if="selectedAsset.extra?.avatar_url || selectedAsset.image_url"
                        :src="selectedAsset.extra?.avatar_url || selectedAsset.image_url"
                        class="avatar-img-view"
                        alt=""
                      />
                      <div v-else class="avatar-placeholder" :style="getAssetGradient(selectedAsset.name)">
                        <span class="placeholder-char">{{ selectedAsset.name?.slice(0, 1) || '?' }}</span>
                        <span class="placeholder-tip">暂无头像</span>
                      </div>

                      <a
                        v-if="selectedAsset.extra?.avatar_url || selectedAsset.image_url"
                        :href="selectedAsset.extra?.avatar_url || selectedAsset.image_url"
                        target="_blank"
                        class="float-view-btn"
                        title="查看大图"
                      >
                        <ExternalLink :size="13" />
                      </a>
                    </div>

                    <div class="avatar-actions">
                      <a-button
                        type="primary"
                        class="avatar-gen-btn"
                        :loading="generatingAvatar"
                        @click="handleGenerateAvatar"
                      >
                        <template #icon><Sparkles :size="15" /></template>
                        {{ (selectedAsset.extra?.avatar_url || selectedAsset.image_url) ? '重新生成头像' : '✨ 生成头像' }}
                      </a-button>

                    </div>
                  </div>

                  <!-- 右侧：头像生图提示词与容貌小传 -->
                  <div class="portrait-prompt-col">
                    <div class="prompt-field-wrap">
                      <div class="field-title-bar">
                        <span class="field-label">
                          <Sparkles :size="14" class="text-purple" />
                          头像生图特写提示词 (Avatar Visual Prompt)
                        </span>
                        <a-space>
                          <a-button type="link" size="small" @click="resetAvatarPrompt">
                            重置为推荐
                          </a-button>
                          <a-button type="link" size="small" @click="copyText(selectedAsset.extra?.avatar_prompt)">
                            复制 Prompt
                          </a-button>
                        </a-space>
                      </div>
                      <a-textarea
                        v-if="selectedAsset.extra"
                        v-model:value="selectedAsset.extra.avatar_prompt"
                        :rows="3"
                        placeholder="描述面容特征、发型、眼神气质、特写镜头感..."
                        class="custom-textarea"
                      />
                      <span class="field-hint">
                        💡 头像将强化人物五官和肖像眼神表现，生成 1024x1024 高清特写。
                      </span>
                    </div>


                    <div class="char-definition-form">
                      <div class="def-form-title">
                        <span>角色定义 (Character Definition)</span>
                      </div>

                      <!-- 行1: 姓名 / 别名 / 描述 -->
                      <div class="def-row">
                        <div class="def-field def-field-sm">
                          <label class="def-label">* 姓名</label>
                          <a-input
                            v-model:value="selectedAsset.name"
                            placeholder="角色姓名"
                            size="small"
                          />
                        </div>
                        <div class="def-field def-field-sm">
                          <label class="def-label">别名</label>
                          <a-input
                            v-if="selectedAsset.extra"
                            v-model:value="selectedAsset.extra.aliases"
                            placeholder="陈先生、陈总，用英文逗号分隔"
                            size="small"
                          />
                        </div>
                        <div class="def-field def-field-lg">
                          <label class="def-label">描述</label>
                          <a-textarea
                            v-if="selectedAsset.extra"
                            v-model:value="selectedAsset.extra.description"
                            :rows="2"
                            placeholder="身手敏捷，气质阴冷，常年习武，指节厚重，面露凶相。"
                            class="custom-textarea"
                          />
                        </div>
                      </div>

                      <!-- 行2: 角色定位 / 年龄段 / 面部提示词 -->
                      <div class="def-row">
                        <div class="def-field def-field-sm">
                          <label class="def-label">角色定位</label>
                          <a-select
                            v-if="selectedAsset.extra"
                            v-model:value="selectedAsset.extra.role_position"
                            size="small"
                            style="width: 100%"
                            placeholder="请选择"
                            allow-clear
                          >
                            <a-select-option value="主角">主角</a-select-option>
                            <a-select-option value="反派/观察">反派/观察</a-select-option>
                            <a-select-option value="配角">配角</a-select-option>
                            <a-select-option value="龙套">龙套</a-select-option>
                            <a-select-option value="旁白">旁白</a-select-option>
                          </a-select>
                        </div>
                        <div class="def-field def-field-sm">
                          <label class="def-label">年龄段</label>
                          <a-select
                            v-if="selectedAsset.extra"
                            v-model:value="selectedAsset.extra.age_group"
                            size="small"
                            style="width: 100%"
                            placeholder="请选择"
                            allow-clear
                          >
                            <a-select-option value="幼年">幼年</a-select-option>
                            <a-select-option value="少年">少年</a-select-option>
                            <a-select-option value="青年">青年</a-select-option>
                            <a-select-option value="中年">中年</a-select-option>
                            <a-select-option value="老年">老年</a-select-option>
                          </a-select>
                        </div>
                        <div class="def-field def-field-lg">
                          <label class="def-label">面部提示词</label>
                          <a-textarea
                            v-if="selectedAsset.extra"
                            v-model:value="selectedAsset.extra.face_prompt"
                            :rows="2"
                            placeholder="男性，青年，黑色短发，黑色眼眸，苍白肤色，棱角分明"
                            class="custom-textarea"
                          />
                        </div>
                      </div>

                      <!-- 行3: 性别 / 身形 -->
                      <div class="def-row">
                        <div class="def-field def-field-sm">
                          <label class="def-label">性别</label>
                          <a-select
                            v-if="selectedAsset.extra"
                            v-model:value="selectedAsset.extra.gender"
                            size="small"
                            style="width: 100%"
                            placeholder="请选择"
                            allow-clear
                          >
                            <a-select-option value="男">男</a-select-option>
                            <a-select-option value="女">女</a-select-option>
                            <a-select-option value="未指定">未指定</a-select-option>
                          </a-select>
                        </div>
                        <div class="def-field def-field-sm">
                          <label class="def-label">身形</label>
                          <a-select
                            v-if="selectedAsset.extra"
                            v-model:value="selectedAsset.extra.body_type"
                            size="small"
                            style="width: 100%"
                            placeholder="请选择"
                            allow-clear
                          >
                            <a-select-option value="纤细">纤细</a-select-option>
                            <a-select-option value="苗条">苗条</a-select-option>
                            <a-select-option value="标准">标准</a-select-option>
                            <a-select-option value="精悍">精悍</a-select-option>
                            <a-select-option value="健壮">健壮</a-select-option>
                            <a-select-option value="魁梧">魁梧</a-select-option>
                          </a-select>
                        </div>
                      </div>

                      <!-- 行4: 风格 / 画风 -->
                      <div class="def-row">
                        <div class="def-field def-field-sm">
                          <label class="def-label">风格</label>
                          <a-select
                            v-if="selectedAsset.extra"
                            v-model:value="selectedAsset.extra.art_style_id"
                            size="small"
                            style="width: 100%"
                            placeholder="请选择"
                            allow-clear
                          >
                            <a-select-option value="chinese_period_drama">写实古装剧</a-select-option>
                            <a-select-option value="chinese_modern_drama">写实现代剧</a-select-option>
                            <a-select-option value="guoman_fantasy">国漫奇幻</a-select-option>
                            <a-select-option value="anime">日漫风</a-select-option>
                            <a-select-option value="western_realistic">欧美写实</a-select-option>
                            <a-select-option value="western_cartoon">欧美卡通</a-select-option>
                          </a-select>
                        </div>
                        <div class="def-field def-field-sm">
                          <label class="def-label">画风</label>
                          <a-select
                            v-if="selectedAsset.extra"
                            v-model:value="selectedAsset.extra.visual_style"
                            size="small"
                            style="width: 100%"
                            placeholder="可不选"
                            allow-clear
                          >
                            <a-select-option value="realistic">写实</a-select-option>
                            <a-select-option value="ancient">古风</a-select-option>
                            <a-select-option value="modern">现代</a-select-option>
                            <a-select-option value="fantasy">奇幻</a-select-option>
                            <a-select-option value="cyberpunk">赛博朋克</a-select-option>
                          </a-select>
                        </div>
                      </div>

                      <!-- 行5: 族裔 -->
                      <div class="def-row">
                        <div class="def-field def-field-sm">
                          <label class="def-label">族裔</label>
                          <a-select
                            v-if="selectedAsset.extra"
                            v-model:value="selectedAsset.extra.ethnicity"
                            size="small"
                            style="width: 100%"
                            placeholder="请选择"
                            allow-clear
                          >
                            <a-select-option value="中国人">中国人</a-select-option>
                            <a-select-option value="日本人">日本人</a-select-option>
                            <a-select-option value="韩国人">韩国人</a-select-option>
                            <a-select-option value="欧美人">欧美人</a-select-option>
                            <a-select-option value="混血">混血</a-select-option>
                            <a-select-option value="其他">其他</a-select-option>
                          </a-select>
                        </div>
                      </div>
                    </div>

                  </div>
                </div>
              </div>

              <!-- 板块二：角色身份与造型设定 (IdentitiesGridSection - 参考 source2) -->
              <div class="section-card identities-section-card">
                <div class="section-header">
                  <div class="section-title-wrap">
                    <div class="section-icon-badge costume-badge">
                      <Shirt :size="16" />
                    </div>
                    <div>
                      <div class="title-with-badge">
                        <h4 class="section-title">身份与造型设定 (Identities & Costumes)</h4>
                        <span class="identity-count-tag">
                          {{ selectedAsset.extra?.identities?.length || 0 }} 套服装造型
                        </span>
                      </div>
                      <p class="section-desc">
                        角色随剧情经历不同时期与社会身份。每套造型具备独立立绘形象与服装 Prompt，用于分镜头精准视觉赋予。
                      </p>
                    </div>
                  </div>

                  <a-button type="primary" class="add-costume-btn" @click="openAddIdentityModal">
                    <template #icon><Plus :size="14" /></template>
                    新增身份/造型
                  </a-button>
                </div>

                <!-- 造型卡片网格 -->
                <div class="identities-grid">
                  <div
                    v-for="(ident, idx) in (selectedAsset.extra?.identities || [])"
                    :key="ident.id || idx"
                    class="identity-card"
                  >
                    <!-- 卡片顶部：造型名称与操作 -->
                    <div class="ident-card-header">
                      <div class="ident-name-row">
                        <span class="ident-index-badge">造型 {{ idx + 1 }}</span>
                        <input
                          v-model="ident.name"
                          class="ident-name-input"
                          placeholder="造型名称 (例如：伴读常服)"
                        />
                      </div>

                      <a-popconfirm
                        title="确定删除此套造型设定？"
                        ok-text="删除"
                        cancel-text="取消"
                        ok-type="danger"
                        @confirm="handleRemoveIdentity(idx)"
                      >
                        <a-button size="small" type="text" danger class="delete-ident-btn">
                          <template #icon><Trash2 :size="13" /></template>
                        </a-button>
                      </a-popconfirm>
                    </div>

                    <!-- 卡片主体：左图 (16:9 四宫格造型图) + 右文 -->
                    <div class="ident-card-body">
                      <!-- 左边：造型图展示与独立生图按钮 (16:9，对齐 source1 look sheet) -->
                      <div class="ident-image-col">
                        <div class="ident-img-frame">
                          <img
                            v-if="ident.image_url"
                            :src="ident.image_url"
                            class="ident-img-view"
                            alt=""
                          />
                          <div v-else class="ident-img-empty">
                            <Shirt :size="28" class="empty-shirt-icon" />
                            <span class="empty-shirt-text">尚未生成造型图</span>
                          </div>

                          <a
                            v-if="ident.image_url"
                            :href="ident.image_url"
                            target="_blank"
                            class="float-view-btn"
                            title="查看大图"
                          >
                            <ExternalLink :size="13" />
                          </a>
                        </div>

                        <a-button
                          type="primary"
                          class="ident-gen-btn"
                          :loading="generatingIdentityId === ident.id"
                          @click="handleGenerateIdentityImage(ident)"
                        >
                          <template #icon><Sparkles :size="14" /></template>
                          {{ ident.image_url ? '重新生成造型图' : '✨ 生成造型图' }}
                        </a-button>
                      </div>

                      <!-- 右边：外观描述与专属提示词 -->
                      <div class="ident-info-col">
                        <div class="ident-field">
                          <label class="ident-field-label">服装与外观特征 (Appearance)</label>
                          <a-textarea
                            v-model:value="ident.description"
                            :rows="2"
                            placeholder="如：洗得发白的青灰粗布长衫、腰束旧布带、旧布鞋..."
                            class="custom-textarea"
                          />
                        </div>

                        <div class="ident-field">
                          <div class="field-title-bar">
                            <label class="ident-field-label">AI 造型生图提示词 (Visual Prompt)</label>
                            <a-button
                              type="link"
                              size="small"
                              class="mini-link-btn"
                              @click="copyText(ident.visual_prompt)"
                            >
                              复制
                            </a-button>
                          </div>
                          <a-textarea
                            v-model:value="ident.visual_prompt"
                            :rows="3"
                            placeholder="用于生成该造型立绘的详细提示词..."
                            class="custom-textarea"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- ========================= B. 场景专属工作区 (严格参考 source2 scene-asset-card) ========================= -->
            <div v-else-if="selectedAsset.kind === 'scene'" class="scene-workspace-layout">
              <div class="section-card">
                <!-- 场景头部：标题 + Meta Badges + 状态 Chips (与 source2 CardHeader 一致) -->
                <div class="section-header scene-header-row">
                  <div class="section-title-wrap">
                    <div class="section-icon-badge scene-badge">
                      <Camera :size="16" />
                    </div>
                    <div>
                      <div class="title-with-badge">
                        <h4 class="section-title">{{ selectedAsset.name }}</h4>
                        <!-- 元信息状态标签组 (参考 source2 ASSET_CARD_META_BADGE_CLASS) -->
                        <span class="meta-chip type-chip">
                          {{ selectedAsset.extra?.scene_type === 'interior' ? '室内 (Interior)' : '室外 (Exterior)' }}
                        </span>
                        <span class="meta-chip" :class="{ ok: selectedAsset.extra?.master_url || selectedAsset.image_url }">
                          Master: {{ (selectedAsset.extra?.master_url || selectedAsset.image_url) ? '已生成' : '缺失' }}
                        </span>
                        <span class="meta-chip" :class="{ ok: selectedAsset.extra?.reverse_url }">
                          Reverse (背面): {{ selectedAsset.extra?.reverse_url ? '已生成' : '缺失' }}
                        </span>
                        <span class="meta-chip" :class="{ ok: selectedAsset.extra?.pano_url }">
                          Pano (360): {{ selectedAsset.extra?.pano_url ? '已生成' : '缺失' }}
                        </span>
                      </div>
                      <p class="section-desc">
                        {{ selectedAsset.description || selectedAsset.extra?.environment_prompt || '影视工业多视角场景设定：包含 Master 主视角、Reverse 背面反打视角与 360° 全景图。' }}
                      </p>
                    </div>
                  </div>

                  <div class="header-right-actions">
                    <a-button size="small" class="slot-btn header-edit-btn" @click="openEditSceneModal">
                      <template #icon><Edit3 :size="12" /></template>
                      编辑场景
                    </a-button>
                  </div>
                </div>

                <!-- 三大机位卡片并排网格 (严格参考 source2 grid md:grid-cols-2 xl:grid-cols-3) -->
                <div class="scene-three-columns-grid">
                  <!-- 1. Master 列 (正向/主视角 16:9) -->
                  <div class="scene-slot-column">
                    <div class="asset-image-slot">
                      <!-- 预览窗口 (带有左上角角标与右上角操作) -->
                      <div class="slot-preview-frame">
                        <img
                          v-if="selectedAsset.extra?.master_url || selectedAsset.image_url"
                          :src="selectedAsset.extra?.master_url || selectedAsset.image_url"
                          class="slot-image"
                          alt="Master"
                          @click="openImageLightbox(selectedAsset.extra?.master_url || selectedAsset.image_url, 'Master 主视角')"
                        />
                        <div v-else class="slot-empty-state">
                          <ImageIcon :size="20" class="slot-empty-icon" />
                          <span class="slot-empty-text">无 Master 视角</span>
                        </div>

                        <!-- 左上角覆盖标签 -->
                        <span class="slot-overlay-badge">Master</span>

                        <!-- 右上角悬浮动作 -->
                        <div v-if="selectedAsset.extra?.master_url || selectedAsset.image_url" class="slot-actions-bar">
                          <button
                            type="button"
                            class="slot-icon-btn delete-btn"
                            title="删除 Master 视角图"
                            @click.stop="handleDeleteSceneImage('master')"
                          >
                            <Trash2 :size="12" />
                          </button>
                        </div>
                      </div>
                    </div>

                    <!-- 下方操作按钮栏 (上传 + 生成) -->
                    <div class="slot-actions-row">
                      <a-button
                        size="small"
                        class="slot-btn"
                        @click="triggerManualUrlInput('master')"
                      >
                        <template #icon><Upload :size="12" /></template>
                        上传 Master
                      </a-button>
                      <a-button
                        size="small"
                        type="primary"
                        class="slot-btn generate-btn"
                        :loading="generatingMaster"
                        @click="handleGenerateSceneMaster"
                      >
                        <template #icon><RefreshCw :size="12" /></template>
                        {{ (selectedAsset.extra?.master_url || selectedAsset.image_url) ? '重新生成 Master' : '生成 Master' }}
                      </a-button>
                    </div>

                    <!-- 环境提示词编辑框 -->
                    <div class="slot-prompt-wrap">
                      <div class="field-title-bar">
                        <span class="slot-prompt-lbl">主视角环境提示词 (Environment Prompt)</span>
                        <a-button type="link" size="small" class="mini-link-btn" @click="copyText(selectedAsset.extra?.environment_prompt)">
                          复制
                        </a-button>
                      </div>
                      <a-textarea
                        v-if="selectedAsset.extra"
                        v-model:value="selectedAsset.extra.environment_prompt"
                        :rows="3"
                        placeholder="描述主视角的空间构图、建筑样式、室内陈设与自然采光..."
                        class="custom-textarea"
                      />
                    </div>
                  </div>

                  <!-- 2. Reverse 列 (背面/反打机位 16:9) -->
                  <div class="scene-slot-column">
                    <div class="asset-image-slot">
                      <div class="slot-preview-frame">
                        <img
                          v-if="selectedAsset.extra?.reverse_url"
                          :src="selectedAsset.extra.reverse_url"
                          class="slot-image"
                          alt="Reverse"
                          @click="openImageLightbox(selectedAsset.extra.reverse_url, 'Reverse 背面反打视角')"
                        />
                        <div v-else class="slot-empty-state">
                          <ImageIcon :size="20" class="slot-empty-icon" />
                          <span class="slot-empty-text">无 Reverse 视角</span>
                        </div>

                        <span class="slot-overlay-badge reverse-tag">Reverse (背面)</span>

                        <div v-if="selectedAsset.extra?.reverse_url" class="slot-actions-bar">
                          <button
                            type="button"
                            class="slot-icon-btn delete-btn"
                            title="删除 Reverse 视角图"
                            @click.stop="handleDeleteSceneImage('reverse')"
                          >
                            <Trash2 :size="12" />
                          </button>
                        </div>
                      </div>
                    </div>

                    <div class="slot-actions-row">
                      <a-button
                        size="small"
                        type="primary"
                        class="slot-btn generate-btn reverse-action-btn"
                        :loading="generatingReverse"
                        @click="handleGenerateSceneReverse"
                      >
                        <template #icon><RefreshCw :size="12" /></template>
                        {{ selectedAsset.extra?.reverse_url ? '重新生成 Reverse' : '生成 Reverse' }}
                      </a-button>
                    </div>

                    <div class="slot-prompt-wrap">
                      <div class="field-title-bar">
                        <span class="slot-prompt-lbl">背面反打机位提示词 (Reverse Prompt)</span>
                        <a-button type="link" size="small" class="mini-link-btn" @click="copyText(selectedAsset.extra?.reverse_prompt)">
                          复制
                        </a-button>
                      </div>
                      <a-textarea
                        v-if="selectedAsset.extra"
                        v-model:value="selectedAsset.extra.reverse_prompt"
                        :rows="3"
                        placeholder="描述180度转身反向对立机位的门窗方位与逆光景深透视..."
                        class="custom-textarea"
                      />
                    </div>
                  </div>

                  <!-- 3. Panorama 列 (360 全景图片) -->
                  <div class="scene-slot-column">
                    <div class="asset-image-slot">
                      <div class="slot-preview-frame pano-frame">
                        <img
                          v-if="selectedAsset.extra?.pano_url"
                          :src="selectedAsset.extra.pano_url"
                          class="slot-image pano-img"
                          alt="Pano"
                          @click="openPanoViewerModal(selectedAsset.extra.pano_url)"
                        />
                        <div v-else class="slot-empty-state">
                          <Compass :size="20" class="slot-empty-icon" />
                          <span class="slot-empty-text">无 Pano 360全景</span>
                        </div>

                        <span class="slot-overlay-badge pano-tag">Pano (360°)</span>

                        <div v-if="selectedAsset.extra?.pano_url" class="slot-actions-bar">
                          <button
                            type="button"
                            class="slot-icon-btn delete-btn"
                            title="删除 Pano 图片"
                            @click.stop="handleDeleteSceneImage('pano')"
                          >
                            <Trash2 :size="12" />
                          </button>
                        </div>
                      </div>
                    </div>

                    <div class="slot-actions-row">
                      <a-button
                        size="small"
                        type="primary"
                        class="slot-btn generate-btn pano-action-btn"
                        :loading="generatingPano"
                        @click="handleGenerateScenePano"
                      >
                        <template #icon><Sparkles :size="12" /></template>
                        {{ selectedAsset.extra?.pano_url ? '重新生成 360 全景' : '生成 360 全景图' }}
                      </a-button>
                      <a-button
                        size="small"
                        class="slot-btn"
                        @click="triggerManualUrlInput('pano')"
                      >
                        <template #icon><Upload :size="12" /></template>
                        上传 Pano
                      </a-button>
                      <a-button
                        v-if="selectedAsset.extra?.pano_url"
                        size="small"
                        class="slot-btn viewer-btn"
                        @click="openPanoViewerModal(selectedAsset.extra.pano_url)"
                      >
                        <template #icon><ExternalLink :size="12" /></template>
                        360 全景查看器
                      </a-button>
                    </div>

                    <div class="slot-prompt-wrap">
                      <div class="field-title-bar">
                        <span class="slot-prompt-lbl">360 全景提示词 (Pano Prompt)</span>
                        <a-button type="link" size="small" class="mini-link-btn" @click="copyText(selectedAsset.extra?.pano_prompt)">
                          复制
                        </a-button>
                      </div>
                      <a-textarea
                        v-if="selectedAsset.extra"
                        v-model:value="selectedAsset.extra.pano_prompt"
                        :rows="3"
                        placeholder="描述360度球形无缝等距柱状全景空间与四方环境陈设..."
                        class="custom-textarea"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <!-- 场景属性与空间设定卡片 -->
              <div class="section-card">
                <div class="field-title-bar" style="margin-bottom: 12px;">
                  <h4 class="section-title">场景空间属性与剧本背景</h4>
                </div>
                <a-row :gutter="14">
                  <a-col :span="8">
                    <a-form-item label="场景名称" required>
                      <a-input v-model:value="selectedAsset.name" placeholder="例如：沈家正堂" />
                    </a-form-item>
                  </a-col>
                  <a-col :span="8">
                    <a-form-item label="场景类型 (Scene Type)">
                      <a-select v-if="selectedAsset.extra" v-model:value="selectedAsset.extra.scene_type">
                        <a-select-option value="interior">室内内景 (Interior)</a-select-option>
                        <a-select-option value="exterior">室外实景 (Exterior)</a-select-option>
                        <a-select-option value="pano">宏观航拍/远景 (Panoramic)</a-select-option>
                      </a-select>
                    </a-form-item>
                  </a-col>
                  <a-col :span="8">
                    <a-form-item label="归属势力 / 地点定位">
                      <a-input v-model:value="selectedAsset.role" placeholder="例如：沈家老宅、陆府后院" />
                    </a-form-item>
                  </a-col>
                </a-row>

                <a-form-item label="场景陈设与建筑格局描述">
                  <a-textarea
                    v-model:value="selectedAsset.description"
                    :rows="3"
                    placeholder="描述该场景在剧本中的陈设细节、光照氛围、破旧或奢华程度..."
                  />
                </a-form-item>
              </div>
            </div>

            <!-- ========================= C. 道具专属工作区 (严格参考 source2 prop-asset-card: 参考图 + 转面三视图 + 细节特写) ========================= -->
            <div v-else-if="selectedAsset.kind === 'prop'" class="prop-workspace-layout">
              <div class="section-card">
                <!-- 道具头部：标题 + Meta Badges + Owner 归属 + 状态 Chips (与 source2 CardHeader 一致) -->
                <div class="section-header prop-header-row">
                  <div class="section-title-wrap">
                    <div class="section-icon-badge prop-badge">
                      <Package :size="16" />
                    </div>
                    <div>
                      <div class="title-with-badge">
                        <h4 class="section-title">{{ selectedAsset.name }}</h4>
                        <span class="meta-chip type-chip prop-chip">
                          {{ getPropTypeLabel(selectedAsset.extra?.prop_type) }}
                        </span>
                        <span class="meta-chip" :class="{ ok: selectedAsset.extra?.reference_url || selectedAsset.image_url }">
                          参考图: {{ (selectedAsset.extra?.reference_url || selectedAsset.image_url) ? '已生成' : '缺失' }}
                        </span>
                        <span class="meta-chip" :class="{ ok: selectedAsset.extra?.turnaround_url }">
                          三视图: {{ selectedAsset.extra?.turnaround_url ? '已生成' : '缺失' }}
                        </span>
                        <span class="meta-chip" :class="{ ok: selectedAsset.extra?.detail_url }">
                          细节特写: {{ selectedAsset.extra?.detail_url ? '已生成' : '缺失' }}
                        </span>
                      </div>
                      <div v-if="selectedAsset.extra?.owner || selectedAsset.role" class="owner-indicator">
                        归属人 (Owner)：<span class="owner-name">{{ selectedAsset.extra?.owner || selectedAsset.role }}</span>
                      </div>
                      <p class="section-desc">
                        {{ selectedAsset.description || selectedAsset.extra?.visual_prompt || '影视工业全景道具资产：配备 16:9 参考图、转面图 (三视图) 及细节微距特写。' }}
                      </p>
                    </div>
                  </div>

                  <div class="header-right-actions">
                    <a-button size="small" class="slot-btn header-edit-btn" @click="openEditPropModal">
                      <template #icon><Edit3 :size="12" /></template>
                      编辑道具
                    </a-button>
                  </div>
                </div>

                <!-- 道具三重视角插槽网格 (参考图 16:9 + 转面三视图 16:9 + 细节特写 16:9) -->
                <div class="prop-three-columns-grid">
                  <!-- 1. 参考图插槽 (Reference Image 16:9) -->
                  <div class="prop-slot-column">
                    <div class="asset-image-slot">
                      <div class="slot-preview-frame">
                        <img
                          v-if="selectedAsset.extra?.reference_url || selectedAsset.image_url"
                          :src="selectedAsset.extra?.reference_url || selectedAsset.image_url"
                          class="slot-image"
                          alt="Prop Reference"
                          @click="openImageLightbox(selectedAsset.extra?.reference_url || selectedAsset.image_url, `${selectedAsset.name} 概念参考图`)"
                        />
                        <div v-else class="slot-empty-state">
                          <Package :size="22" class="slot-empty-icon" />
                          <span class="slot-empty-text">无参考图 (No Reference)</span>
                        </div>

                        <span class="slot-overlay-badge prop-tag">参考图 (Reference)</span>

                        <div v-if="selectedAsset.extra?.reference_url || selectedAsset.image_url" class="slot-actions-bar">
                          <button
                            type="button"
                            class="slot-icon-btn delete-btn"
                            title="删除参考图"
                            @click.stop="handleDeletePropImage('reference')"
                          >
                            <Trash2 :size="12" />
                          </button>
                        </div>
                      </div>
                    </div>

                    <div class="slot-actions-row">
                      <a-button
                        size="small"
                        class="slot-btn"
                        @click="triggerManualUrlInput('prop_reference')"
                      >
                        <template #icon><Upload :size="12" /></template>
                        上传参考图
                      </a-button>
                      <a-button
                        size="small"
                        type="primary"
                        class="slot-btn generate-btn prop-btn"
                        :loading="generatingProp"
                        @click="handleGeneratePropReference"
                      >
                        <template #icon><RefreshCw :size="12" /></template>
                        {{ (selectedAsset.extra?.reference_url || selectedAsset.image_url) ? '重新生成参考图' : '生成参考图' }}
                      </a-button>
                    </div>

                    <div class="slot-prompt-wrap">
                      <div class="field-title-bar">
                        <span class="slot-prompt-lbl">概念参考图提示词 (Visual Prompt)</span>
                        <a-button type="link" size="small" class="mini-link-btn" @click="copyText(selectedAsset.extra?.visual_prompt || selectedAsset.visual_prompt)">
                          复制
                        </a-button>
                      </div>
                      <a-textarea
                        v-if="selectedAsset.extra"
                        v-model:value="selectedAsset.extra.visual_prompt"
                        :rows="3"
                        placeholder="描述道具的主体外观形态、材质包浆、使用痕迹与电影级光影..."
                        class="custom-textarea"
                      />
                    </div>
                  </div>

                  <!-- 2. 转面图 / 三视图插槽 (Turnaround 16:9) -->
                  <div class="prop-slot-column">
                    <div class="asset-image-slot">
                      <div class="slot-preview-frame">
                        <img
                          v-if="selectedAsset.extra?.turnaround_url"
                          :src="selectedAsset.extra.turnaround_url"
                          class="slot-image"
                          alt="Turnaround"
                          @click="openImageLightbox(selectedAsset.extra.turnaround_url, `${selectedAsset.name} 转面三视图`)"
                        />
                        <div v-else class="slot-empty-state">
                          <Layers :size="22" class="slot-empty-icon" />
                          <span class="slot-empty-text">无三视图 (No Turnaround)</span>
                        </div>

                        <span class="slot-overlay-badge turnaround-tag">转面图 (三视图)</span>

                        <div v-if="selectedAsset.extra?.turnaround_url" class="slot-actions-bar">
                          <button
                            type="button"
                            class="slot-icon-btn delete-btn"
                            title="删除转面图"
                            @click.stop="handleDeletePropImage('turnaround')"
                          >
                            <Trash2 :size="12" />
                          </button>
                        </div>
                      </div>
                    </div>

                    <div class="slot-actions-row">
                      <a-button
                        size="small"
                        class="slot-btn"
                        @click="triggerManualUrlInput('prop_turnaround')"
                      >
                        <template #icon><Upload :size="12" /></template>
                        上传三视图
                      </a-button>
                      <a-button
                        size="small"
                        type="primary"
                        class="slot-btn generate-btn turnaround-action-btn"
                        :loading="generatingPropTurnaround"
                        @click="handleGeneratePropTurnaround"
                      >
                        <template #icon><Sparkles :size="12" /></template>
                        {{ selectedAsset.extra?.turnaround_url ? '重新生成三视图' : '生成三视图' }}
                      </a-button>
                    </div>

                    <div class="slot-prompt-wrap">
                      <div class="field-title-bar">
                        <span class="slot-prompt-lbl">三视图转面设计提示词 (Turnaround)</span>
                        <a-button type="link" size="small" class="mini-link-btn" @click="copyText(selectedAsset.extra?.turnaround_prompt)">
                          复制
                        </a-button>
                      </div>
                      <a-textarea
                        v-if="selectedAsset.extra"
                        v-model:value="selectedAsset.extra.turnaround_prompt"
                        :rows="3"
                        placeholder="描述器物的正视图、侧视图、背视图多角度展开与工业结构图纸..."
                        class="custom-textarea"
                      />
                    </div>
                  </div>

                  <!-- 3. 细节特写插槽 (Detail Close-up 16:9) -->
                  <div class="prop-slot-column">
                    <div class="asset-image-slot">
                      <div class="slot-preview-frame">
                        <img
                          v-if="selectedAsset.extra?.detail_url"
                          :src="selectedAsset.extra.detail_url"
                          class="slot-image"
                          alt="Detail"
                          @click="openImageLightbox(selectedAsset.extra.detail_url, `${selectedAsset.name} 细节特写`)"
                        />
                        <div v-else class="slot-empty-state">
                          <Eye :size="22" class="slot-empty-icon" />
                          <span class="slot-empty-text">无细节特写 (No Detail)</span>
                        </div>

                        <span class="slot-overlay-badge detail-tag">细节特写 (Detail)</span>

                        <div v-if="selectedAsset.extra?.detail_url" class="slot-actions-bar">
                          <button
                            type="button"
                            class="slot-icon-btn delete-btn"
                            title="删除特写图"
                            @click.stop="handleDeletePropImage('detail')"
                          >
                            <Trash2 :size="12" />
                          </button>
                        </div>
                      </div>
                    </div>

                    <div class="slot-actions-row">
                      <a-button
                        size="small"
                        class="slot-btn"
                        @click="triggerManualUrlInput('prop_detail')"
                      >
                        <template #icon><Upload :size="12" /></template>
                        上传特写图
                      </a-button>
                      <a-button
                        size="small"
                        type="primary"
                        class="slot-btn generate-btn detail-action-btn"
                        :loading="generatingPropDetail"
                        @click="handleGeneratePropDetail"
                      >
                        <template #icon><Sparkles :size="12" /></template>
                        {{ selectedAsset.extra?.detail_url ? '重新生成特写' : '生成细节特写' }}
                      </a-button>
                    </div>

                    <div class="slot-prompt-wrap">
                      <div class="field-title-bar">
                        <span class="slot-prompt-lbl">微距特写提示词 (Detail Prompt)</span>
                        <a-button type="link" size="small" class="mini-link-btn" @click="copyText(selectedAsset.extra?.detail_prompt)">
                          复制
                        </a-button>
                      </div>
                      <a-textarea
                        v-if="selectedAsset.extra"
                        v-model:value="selectedAsset.extra.detail_prompt"
                        :rows="3"
                        placeholder="描述材质纹理（红木包浆、铜扣生锈、青玉通透）、刻字铭文与微距开刃磨损..."
                        class="custom-textarea"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <!-- 道具属性与背景故事卡片 -->
              <div class="section-card">
                <div class="field-title-bar" style="margin-bottom: 12px;">
                  <h4 class="section-title">道具属性、所属角色与剧本出处</h4>
                </div>
                <a-row :gutter="14">
                  <a-col :span="8">
                    <a-form-item label="道具名称" required>
                      <a-input v-model:value="selectedAsset.name" placeholder="例如：旧木书箱" />
                    </a-form-item>
                  </a-col>
                  <a-col :span="8">
                    <a-form-item label="所属角色 (Owner)">
                      <a-input
                        v-if="selectedAsset.extra"
                        v-model:value="selectedAsset.extra.owner"
                        placeholder="例如：沈砚 专属信物"
                      />
                      <a-input
                        v-else
                        v-model:value="selectedAsset.role"
                        placeholder="例如：沈砚 专属信物"
                      />
                    </a-form-item>
                  </a-col>
                  <a-col :span="8">
                    <a-form-item label="道具类型 (Prop Type)">
                      <a-select v-if="selectedAsset.extra" v-model:value="selectedAsset.extra.prop_type">
                        <a-select-option value="weapon">武器 (Weapon)</a-select-option>
                        <a-select-option value="accessory">饰品 (Accessory)</a-select-option>
                        <a-select-option value="artifact">神器/法器 (Artifact)</a-select-option>
                        <a-select-option value="document">文书 (Document)</a-select-option>
                        <a-select-option value="furniture">家具 (Furniture)</a-select-option>
                        <a-select-option value="object">其他物件 (Object)</a-select-option>
                      </a-select>
                    </a-form-item>
                  </a-col>
                </a-row>

                <a-form-item label="道具背景故事与剧本出处描述">
                  <a-textarea
                    v-model:value="selectedAsset.description"
                    :rows="3"
                    placeholder="记录该道具在剧本故事中的起源、象征意义或重要剧情推动作用..."
                  />
                </a-form-item>
              </div>
            </div>
          </div>
        </div>
      </div>
    </a-spin>

    <!-- 360 全景查看器弹窗 (PanoViewerModal) -->
    <a-modal
      v-model:open="panoViewerVisible"
      title="360° 全景空间查看器 (Panorama Viewer)"
      :footer="null"
      :width="960"
      destroy-on-close
    >
      <div class="pano-viewer-body">
        <div class="pano-image-container">
          <img :src="currentPanoUrl" class="pano-panoramic-img" alt="360 Panorama" />
        </div>
        <div class="pano-viewer-tips">
          <Compass :size="15" class="text-blue" />
          <span>支持 360° 全景等距柱状图漫游展示，在 3D 虚拟影棚与自由运镜模式中作为沉浸式天空盒背景。</span>
          <a :href="currentPanoUrl" target="_blank" class="download-link">在新标签页打开原图</a>
        </div>
      </div>
    </a-modal>

    <!-- 手动输入图片 URL 弹窗 -->
    <a-modal
      v-model:open="manualUrlModalVisible"
      :title="`手动指定 ${manualUrlTarget} 图片地址`"
      ok-text="确认指定"
      cancel-text="取消"
      :width="500"
      @ok="handleConfirmManualUrl"
    >
      <a-form layout="vertical">
        <a-form-item label="图片 URL 直链">
          <a-input v-model:value="manualUrlInput" placeholder="https://..." />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 新增身份/造型弹窗 (参考 source2 CreateIdentityModal) -->
    <a-modal
      v-model:open="identityModalVisible"
      title="为角色新增身份 / 造型 (Identity & Costume)"
      :confirm-loading="savingIdentity"
      ok-text="确认添加造型"
      cancel-text="取消"
      :width="540"
      destroy-on-close
      @ok="handleConfirmAddIdentity"
    >
      <a-form layout="vertical">
        <a-form-item label="身份/造型名称" required>
          <a-input
            v-model:value="identityForm.name"
            placeholder="例如：伴读常服 / 武行夜行衣 / 金榜题名锦袍"
          />
        </a-form-item>

        <a-form-item label="服装与外观设定 (Appearance)">
          <a-textarea
            v-model:value="identityForm.description"
            placeholder="详细描述该时期的衣着、配饰、颜色、发型与神态特征..."
            :rows="3"
          />
        </a-form-item>

        <a-form-item label="AI 造型生图提示词 (Visual Prompt)">
          <a-textarea
            v-model:value="identityForm.visual_prompt"
            placeholder="AI 生图提示词，例如：沈砚全身立绘，穿浅青色伴读装，腰佩香囊，宋代书生质感，8k..."
            :rows="3"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 新建资产弹窗 -->
    <a-modal
      v-model:open="modalVisible"
      :title="`新增项目${kindLabel(createForm.kind)}`"
      :width="540"
      destroy-on-close
    >
      <a-form layout="vertical">
        <a-form-item label="资产类型" required>
          <a-radio-group v-model:value="createForm.kind">
            <a-radio-button value="character">角色</a-radio-button>
            <a-radio-button value="scene">场景</a-radio-button>
            <a-radio-button value="prop">道具</a-radio-button>
          </a-radio-group>
        </a-form-item>

        <a-form-item label="资产名称" required>
          <a-input v-model:value="createForm.name" :placeholder="`例如：${createForm.kind === 'character' ? '沈砚' : createForm.kind === 'scene' ? '陆府后花园' : '旧木书箱'}`" />
        </a-form-item>

        <a-form-item :label="createForm.kind === 'character' ? '角色定位' : createForm.kind === 'scene' ? '地点/势力' : '归属角色 (Owner)'">
          <a-input v-model:value="createForm.role" :placeholder="createForm.kind === 'character' ? '例如：男主角' : createForm.kind === 'scene' ? '例如：陆府、书塾' : '例如：沈砚专属信物'" />
        </a-form-item>

        <a-form-item :label="createForm.kind === 'character' ? '容貌与服装描述' : createForm.kind === 'scene' ? '场景环境与格局描述' : '材质纹理与做旧描述'">
          <a-textarea
            v-model:value="createForm.description"
            :placeholder="createForm.kind === 'character' ? '详细描述外貌身材、服饰细节...' : createForm.kind === 'scene' ? '详细描述空间、门窗、陈设光影...' : '详细描述木质、玉石、成色磨损...'"
            :rows="3"
          />
        </a-form-item>

        <a-form-item label="AI 生图提示词 (Visual Prompt)">
          <a-textarea
            v-model:value="createForm.visual_prompt"
            :placeholder="`输入该${kindLabel(createForm.kind)}的 AI 生图提示词...`"
            :rows="3"
          />
        </a-form-item>
      </a-form>
      <template #footer>
        <div class="create-asset-modal-footer">
          <a-button
            v-if="createForm.kind === 'character'"
            :disabled="submitting"
            @click="openCharacterAiModal"
          >
            <Sparkles :size="15" />
            AI 生成内容
          </a-button>
          <a-button :disabled="submitting" @click="modalVisible = false">取消</a-button>
          <a-button type="primary" :loading="submitting" @click="handleCreateSubmit">确认保存</a-button>
        </div>
      </template>
    </a-modal>

    <a-modal
      v-model:open="characterAiModalVisible"
      title="AI 生成角色内容"
      ok-text="生成并回填"
      cancel-text="取消"
      :confirm-loading="generatingCharacterContent"
      :width="500"
      destroy-on-close
      @ok="handleGenerateCharacterContent"
    >
      <a-form layout="vertical">
        <a-form-item label="简洁需求" required>
          <a-textarea
            v-model:value="characterAiRequirement"
            placeholder="例如：26岁现代男硕士，短发，沉稳清瘦，穿白衬衫和深色长裤"
            :rows="5"
            :maxlength="1000"
            show-count
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 编辑场景弹窗 (严格对齐 source2 SceneDialog) -->
    <a-modal
      v-model:open="editSceneModalVisible"
      :title="`编辑场景「${draftScene.name || ''}」`"
      :confirm-loading="savingSceneModal"
      ok-text="确认保存"
      cancel-text="取消"
      :width="780"
      destroy-on-close
      @ok="handleSaveSceneModal"
    >
      <a-form layout="vertical">
        <a-row :gutter="14">
          <a-col :span="12">
            <a-form-item label="场景名称" required>
              <a-input v-model:value="draftScene.name" placeholder="例如：沈家正堂" />
            </a-form-item>
          </a-col>
          <a-col :span="6">
            <a-form-item label="场景类型 (Scene Type)">
              <a-select v-model:value="draftScene.scene_type">
                <a-select-option value="interior">室内内景 (Interior)</a-select-option>
                <a-select-option value="exterior">室外实景 (Exterior)</a-select-option>
                <a-select-option value="pano">宏观航拍/远景 (Panoramic)</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="6">
            <a-form-item label="归属势力 / 地点定位">
              <a-input v-model:value="draftScene.role" placeholder="例如：沈家老宅、陆府" />
            </a-form-item>
          </a-col>
        </a-row>

        <!-- 360 空间合同七大维度结构化编辑 (对齐 source2 SceneEnvironmentPromptFields) -->
        <div class="modal-section-title">
          <Compass :size="14" class="text-cyan" />
          <span>360° 空间环境合同 (七大维度提示词)</span>
        </div>
        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="正面描述 (Front)">
              <a-textarea v-model:value="envSections.front" :rows="2" placeholder="正面主视线景观、空间主体与轴线..." />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="背面描述 (Back / Reverse)">
              <a-textarea v-model:value="envSections.back" :rows="2" placeholder="180度反打视角门窗、屏风与对向景深..." />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="左侧描述 (Left)">
              <a-textarea v-model:value="envSections.left" :rows="2" placeholder="左侧陈设、通道门廊、墙体挂画..." />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="右侧描述 (Right)">
              <a-textarea v-model:value="envSections.right" :rows="2" placeholder="右侧采光窗格、案几器皿、绿植..." />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="光源描述 (Light)">
              <a-input v-model:value="envSections.light" placeholder="如：午后斜阳、烛台暖光、柔和自然散光" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="材质/风格 (Material/Style)">
              <a-input v-model:value="envSections.material" placeholder="如：宋代古典木构、青砖黛瓦、古拙朴素" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="禁止元素 (Forbidden)">
              <a-input v-model:value="envSections.forbidden" placeholder="如：现代电器、塑胶水管、英文标识" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="场景陈设与叙述性描述 (Description)">
          <a-textarea
            v-model:value="draftScene.description"
            placeholder="描述该场景在剧本中的陈设细节、环境氛围与剧情故事..."
            :rows="3"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 编辑道具弹窗 (严格对齐 source2 PropDialog) -->
    <a-modal
      v-model:open="editPropModalVisible"
      :title="`编辑道具「${draftProp.name || ''}」`"
      :confirm-loading="savingPropModal"
      ok-text="确认保存"
      cancel-text="取消"
      :width="640"
      destroy-on-close
      @ok="handleSavePropModal"
    >
      <a-form layout="vertical">
        <a-row :gutter="14">
          <a-col :span="10">
            <a-form-item label="道具名称" required>
              <a-input v-model:value="draftProp.name" placeholder="例如：旧木书箱" />
            </a-form-item>
          </a-col>
          <a-col :span="7">
            <a-form-item label="道具类型 (Prop Type)">
              <a-select v-model:value="draftProp.prop_type">
                <a-select-option value="weapon">武器 (Weapon)</a-select-option>
                <a-select-option value="accessory">饰品 (Accessory)</a-select-option>
                <a-select-option value="artifact">神器/法器 (Artifact)</a-select-option>
                <a-select-option value="document">文书 (Document)</a-select-option>
                <a-select-option value="furniture">家具 (Furniture)</a-select-option>
                <a-select-option value="object">其他物件 (Object)</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="7">
            <a-form-item label="所属角色 (Owner)">
              <a-input v-model:value="draftProp.owner" placeholder="例如：沈砚 专属信物" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="概念参考图提示词 (Visual Prompt)">
          <a-textarea
            v-model:value="draftProp.visual_prompt"
            placeholder="描述道具整体形态、材质、做旧与电影级工作室布光..."
            :rows="2"
          />
        </a-form-item>

        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="转面三视图提示词 (Turnaround)">
              <a-textarea
                v-model:value="draftProp.turnaround_prompt"
                placeholder="描述道具正视图、侧视图、背视图多方位设计..."
                :rows="2"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="细节特写提示词 (Detail Close-up)">
              <a-textarea
                v-model:value="draftProp.detail_prompt"
                placeholder="描述微距材质、刻字铭文、开刃磨损与质感..."
                :rows="2"
              />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="背景故事与叙述性描述 (Description)">
          <a-textarea
            v-model:value="draftProp.description"
            placeholder="记录该道具在剧本故事中的起源、象征意义或重要剧情推动作用..."
            :rows="3"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onBeforeUnmount, onMounted, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  Plus,
  Search,
  Boxes,
  Users,
  MapPin,
  Package,
  Sparkles,
  Save,
  Trash2,
  ExternalLink,
  Shirt,
  User,
  Camera,
  RefreshCw,
  Upload,
  Image as ImageIcon,
  Compass,
  Edit3,
  Layers,
  Eye,
} from 'lucide-vue-next'
import {
  listAssets,
  createAsset,
  generateCharacterContent,
  updateAsset,
  deleteAsset,
  generateAssetImage,
} from '../../api/projects'

const props = defineProps({
  projectId: { type: String, required: true },
})

const assets = ref([])
const selectedAsset = ref(null)
const loading = ref(false)
const saving = ref(false)
const autoSaveState = ref('idle')
const autoSaveStatusText = computed(() => ({
  idle: '修改后自动保存',
  pending: '有修改，准备保存',
  saving: '正在自动保存',
  saved: '已自动保存',
  error: '自动保存失败',
}[autoSaveState.value] || '修改后自动保存'))
let autoSaveTimer = null
let autoSaveQueuedSnapshot = null
let autoSaveRunner = null
let suppressAutoSave = false

// 各生成动作的独立 Loading 状态
const generatingAvatar = ref(false)
const generatingIdentityId = ref(null)
const batchGeneratingAvatars = ref(false)
const batchGeneratingLooks = ref(false)
const batchGeneratingSceneMasters = ref(false)
const batchGeneratingSceneReverses = ref(false)
const batchGeneratingScenePanos = ref(false)
const batchGeneratingPropReferences = ref(false)
const batchGeneratingPropTurnarounds = ref(false)
const batchGeneratingPropDetails = ref(false)
const generatingMaster = ref(false)
const generatingReverse = ref(false)
const generatingPano = ref(false)
const generatingProp = ref(false)
const generatingPropTurnaround = ref(false)
const generatingPropDetail = ref(false)

const batchGenerationActive = computed(() => [
  batchGeneratingAvatars,
  batchGeneratingLooks,
  batchGeneratingSceneMasters,
  batchGeneratingSceneReverses,
  batchGeneratingScenePanos,
  batchGeneratingPropReferences,
  batchGeneratingPropTurnarounds,
  batchGeneratingPropDetails,
].some((state) => state.value))

const submitting = ref(false)
const modalVisible = ref(false)
const characterAiModalVisible = ref(false)
const characterAiRequirement = ref('')
const generatingCharacterContent = ref(false)

// 场景编辑弹窗状态 (对齐 source2 SceneDialog)
const editSceneModalVisible = ref(false)
const savingSceneModal = ref(false)
const draftScene = ref({
  name: '',
  scene_type: 'interior',
  role: '',
  description: '',
})
const envSections = ref({
  front: '',
  back: '',
  left: '',
  right: '',
  light: '',
  material: '',
  forbidden: '',
})

// 道具编辑弹窗状态 (对齐 source2 PropDialog)
const editPropModalVisible = ref(false)
const savingPropModal = ref(false)
const draftProp = ref({
  name: '',
  prop_type: 'object',
  owner: '',
  visual_prompt: '',
  turnaround_prompt: '',
  detail_prompt: '',
  description: '',
})

// 360 全景查看器状态
const panoViewerVisible = ref(false)
const currentPanoUrl = ref('')

// 手动输入直链弹窗
const manualUrlModalVisible = ref(false)
const manualUrlTarget = ref('master')
const manualUrlInput = ref('')

const identityModalVisible = ref(false)
const savingIdentity = ref(false)
const identityForm = ref({
  name: '',
  description: '',
  visual_prompt: '',
})

// 去掉「全部」，默认显示「角色」
const currentTab = ref('character')
const searchKeyword = ref('')

const genConfig = ref({
  model: 'NanoBanana 标准',
  aspect_ratio: '1:1',
})

const createForm = ref({
  kind: 'character',
  name: '',
  role: '',
  description: '',
  visual_prompt: '',
  image_url: '',
})

// 仅保留 角色、场景、道具
const tabs = [
  { key: 'character', label: '角色' },
  { key: 'scene', label: '场景' },
  { key: 'prop', label: '道具' },
]

function getCountByKind(k) {
  return assets.value.filter((a) => a.kind === k).length
}

function kindLabel(k) {
  const map = { character: '角色', scene: '场景', prop: '道具' }
  return map[k] || k || '资产'
}

function getKindColor(k) {
  const map = { character: 'purple', scene: 'blue', prop: 'orange' }
  return map[k] || 'default'
}

function getKindIcon(k) {
  if (k === 'character') return Users
  if (k === 'scene') return MapPin
  return Package
}

function getKindMetaBadge(ast) {
  if (ast.kind === 'character') return '角色'
  if (ast.kind === 'scene') {
    return ast.extra?.scene_type === 'interior' ? '内景' : '实景'
  }
  return getPropTypeLabel(ast.extra?.prop_type)
}

function getPropTypeLabel(pt) {
  const map = {
    weapon: '武器',
    accessory: '饰品',
    artifact: '神器/法器',
    document: '文书',
    furniture: '家具',
    object: '其他物件',
    key_prop: '核心信物',
    stationery: '文房器具',
    daily: '日常随身',
    decor: '场景固定',
  }
  return map[pt] || pt || '物件'
}

function getSubRoleDisplay(ast) {
  if (ast.role) return ast.role
  if (ast.kind === 'character') return '主要角色'
  if (ast.kind === 'scene') return '拍摄场景'
  return ast.extra?.owner || '随行道具'
}

function getAssetDisplayAvatar(ast) {
  if (!ast) return ''
  if (ast.kind === 'character' && ast.extra?.avatar_url) {
    return ast.extra.avatar_url
  }
  if (ast.kind === 'scene' && (ast.extra?.master_url || ast.image_url)) {
    return ast.extra?.master_url || ast.image_url
  }
  if (ast.kind === 'prop') {
    return ast.extra?.reference_url || ast.extra?.turnaround_url || ast.extra?.detail_url || ast.image_url || ''
  }
  return ast.image_url || ''
}

const filteredAssets = computed(() => {
  let list = assets.value.filter((a) => a.kind === currentTab.value)
  const kw = searchKeyword.value.trim().toLowerCase()
  if (kw) {
    list = list.filter(
      (a) =>
        (a.name && a.name.toLowerCase().includes(kw)) ||
        (a.role && a.role.toLowerCase().includes(kw)) ||
        (a.description && a.description.toLowerCase().includes(kw))
    )
  }
  return list
})

function getAssetGradient(name) {
  const gradients = [
    'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
    'linear-gradient(135deg, #0ea5e9 0%, #22c55e 100%)',
    'linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)',
    'linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)',
    'linear-gradient(135deg, #7047f6 0%, #10b981 100%)',
  ]
  let hash = 0
  for (let i = 0; i < (name || '').length; i++) {
    hash = (hash << 5) - hash + name.charCodeAt(i)
    hash |= 0
  }
  return { background: gradients[Math.abs(hash) % gradients.length] }
}

function handleTabChange(tabKey) {
  currentTab.value = tabKey
  setTimeout(() => {
    if (filteredAssets.value.length > 0) {
      if (!selectedAsset.value || selectedAsset.value.kind !== tabKey) {
        selectAsset(filteredAssets.value[0])
      }
    } else {
      selectedAsset.value = null
    }
  }, 50)
}

function selectAsset(ast) {
  flushAutoSave()
  const copy = JSON.parse(JSON.stringify(ast))
  if (!copy.extra) copy.extra = {}

  if (copy.kind === 'character') {
    if (!copy.extra.identities) copy.extra.identities = []
    if (!copy.extra.avatar_prompt) {
      copy.extra.avatar_prompt = `${copy.name}，面部肖像，五官特写，眼神清亮坚毅，写实电影级光影，8k`
    }
  } else if (copy.kind === 'scene') {
    if (!copy.extra.environment_prompt) {
      copy.extra.environment_prompt = copy.visual_prompt || `${copy.name}，电影级实景空间，宋式古典建筑美学，自然光影，8k`
    }
    if (!copy.extra.reverse_prompt) {
      copy.extra.reverse_prompt = `${copy.name}，对立反打机位视角，180度对立景深透视，空间镜头，8k`
    }
    if (!copy.extra.pano_prompt) {
      copy.extra.pano_prompt = `${copy.name}，360度球形全景等距柱状图，无缝环视无死角，8k`
    }
  } else if (copy.kind === 'prop') {
    if (!copy.extra.visual_prompt) {
      copy.extra.visual_prompt = copy.visual_prompt || `${copy.name} 概念参考图，电影级质感，真实器物纹理光影，8k`
    }
    if (!copy.extra.turnaround_prompt) {
      copy.extra.turnaround_prompt = `${copy.name} 道具三视图转面设计，正视、侧视、背视，纯色背景，工业造型图纸，8k`
    }
    if (!copy.extra.detail_prompt) {
      copy.extra.detail_prompt = `${copy.name} 静物微距特写摄影，局部材质包浆与雕刻细节，8k`
    }
    if (!copy.extra.owner) {
      copy.extra.owner = copy.role || ''
    }
    if (!copy.extra.prop_type) {
      copy.extra.prop_type = 'object'
    }
  }

  suppressAutoSave = true
  selectedAsset.value = copy
  autoSaveState.value = 'idle'
  nextTick(() => {
    suppressAutoSave = false
  })
}

async function fetchAssets() {
  loading.value = true
  try {
    const res = await listAssets(props.projectId)
    assets.value = res || []
    const charList = assets.value.filter((a) => a.kind === currentTab.value)
    if (charList.length > 0) {
      if (!selectedAsset.value || selectedAsset.value.kind !== currentTab.value) {
        selectAsset(charList[0])
      } else {
        const found = assets.value.find((a) => a.id === selectedAsset.value.id)
        if (found) selectAsset(found)
      }
    } else if (assets.value.length > 0) {
      currentTab.value = assets.value[0].kind
      selectAsset(assets.value[0])
    } else {
      selectedAsset.value = null
    }
  } catch (err) {
    message.error('加载资产列表失败')
  } finally {
    loading.value = false
  }
}

function cloneAssetSnapshot(asset) {
  return asset ? JSON.parse(JSON.stringify(asset)) : null
}

async function runAutoSaveQueue() {
  while (autoSaveQueuedSnapshot) {
    const snapshot = autoSaveQueuedSnapshot
    autoSaveQueuedSnapshot = null
    if (!snapshot.name?.trim()) {
      autoSaveState.value = 'error'
      message.warning('名称不能为空，当前修改未保存')
      continue
    }
    saving.value = true
    autoSaveState.value = 'saving'
    try {
      const updated = await updateAsset(props.projectId, snapshot.id, snapshot)
      const idx = assets.value.findIndex((asset) => asset.id === snapshot.id)
      if (idx !== -1) assets.value[idx] = { ...updated }
      autoSaveState.value = (autoSaveQueuedSnapshot || autoSaveTimer) ? 'pending' : 'saved'
    } catch (err) {
      autoSaveState.value = 'error'
      message.error(err?.response?.data?.detail || '自动保存失败，请检查网络后继续修改')
    } finally {
      saving.value = false
    }
  }
}

function enqueueAutoSave(snapshot) {
  if (!snapshot?.id) return Promise.resolve()
  autoSaveQueuedSnapshot = snapshot
  if (!autoSaveRunner) {
    autoSaveRunner = runAutoSaveQueue().finally(() => {
      autoSaveRunner = null
      if (autoSaveQueuedSnapshot) enqueueAutoSave(autoSaveQueuedSnapshot)
    })
  }
  return autoSaveRunner
}

function flushAutoSave() {
  const hadPendingTimer = Boolean(autoSaveTimer)
  if (autoSaveTimer) {
    clearTimeout(autoSaveTimer)
    autoSaveTimer = null
  }
  if (selectedAsset.value && (hadPendingTimer || autoSaveState.value === 'pending')) {
    return enqueueAutoSave(cloneAssetSnapshot(selectedAsset.value))
  }
  return autoSaveRunner || Promise.resolve()
}

function persistPendingAssetBeforeUnload() {
  if (!selectedAsset.value || !['pending', 'saving'].includes(autoSaveState.value)) return
  const snapshot = cloneAssetSnapshot(selectedAsset.value)
  const body = JSON.stringify(snapshot)
  if (body.length > 60000) return
  const projectId = encodeURIComponent(props.projectId)
  const assetId = encodeURIComponent(snapshot.id)
  fetch(`/api/projects/${projectId}/assets/${assetId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body,
    keepalive: true,
  }).catch(() => {})
}

async function handleSaveDetail() {
  if (!selectedAsset.value) return
  autoSaveState.value = 'pending'
  await flushAutoSave()
}

watch(
  selectedAsset,
  (asset) => {
    if (suppressAutoSave || !asset?.id) return
    if (autoSaveTimer) clearTimeout(autoSaveTimer)
    autoSaveState.value = 'pending'
    autoSaveTimer = setTimeout(() => {
      autoSaveTimer = null
      enqueueAutoSave(cloneAssetSnapshot(selectedAsset.value))
    }, 700)
  },
  { deep: true },
)

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', persistPendingAssetBeforeUnload)
  flushAutoSave()
})

// 1. 生成角色头像 (1:1)
async function handleGenerateAvatar() {
  if (!selectedAsset.value) return
  const extra = selectedAsset.value.extra || {}
  const prompt = (extra.avatar_prompt || selectedAsset.value.name).trim()
  generatingAvatar.value = true
  try {
    const res = await generateAssetImage(props.projectId, selectedAsset.value.id, {
      target_type: 'avatar',
      prompt,
      model: 'gpt-image-2',
      aspect_ratio: '1:1',
      ...characterStylePayload(selectedAsset.value),
    })
    message.success(`「${selectedAsset.value.name}」头像生成成功！`)
    if (res.image_url) {
      if (!selectedAsset.value.extra) selectedAsset.value.extra = {}
      selectedAsset.value.extra.avatar_url = res.image_url
      selectedAsset.value.image_url = res.image_url

      const idx = assets.value.findIndex((a) => a.id === selectedAsset.value.id)
      if (idx !== -1 && res.asset) {
        assets.value[idx] = { ...res.asset }
      }
    }
  } catch (err) {
    message.error(err?.response?.data?.detail || '头像生图失败')
  } finally {
    generatingAvatar.value = false
  }
}

function applyGeneratedAsset(assetId, res) {
  if (!res?.asset) return
  const idx = assets.value.findIndex((a) => a.id === assetId)
  if (idx !== -1) {
    assets.value[idx] = { ...res.asset }
  }
  if (selectedAsset.value?.id === assetId) {
    selectedAsset.value = { ...res.asset }
  }
}

function characterStylePayload(ast) {
  const extra = ast?.extra || {}
  return {
    ethnicity: extra.ethnicity || 'Chinese',
    visual_style: extra.visual_style || '',
    art_style_id: extra.art_style_id || '',
    body_type: extra.body_type || '',
    gender: extra.gender || '',
  }
}

function hasCharacterAvatar(ast) {
  return Boolean(ast?.extra?.avatar_url || ast?.image_url)
}

async function handleBatchGenerateAvatars() {
  const chars = assets.value.filter((a) => a.kind === 'character')
  const targets = chars.filter((a) => !hasCharacterAvatar(a))
  if (!targets.length) {
    message.info(chars.length ? '所有角色已有头像，无需再生成' : '暂无角色可生成头像')
    return
  }
  batchGeneratingAvatars.value = true
  let ok = 0
  const failed = []
  message.loading({ content: `开始一键生成 ${targets.length} 个头像…`, key: 'batchAvatars' })
  try {
    for (let i = 0; i < targets.length; i += 1) {
      const ast = targets[i]
      message.loading({
        content: `正在生成头像 (${i + 1}/${targets.length})：${ast.name}`,
        key: 'batchAvatars',
      })
      try {
        const extra = ast.extra || {}
        const res = await generateAssetImage(props.projectId, ast.id, {
          target_type: 'avatar',
          prompt: (extra.avatar_prompt || ast.name || '').trim(),
          model: 'gpt-image-2',
          aspect_ratio: '1:1',
          ...characterStylePayload(ast),
        })
        applyGeneratedAsset(ast.id, res)
        ok += 1
      } catch (err) {
        failed.push(`${ast.name}: ${err?.response?.data?.detail || err?.message || '失败'}`)
      }
    }
    if (failed.length) {
      message.warning({
        content: `头像完成 ${ok}/${targets.length}，失败：${failed.slice(0, 3).join('；')}`,
        key: 'batchAvatars',
        duration: 6,
      })
    } else {
      message.success({ content: `已一键生成 ${ok} 个头像`, key: 'batchAvatars' })
    }
  } finally {
    batchGeneratingAvatars.value = false
  }
}

async function handleBatchGenerateLooks() {
  const chars = assets.value.filter((a) => a.kind === 'character')
  const jobs = []
  let skippedNoAvatar = 0
  let skippedNoCostume = 0
  for (const ast of chars) {
    if (!hasCharacterAvatar(ast)) {
      skippedNoAvatar += 1
      continue
    }
    for (const ident of ast.extra?.identities || []) {
      const costume = (ident.description || ident.appearance_details || '').trim()
      if (!costume) {
        skippedNoCostume += 1
        continue
      }
      if (ident.image_url) continue
      jobs.push({ ast, ident, costume })
    }
  }
  if (!jobs.length) {
    if (skippedNoAvatar && !chars.some((a) => hasCharacterAvatar(a))) {
      message.info('请先生成头像，造型图需要把头像作为身份锚点')
    } else {
      message.info('所有已有头像的角色造型图已就绪（或缺少外观描述）')
    }
    return
  }
  batchGeneratingLooks.value = true
  let ok = 0
  const failed = []
  message.loading({ content: `开始一键生成 ${jobs.length} 张造型图…`, key: 'batchLooks' })
  try {
    for (let i = 0; i < jobs.length; i += 1) {
      const { ast, ident, costume } = jobs[i]
      message.loading({
        content: `正在生成造型图 (${i + 1}/${jobs.length})：${ast.name} · ${ident.name}`,
        key: 'batchLooks',
      })
      try {
        const res = await generateAssetImage(props.projectId, ast.id, {
          target_type: 'identity',
          identity_id: ident.id,
          prompt: costume,
          model: 'gpt-image-2',
          aspect_ratio: '16:9',
          ...characterStylePayload(ast),
        })
        applyGeneratedAsset(ast.id, res)
        ok += 1
      } catch (err) {
        failed.push(`${ast.name}/${ident.name}: ${err?.response?.data?.detail || err?.message || '失败'}`)
      }
    }
    const skipHint = [
      skippedNoAvatar ? `${skippedNoAvatar} 个角色尚无头像已跳过` : '',
      skippedNoCostume ? `${skippedNoCostume} 个造型缺外观描述已跳过` : '',
    ].filter(Boolean).join('，')
    const skipSuffix = skipHint ? `，${skipHint}` : ''
    if (failed.length) {
      message.warning({
        content: `造型图完成 ${ok}/${jobs.length}${skipSuffix}，失败：${failed.slice(0, 3).join('；')}`,
        key: 'batchLooks',
        duration: 6,
      })
    } else {
      message.success({ content: `已一键生成 ${ok} 张造型图${skipSuffix}`, key: 'batchLooks' })
    }
  } finally {
    batchGeneratingLooks.value = false
  }
}

async function runBatchAssetGeneration({
  kind,
  loadingState,
  messageKey,
  label,
  targetType,
  aspectRatio,
  hasOutput,
  hasReference = () => true,
  referenceHint = '',
  buildPayload = () => ({}),
}) {
  const kindAssets = assets.value.filter((a) => a.kind === kind)
  const pending = kindAssets.filter((a) => !hasOutput(a))
  const targets = pending.filter(hasReference)
  const skipped = pending.length - targets.length

  if (!targets.length) {
    if (!kindAssets.length) {
      message.info(`暂无${kindLabel(kind)}可生成${label}`)
    } else if (skipped) {
      message.info(referenceHint)
    } else {
      message.info(`所有${kindLabel(kind)}${label}已就绪，无需再生成`)
    }
    return
  }

  loadingState.value = true
  let ok = 0
  const failed = []
  message.loading({ content: `开始一键生成 ${targets.length} 张${label}…`, key: messageKey })
  try {
    for (let i = 0; i < targets.length; i += 1) {
      const ast = targets[i]
      message.loading({
        content: `正在生成${label} (${i + 1}/${targets.length})：${ast.name}`,
        key: messageKey,
      })
      try {
        const res = await generateAssetImage(props.projectId, ast.id, {
          target_type: targetType,
          model: 'gpt-image-2',
          aspect_ratio: aspectRatio,
          ...buildPayload(ast),
        })
        applyGeneratedAsset(ast.id, res)
        ok += 1
      } catch (err) {
        failed.push(`${ast.name}: ${err?.response?.data?.detail || err?.message || '失败'}`)
      }
    }

    const skipSuffix = skipped ? `，${skipped} 个缺少前置图片已跳过` : ''
    if (failed.length) {
      message.warning({
        content: `${label}完成 ${ok}/${targets.length}${skipSuffix}，失败：${failed.slice(0, 3).join('；')}`,
        key: messageKey,
        duration: 6,
      })
    } else {
      message.success({ content: `已一键生成 ${ok} 张${label}${skipSuffix}`, key: messageKey })
    }
  } finally {
    loadingState.value = false
  }
}

function sceneStylePayload(ast) {
  const extra = ast?.extra || {}
  return {
    visual_style: extra.visual_style || '',
    art_style_id: extra.art_style_id || '',
  }
}

function hasSceneMaster(ast) {
  return Boolean(ast?.extra?.master_url || ast?.image_url)
}

function handleBatchGenerateSceneMasters() {
  return runBatchAssetGeneration({
    kind: 'scene',
    loadingState: batchGeneratingSceneMasters,
    messageKey: 'batchSceneMasters',
    label: '正面图',
    targetType: 'scene_master',
    aspectRatio: '16:9',
    hasOutput: hasSceneMaster,
    buildPayload: (ast) => ({
      prompt: (ast.extra?.environment_prompt || ast.visual_prompt || ast.name || '').trim(),
      ...sceneStylePayload(ast),
    }),
  })
}

function handleBatchGenerateSceneReverses() {
  return runBatchAssetGeneration({
    kind: 'scene',
    loadingState: batchGeneratingSceneReverses,
    messageKey: 'batchSceneReverses',
    label: '背面图',
    targetType: 'scene_reverse',
    aspectRatio: '16:9',
    hasOutput: (ast) => Boolean(ast.extra?.reverse_url),
    hasReference: hasSceneMaster,
    referenceHint: '请先生成场景正面图，背面图需要将正面图作为参考',
    buildPayload: sceneStylePayload,
  })
}

function handleBatchGenerateScenePanos() {
  return runBatchAssetGeneration({
    kind: 'scene',
    loadingState: batchGeneratingScenePanos,
    messageKey: 'batchScenePanos',
    label: '360图',
    targetType: 'scene_pano',
    aspectRatio: '2:1',
    hasOutput: (ast) => Boolean(ast.extra?.pano_url),
    hasReference: hasSceneMaster,
    referenceHint: '请先生成场景正面图，360 图需要将正面图作为参考',
    buildPayload: sceneStylePayload,
  })
}

function propStylePayload(ast) {
  const extra = ast?.extra || {}
  return {
    visual_style: extra.visual_style || '',
    art_style_id: extra.art_style_id || '',
  }
}

function hasPropReference(ast) {
  return Boolean(ast?.extra?.reference_url || ast?.image_url)
}

function handleBatchGeneratePropReferences() {
  return runBatchAssetGeneration({
    kind: 'prop',
    loadingState: batchGeneratingPropReferences,
    messageKey: 'batchPropReferences',
    label: '参考图',
    targetType: 'prop_reference',
    aspectRatio: '16:9',
    hasOutput: hasPropReference,
    buildPayload: propStylePayload,
  })
}

function handleBatchGeneratePropTurnarounds() {
  return runBatchAssetGeneration({
    kind: 'prop',
    loadingState: batchGeneratingPropTurnarounds,
    messageKey: 'batchPropTurnarounds',
    label: '三视图',
    targetType: 'prop_turnaround',
    aspectRatio: '16:9',
    hasOutput: (ast) => Boolean(ast.extra?.turnaround_url),
    hasReference: hasPropReference,
    referenceHint: '请先生成道具参考图，三视图需要将参考图作为参考',
    buildPayload: propStylePayload,
  })
}

function handleBatchGeneratePropDetails() {
  return runBatchAssetGeneration({
    kind: 'prop',
    loadingState: batchGeneratingPropDetails,
    messageKey: 'batchPropDetails',
    label: '细节图',
    targetType: 'prop_detail',
    aspectRatio: '16:9',
    hasOutput: (ast) => Boolean(ast.extra?.detail_url),
    hasReference: hasPropReference,
    referenceHint: '请先生成道具参考图，细节图需要将参考图作为参考',
    buildPayload: propStylePayload,
  })
}

// 2. 生成角色造型 (对齐 source1 look：16:9 四宫格)
async function handleGenerateIdentityImage(ident) {
  if (!selectedAsset.value || !ident) return
  const extra = selectedAsset.value.extra || {}
  const costume = (ident.description || ident.appearance_details || '').trim()
  if (!costume) {
    message.warning('请先填写外观描述，造型图需要服装关键词')
    return
  }
  if (!(extra.avatar_url || selectedAsset.value.image_url)) {
    message.warning('请先生成或上传肖像，造型图需要把它作为身份锚点传入')
    return
  }
  generatingIdentityId.value = ident.id
  try {
    const res = await generateAssetImage(props.projectId, selectedAsset.value.id, {
      target_type: 'identity',
      identity_id: ident.id,
      prompt: costume,
      model: 'gpt-image-2',
      aspect_ratio: '16:9',
      ...characterStylePayload(selectedAsset.value),
    })
    message.success(`造型「${ident.name}」造型图生成成功！`)
    if (res.image_url) {
      ident.image_url = res.image_url
      const idx = assets.value.findIndex((a) => a.id === selectedAsset.value.id)
      if (idx !== -1 && res.asset) {
        assets.value[idx] = { ...res.asset }
      }
    }
  } catch (err) {
    message.error(err?.response?.data?.detail || '造型形象生成失败')
  } finally {
    generatingIdentityId.value = null
  }
}

// 3. 生成场景 Master 主视角 (16:9)
async function handleGenerateSceneMaster() {
  if (!selectedAsset.value) return
  const prompt = (selectedAsset.value.extra?.environment_prompt || selectedAsset.value.visual_prompt || selectedAsset.value.name).trim()
  generatingMaster.value = true
  try {
    const res = await generateAssetImage(props.projectId, selectedAsset.value.id, {
      target_type: 'scene_master',
      prompt,
      aspect_ratio: '16:9',
    })
    message.success(`场景「${selectedAsset.value.name}」Master 主视角生成成功！`)
    if (res.image_url) {
      if (!selectedAsset.value.extra) selectedAsset.value.extra = {}
      selectedAsset.value.extra.master_url = res.image_url
      selectedAsset.value.image_url = res.image_url

      const idx = assets.value.findIndex((a) => a.id === selectedAsset.value.id)
      if (idx !== -1 && res.asset) {
        assets.value[idx] = { ...res.asset }
      }
    }
  } catch (err) {
    message.error(err?.response?.data?.detail || '主视角生成失败')
  } finally {
    generatingMaster.value = false
  }
}

// 4. 生成场景 Reverse 背面（对齐 source1：16:9 + Master 为 REFERENCE 1）
async function handleGenerateSceneReverse() {
  if (!selectedAsset.value) return
  const extra = selectedAsset.value.extra || {}
  const master = (extra.master_url || selectedAsset.value.image_url || '').trim()
  if (!master) {
    message.warning('请先生成或上传正面源图，背面图需要把它作为 REFERENCE 1 传入')
    return
  }
  generatingReverse.value = true
  try {
    const res = await generateAssetImage(props.projectId, selectedAsset.value.id, {
      target_type: 'scene_reverse',
      model: 'gpt-image-2',
      aspect_ratio: '16:9',
      visual_style: extra.visual_style || '',
      art_style_id: extra.art_style_id || '',
    })
    message.success(`场景「${selectedAsset.value.name}」Reverse 背面反打视角生成成功！`)
    if (res.image_url) {
      if (!selectedAsset.value.extra) selectedAsset.value.extra = {}
      selectedAsset.value.extra.reverse_url = res.image_url

      const idx = assets.value.findIndex((a) => a.id === selectedAsset.value.id)
      if (idx !== -1 && res.asset) {
        assets.value[idx] = { ...res.asset }
      }
    }
  } catch (err) {
    message.error(err?.response?.data?.detail || '反打视角生成失败')
  } finally {
    generatingReverse.value = false
  }
}

// 5. 生成场景 Pano 360（对齐 source1：2:1 + Master/Reverse 参考图）
async function handleGenerateScenePano() {
  if (!selectedAsset.value) return
  const extra = selectedAsset.value.extra || {}
  const master = (extra.master_url || selectedAsset.value.image_url || '').trim()
  if (!master) {
    message.warning('请先生成或上传正面源图，360全景需要把它作为 REFERENCE 1 传入')
    return
  }
  generatingPano.value = true
  try {
    const res = await generateAssetImage(props.projectId, selectedAsset.value.id, {
      target_type: 'scene_pano',
      model: 'gpt-image-2',
      aspect_ratio: '2:1',
      visual_style: extra.visual_style || '',
      art_style_id: extra.art_style_id || '',
    })
    message.success(`场景「${selectedAsset.value.name}」360° 全景图生成成功！`)
    if (res.image_url) {
      if (!selectedAsset.value.extra) selectedAsset.value.extra = {}
      selectedAsset.value.extra.pano_url = res.image_url

      const idx = assets.value.findIndex((a) => a.id === selectedAsset.value.id)
      if (idx !== -1 && res.asset) {
        assets.value[idx] = { ...res.asset }
      }
    }
  } catch (err) {
    message.error(err?.response?.data?.detail || '360 全景图生成失败')
  } finally {
    generatingPano.value = false
  }
}

// 6. 生成道具主视图（对齐 source1：16:9 产品静物正面）
async function handleGeneratePropReference() {
  if (!selectedAsset.value) return
  const extra = selectedAsset.value.extra || {}
  generatingProp.value = true
  try {
    const res = await generateAssetImage(props.projectId, selectedAsset.value.id, {
      target_type: 'prop_reference',
      model: 'gpt-image-2',
      aspect_ratio: '16:9',
      visual_style: extra.visual_style || '',
      art_style_id: extra.art_style_id || '',
    })
    message.success(`道具「${selectedAsset.value.name}」参考图生成成功！`)
    if (res.image_url) {
      if (!selectedAsset.value.extra) selectedAsset.value.extra = {}
      selectedAsset.value.extra.reference_url = res.image_url
      selectedAsset.value.image_url = res.image_url

      const idx = assets.value.findIndex((a) => a.id === selectedAsset.value.id)
      if (idx !== -1 && res.asset) {
        assets.value[idx] = { ...res.asset }
      }
    }
  } catch (err) {
    message.error(err?.response?.data?.detail || '道具参考图生成失败')
  } finally {
    generatingProp.value = false
  }
}

// 7. 生成道具转面三视图（对齐 source1：16:9 1x3 + 主视图 REFERENCE 1）
async function handleGeneratePropTurnaround() {
  if (!selectedAsset.value) return
  const extra = selectedAsset.value.extra || {}
  const master = (extra.reference_url || selectedAsset.value.image_url || '').trim()
  if (!master) {
    message.warning('请先生成或上传主视图，转面三视图需要把它作为 REFERENCE 1 传入')
    return
  }
  generatingPropTurnaround.value = true
  try {
    const res = await generateAssetImage(props.projectId, selectedAsset.value.id, {
      target_type: 'prop_turnaround',
      model: 'gpt-image-2',
      aspect_ratio: '16:9',
      visual_style: extra.visual_style || '',
      art_style_id: extra.art_style_id || '',
    })
    message.success(`道具「${selectedAsset.value.name}」三视图生成成功！`)
    if (res.image_url) {
      if (!selectedAsset.value.extra) selectedAsset.value.extra = {}
      selectedAsset.value.extra.turnaround_url = res.image_url

      const idx = assets.value.findIndex((a) => a.id === selectedAsset.value.id)
      if (idx !== -1 && res.asset) {
        assets.value[idx] = { ...res.asset }
      }
    }
  } catch (err) {
    message.error(err?.response?.data?.detail || '三视图生成失败')
  } finally {
    generatingPropTurnaround.value = false
  }
}

// 8. 生成道具细节特写（对齐 source1：16:9 微距 + 主视图 REFERENCE 1）
async function handleGeneratePropDetail() {
  if (!selectedAsset.value) return
  const extra = selectedAsset.value.extra || {}
  const master = (extra.reference_url || selectedAsset.value.image_url || '').trim()
  if (!master) {
    message.warning('请先生成或上传主视图，细节特写需要把它作为 REFERENCE 1 传入')
    return
  }
  generatingPropDetail.value = true
  try {
    const res = await generateAssetImage(props.projectId, selectedAsset.value.id, {
      target_type: 'prop_detail',
      model: 'gpt-image-2',
      aspect_ratio: '16:9',
      visual_style: extra.visual_style || '',
      art_style_id: extra.art_style_id || '',
    })
    message.success(`道具「${selectedAsset.value.name}」细节特写生成成功！`)
    if (res.image_url) {
      if (!selectedAsset.value.extra) selectedAsset.value.extra = {}
      selectedAsset.value.extra.detail_url = res.image_url

      const idx = assets.value.findIndex((a) => a.id === selectedAsset.value.id)
      if (idx !== -1 && res.asset) {
        assets.value[idx] = { ...res.asset }
      }
    }
  } catch (err) {
    message.error(err?.response?.data?.detail || '细节特写生成失败')
  } finally {
    generatingPropDetail.value = false
  }
}

// 删除场景视角图片
async function handleDeleteSceneImage(slotType) {
  if (!selectedAsset.value?.extra) return
  if (slotType === 'master') {
    selectedAsset.value.extra.master_url = ''
    selectedAsset.value.image_url = ''
  } else if (slotType === 'reverse') {
    selectedAsset.value.extra.reverse_url = ''
  } else if (slotType === 'pano') {
    selectedAsset.value.extra.pano_url = ''
  }
  await handleSaveDetail()
  message.success(`已删除 ${slotType.toUpperCase()} 图片`)
}

// 删除道具视角图片
async function handleDeletePropImage(slot = 'reference') {
  if (!selectedAsset.value?.extra) return
  if (slot === 'reference') {
    selectedAsset.value.extra.reference_url = ''
    selectedAsset.value.image_url = ''
  } else if (slot === 'turnaround') {
    selectedAsset.value.extra.turnaround_url = ''
  } else if (slot === 'detail') {
    selectedAsset.value.extra.detail_url = ''
  }
  await handleSaveDetail()
  message.success('已清除对应视角图片')
}

// 360 空间环境合同 (七大维度) 解析与序列化 (严格对齐 source2 scene-environment-prompt.tsx)
function parseEnvironmentPrompt(prompt) {
  const res = { front: '', back: '', left: '', right: '', light: '', material: '', forbidden: '' }
  if (!prompt) return res
  const text = prompt.replace(/\r\n/g, '\n').trim()
  const map = {
    '正面': 'front', '正面描述': 'front',
    '背面': 'back', '背面描述': 'back',
    '左侧': 'left', '左侧描述': 'left',
    '右侧': 'right', '右侧描述': 'right',
    '光源': 'light', '光源描述': 'light',
    '材质/风格': 'material', '材质': 'material', '风格': 'material',
    '禁止元素': 'forbidden', '禁止': 'forbidden',
  }
  const regex = /(?:^|\n)\s*(正面|背面|左侧|右侧|光源|材质\/风格|材质|禁止元素|禁止)\s*[:：]([\s\S]*?)(?=(?:\n\s*(?:正面|背面|左侧|右侧|光源|材质\/风格|材质|禁止元素|禁止)\s*[:：]|$))/g
  let match
  let count = 0
  while ((match = regex.exec(text)) !== null) {
    count++
    const k = map[match[1]]
    if (k) res[k] = match[2].trim()
  }
  if (count === 0) {
    res.front = text
  }
  return res
}

function serializeEnvironmentPrompt(sections) {
  const lines = []
  if (sections.front?.trim()) lines.push(`正面：${sections.front.trim()}`)
  if (sections.back?.trim()) lines.push(`背面：${sections.back.trim()}`)
  if (sections.left?.trim()) lines.push(`左侧：${sections.left.trim()}`)
  if (sections.right?.trim()) lines.push(`右侧：${sections.right.trim()}`)
  if (sections.light?.trim()) lines.push(`光源：${sections.light.trim()}`)
  if (sections.material?.trim()) lines.push(`材质/风格：${sections.material.trim()}`)
  if (sections.forbidden?.trim()) lines.push(`禁止元素：${sections.forbidden.trim()}`)
  return lines.join('\n')
}

// 场景编辑弹窗
function openEditSceneModal() {
  if (!selectedAsset.value) return
  draftScene.value = {
    name: selectedAsset.value.name || '',
    scene_type: selectedAsset.value.extra?.scene_type || 'interior',
    role: selectedAsset.value.role || '',
    description: selectedAsset.value.description || '',
  }
  envSections.value = parseEnvironmentPrompt(selectedAsset.value.extra?.environment_prompt || '')
  editSceneModalVisible.value = true
}

async function handleSaveSceneModal() {
  if (!draftScene.value.name.trim()) {
    message.warning('场景名称不能为空')
    return
  }
  savingSceneModal.value = true
  try {
    const envPrompt = serializeEnvironmentPrompt(envSections.value)
    if (!selectedAsset.value.extra) selectedAsset.value.extra = {}
    selectedAsset.value.name = draftScene.value.name
    selectedAsset.value.role = draftScene.value.role
    selectedAsset.value.description = draftScene.value.description
    selectedAsset.value.extra.scene_type = draftScene.value.scene_type
    selectedAsset.value.extra.environment_prompt = envPrompt
    selectedAsset.value.visual_prompt = envPrompt

    const updated = await updateAsset(props.projectId, selectedAsset.value.id, selectedAsset.value)
    message.success('场景设定已保存更新')
    editSceneModalVisible.value = false
    const idx = assets.value.findIndex((a) => a.id === selectedAsset.value.id)
    if (idx !== -1) assets.value[idx] = { ...updated }
  } catch (err) {
    message.error('保存场景失败')
  } finally {
    savingSceneModal.value = false
  }
}

// 道具编辑弹窗 (严格对齐 source2 PropDialog)
function openEditPropModal() {
  if (!selectedAsset.value) return
  draftProp.value = {
    name: selectedAsset.value.name || '',
    prop_type: selectedAsset.value.extra?.prop_type || 'object',
    owner: selectedAsset.value.extra?.owner || selectedAsset.value.role || '',
    visual_prompt: selectedAsset.value.extra?.visual_prompt || selectedAsset.value.visual_prompt || '',
    turnaround_prompt: selectedAsset.value.extra?.turnaround_prompt || '',
    detail_prompt: selectedAsset.value.extra?.detail_prompt || '',
    description: selectedAsset.value.description || '',
  }
  editPropModalVisible.value = true
}

async function handleSavePropModal() {
  if (!draftProp.value.name.trim()) {
    message.warning('道具名称不能为空')
    return
  }
  savingPropModal.value = true
  try {
    if (!selectedAsset.value.extra) selectedAsset.value.extra = {}
    selectedAsset.value.name = draftProp.value.name
    selectedAsset.value.role = draftProp.value.owner
    selectedAsset.value.description = draftProp.value.description
    selectedAsset.value.extra.owner = draftProp.value.owner
    selectedAsset.value.extra.prop_type = draftProp.value.prop_type
    selectedAsset.value.extra.visual_prompt = draftProp.value.visual_prompt
    selectedAsset.value.extra.turnaround_prompt = draftProp.value.turnaround_prompt
    selectedAsset.value.extra.detail_prompt = draftProp.value.detail_prompt
    selectedAsset.value.visual_prompt = draftProp.value.visual_prompt

    const updated = await updateAsset(props.projectId, selectedAsset.value.id, selectedAsset.value)
    message.success('道具设定已保存更新')
    editPropModalVisible.value = false
    const idx = assets.value.findIndex((a) => a.id === selectedAsset.value.id)
    if (idx !== -1) assets.value[idx] = { ...updated }
  } catch (err) {
    message.error('保存道具失败')
  } finally {
    savingPropModal.value = false
  }
}

// 360 全景查看器
function openPanoViewerModal(url) {
  currentPanoUrl.value = url
  panoViewerVisible.value = true
}

// 点击放大查看图片
function openImageLightbox(url, title) {
  if (!url) return
  window.open(url, '_blank')
}

// 手动指定 URL
function triggerManualUrlInput(target) {
  manualUrlTarget.value = target
  manualUrlInput.value = ''
  manualUrlModalVisible.value = true
}

async function handleConfirmManualUrl() {
  if (!manualUrlInput.value.trim()) {
    message.warning('请输入图片链接')
    return
  }
  const url = manualUrlInput.value.trim()
  if (!selectedAsset.value.extra) selectedAsset.value.extra = {}

  if (manualUrlTarget.value === 'master') {
    selectedAsset.value.extra.master_url = url
    selectedAsset.value.image_url = url
  } else if (manualUrlTarget.value === 'reverse') {
    selectedAsset.value.extra.reverse_url = url
  } else if (manualUrlTarget.value === 'pano') {
    selectedAsset.value.extra.pano_url = url
  } else if (manualUrlTarget.value === 'prop' || manualUrlTarget.value === 'prop_reference') {
    selectedAsset.value.extra.reference_url = url
    selectedAsset.value.image_url = url
  } else if (manualUrlTarget.value === 'prop_turnaround') {
    selectedAsset.value.extra.turnaround_url = url
  } else if (manualUrlTarget.value === 'prop_detail') {
    selectedAsset.value.extra.detail_url = url
  }

  manualUrlModalVisible.value = false
  await handleSaveDetail()
}

// 新增身份/造型弹窗
function openAddIdentityModal() {
  if (!selectedAsset.value) return
  const currentCount = selectedAsset.value.extra?.identities?.length || 0
  identityForm.value = {
    name: `造型 ${currentCount + 1}`,
    description: '',
    visual_prompt: `${selectedAsset.value.name} 全身立绘，宋代概念美术设计，电影级质感，8k`,
  }
  identityModalVisible.value = true
}

async function handleConfirmAddIdentity() {
  if (!identityForm.value.name.trim()) {
    message.warning('请输入造型名称')
    return
  }
  savingIdentity.value = true
  try {
    if (!selectedAsset.value.extra) selectedAsset.value.extra = {}
    if (!selectedAsset.value.extra.identities) selectedAsset.value.extra.identities = []

    const newId = `ident-${Date.now().toString(36)}`
    selectedAsset.value.extra.identities.push({
      id: newId,
      name: identityForm.value.name.trim(),
      description: identityForm.value.description.trim(),
      visual_prompt: identityForm.value.visual_prompt.trim(),
      image_url: '',
    })

    const updated = await updateAsset(props.projectId, selectedAsset.value.id, selectedAsset.value)
    message.success(`已为「${selectedAsset.value.name}」新增造型「${identityForm.value.name}」`)
    const idx = assets.value.findIndex((a) => a.id === selectedAsset.value.id)
    if (idx !== -1) {
      assets.value[idx] = { ...updated }
    }
    identityModalVisible.value = false
  } catch (err) {
    message.error('新增造型失败')
  } finally {
    savingIdentity.value = false
  }
}

async function handleRemoveIdentity(idx) {
  if (!selectedAsset.value?.extra?.identities) return
  selectedAsset.value.extra.identities.splice(idx, 1)
  try {
    const updated = await updateAsset(props.projectId, selectedAsset.value.id, selectedAsset.value)
    message.success('造型已删除')
    const i = assets.value.findIndex((a) => a.id === selectedAsset.value.id)
    if (i !== -1) {
      assets.value[i] = { ...updated }
    }
  } catch (err) {
    message.error('删除造型失败')
  }
}

function resetAvatarPrompt() {
  if (!selectedAsset.value) return
  if (!selectedAsset.value.extra) selectedAsset.value.extra = {}
  selectedAsset.value.extra.avatar_prompt = `${selectedAsset.value.name}，面部肖像特写，五官分明，眼神清澈坚毅，中国古代少年，极简中性灰色背景，柔和电影级布光，8k`
  message.success('已重置为推荐特写提示词')
}

async function handleDeleteAsset(id) {
  try {
    await deleteAsset(props.projectId, id)
    message.success('资产已删除')
    await fetchAssets()
  } catch (err) {
    message.error('删除失败')
  }
}

function openCreateModal() {
  createForm.value = {
    kind: currentTab.value,
    name: '',
    role: '',
    description: '',
    visual_prompt: '',
    image_url: '',
  }
  modalVisible.value = true
}

function openCharacterAiModal() {
  characterAiRequirement.value = ''
  characterAiModalVisible.value = true
}

async function handleGenerateCharacterContent() {
  const requirement = characterAiRequirement.value.trim()
  if (!requirement) {
    message.warning('请输入角色简洁需求')
    return
  }
  generatingCharacterContent.value = true
  try {
    const generated = await generateCharacterContent(props.projectId, {
      requirement,
      name: createForm.value.name,
      role: createForm.value.role,
    })
    createForm.value.description = generated.description || ''
    createForm.value.visual_prompt = generated.visual_prompt || ''
    characterAiModalVisible.value = false
    message.success('角色内容已生成并回填')
  } catch (err) {
    message.error(err?.response?.data?.detail || 'AI 生成角色内容失败')
  } finally {
    generatingCharacterContent.value = false
  }
}

async function handleCreateSubmit() {
  if (!createForm.value.name.trim()) {
    message.warning('请输入名称')
    return
  }
  submitting.value = true
  try {
    const created = await createAsset(props.projectId, createForm.value)
    message.success(`「${created.name}」创建成功`)
    modalVisible.value = false
    currentTab.value = created.kind
    await fetchAssets()
    if (created && created.id) {
      const found = assets.value.find((a) => a.id === created.id)
      if (found) selectAsset(found)
    }
  } catch (err) {
    message.error(err?.response?.data?.detail || '创建失败')
  } finally {
    submitting.value = false
  }
}

function copyText(text) {
  const p = (text || '').trim()
  if (!p) {
    message.warning('内容为空')
    return
  }
  navigator.clipboard.writeText(p).then(() => {
    message.success('已复制到剪贴板')
  }).catch(() => {
    message.info('请手动复制')
  })
}

defineExpose({ fetchAssets })

onMounted(() => {
  window.addEventListener('beforeunload', persistPendingAssetBeforeUnload)
  fetchAssets()
})
</script>

<style scoped>
.assets-library-pane {
  padding: 4px 0;
}

.sub-pane-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  gap: 20px;
}

.header-copy {
  flex: 1;
  min-width: 220px;
}

.header-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-shrink: 0;
}

.batch-generate-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin: -4px 0 16px;
}

.batch-generate-hint {
  font-size: 12px;
  color: #6b7280;
}

.sub-pane-title {
  font-size: 20px;
  font-weight: 700;
  color: #111827;
  margin: 0 0 4px;
}

.sub-pane-subtitle {
  font-size: 13px;
  color: #6b7280;
  margin: 0;
}

.stats-pills {
  display: flex;
  gap: 6px;
}

.stat-pill {
  font-size: 12px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  padding: 4px 10px;
  border-radius: 20px;
  color: #4b5563;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.stat-pill:hover,
.stat-pill.active {
  border-color: #7047f6;
  color: #7047f6;
  background: rgba(112, 71, 246, 0.05);
}

.primary-btn {
  background: linear-gradient(135deg, #7047f6 0%, #8b5cf6 100%);
  border: none;
}

.empty-asset-box {
  background: #ffffff;
  border: 1px dashed rgba(0, 0, 0, 0.1);
  border-radius: 12px;
  padding: 64px 20px;
  text-align: center;
}

.empty-icon {
  color: #9ca3af;
  margin-bottom: 16px;
}

/* 左右分栏结构 (参考 source2) */
.assets-split-container {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  min-height: 640px;
}

/* 左侧列表侧边栏 */
.assets-sidebar-list {
  width: 320px;
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px;
  padding: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sidebar-tabs {
  display: flex;
  background: #f3f4f6;
  padding: 3px;
  border-radius: 8px;
}

.sidebar-tab-item {
  flex: 1;
  text-align: center;
  font-size: 12px;
  padding: 6px 2px;
  border-radius: 6px;
  cursor: pointer;
  color: #4b5563;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  transition: all 0.2s;
}

.sidebar-tab-item.active {
  background: #ffffff;
  color: #7047f6;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.tab-count-badge {
  font-size: 10px;
  opacity: 0.8;
}

.sidebar-search-box {
  margin-top: 2px;
}

.sidebar-items-scroll {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: calc(100vh - 270px);
  min-height: 480px;
  overflow-y: auto;
  padding-right: 2px;
}

.no-filter-match {
  padding: 40px 10px;
  text-align: center;
  font-size: 12px;
  color: #9ca3af;
}

.asset-list-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  background: #fafafa;
  border: 1px solid transparent;
  transition: all 0.2s;
  position: relative;
}

.asset-list-item:hover {
  background: #f3f4f6;
}

.asset-list-item.active {
  background: rgba(112, 71, 246, 0.08);
  border-color: rgba(112, 71, 246, 0.35);
}

.item-avatar {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  color: #ffffff;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 15px;
  flex-shrink: 0;
  overflow: hidden;
  position: relative;
}

.item-avatar.scene {
  aspect-ratio: 16/9;
  width: 50px;
  height: 36px;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.has-image-dot {
  position: absolute;
  bottom: 2px;
  right: 2px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #10b981;
  border: 1px solid #ffffff;
}

.item-info {
  flex: 1;
  min-width: 0;
}

.item-name-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2px;
}

.item-name {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kind-tag {
  margin: 0;
  transform: scale(0.9);
  transform-origin: right center;
}

.item-sub-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
}

.item-role {
  display: block;
  font-size: 11px;
  color: #6b7280;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.extra-count-chip {
  font-size: 10px;
  background: rgba(112, 71, 246, 0.1);
  color: #7047f6;
  padding: 1px 5px;
  border-radius: 4px;
  font-weight: 500;
  white-space: nowrap;
}

.extra-count-chip.scene-chip {
  background: rgba(14, 165, 233, 0.1);
  color: #0284c7;
}

.extra-count-chip.prop-chip {
  background: rgba(245, 158, 11, 0.1);
  color: #d97706;
}

.item-active-bar {
  position: absolute;
  right: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 3px 0 0 3px;
  background: #7047f6;
}

/* 右侧详情与生成工作区 */
.asset-detail-workspace {
  flex: 1;
  min-width: 0;
}

.empty-detail-state {
  background: #ffffff;
  border: 1px dashed rgba(0, 0, 0, 0.1);
  border-radius: 12px;
  padding: 80px 20px;
  text-align: center;
}

.empty-detail-icon {
  width: 64px;
  height: 64px;
  border-radius: 16px;
  background: #f3f4f6;
  color: #9ca3af;
  display: grid;
  place-items: center;
  margin: 0 auto 16px;
}

.empty-detail-state h4 {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 6px;
}

.empty-detail-state p {
  font-size: 13px;
  color: #6b7280;
  margin: 0;
}

.detail-content-wrap {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-header-card {
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px;
  padding: 16px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}

.header-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.detail-asset-name {
  font-size: 20px;
  font-weight: 700;
  color: #111827;
  margin: 0;
}

.update-time {
  font-size: 12px;
  color: #9ca3af;
  margin-left: 4px;
}

.add-identity-btn {
  color: #7047f6;
  border-color: #7047f6;
}

.auto-save-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 112px;
  color: #64748b;
  font-size: 12px;
  white-space: nowrap;
}

.auto-save-status.is-saving,
.auto-save-status.is-pending {
  color: #2563eb;
}

.auto-save-status.is-saved {
  color: #059669;
}

.auto-save-status.is-error {
  color: #dc2626;
}

/* 通用板块卡片 */
.section-card {
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px;
  padding: 18px 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  border-bottom: 1px solid #f3f4f6;
  padding-bottom: 12px;
}

.section-title-wrap {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.section-icon-badge {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.avatar-badge {
  background: rgba(112, 71, 246, 0.1);
  color: #7047f6;
}

.costume-badge {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.scene-badge {
  background: rgba(14, 165, 233, 0.1);
  color: #0284c7;
}

.prop-badge {
  background: rgba(245, 158, 11, 0.1);
  color: #d97706;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: #111827;
  margin: 0 0 2px;
}

.title-with-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.identity-count-tag {
  font-size: 11px;
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
  padding: 1px 8px;
  border-radius: 12px;
  font-weight: 600;
}

.meta-chip {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 12px;
  font-weight: 600;
  background: #f3f4f6;
  color: #6b7280;
  border: 1px solid #e5e7eb;
}

.meta-chip.type-chip {
  background: #f0f9ff;
  color: #0284c7;
  border-color: #bae6fd;
}

.meta-chip.prop-chip {
  background: #fffbeb;
  color: #d97706;
  border-color: #fde68a;
}

.meta-chip.ok {
  background: #ecfdf5;
  color: #059669;
  border-color: #a7f3d0;
}

.owner-indicator {
  font-size: 12px;
  color: #4b5563;
  margin: 2px 0;
}

.owner-name {
  font-weight: 600;
  color: #111827;
}

.section-desc {
  font-size: 12px;
  color: #6b7280;
  margin: 2px 0 0;
}

/* ================== A. 角色工作区样式 ================== */
.character-workspace-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.portrait-content-grid {
  display: grid;
  grid-template-columns: 190px 1fr;
  gap: 20px;
  align-items: flex-start;
}

.portrait-preview-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.avatar-box {
  width: 180px;
  height: 180px;
  border-radius: 12px;
  overflow: hidden;
  background: #1e1e2d;
  position: relative;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  border: 2px solid #f3f4f6;
}

.avatar-img-view {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s;
}

.avatar-img-view:hover {
  transform: scale(1.04);
}

.avatar-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #ffffff;
}

.placeholder-char {
  font-size: 40px;
  font-weight: 700;
  line-height: 1;
}

.placeholder-tip {
  font-size: 11px;
  opacity: 0.8;
  margin-top: 6px;
}

.float-view-btn {
  position: absolute;
  top: 6px;
  right: 6px;
  background: rgba(0, 0, 0, 0.6);
  color: #ffffff;
  width: 24px;
  height: 24px;
  border-radius: 4px;
  display: grid;
  place-items: center;
  backdrop-filter: blur(4px);
  transition: all 0.2s;
}

.float-view-btn:hover {
  background: rgba(0, 0, 0, 0.85);
  color: #ffffff;
}

.avatar-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 180px;
}

.avatar-gen-btn {
  background: linear-gradient(135deg, #7047f6 0%, #8b5cf6 100%);
  border: none;
  font-size: 13px;
  font-weight: 600;
  border-radius: 8px;
}

.model-select-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sub-label {
  font-size: 11px;
  color: #6b7280;
  white-space: nowrap;
}

.prompt-field-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-title-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.field-label {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  display: flex;
  align-items: center;
  gap: 6px;
}

.text-purple {
  color: #7047f6;
}

.text-orange {
  color: #d97706;
}

.text-blue {
  color: #0284c7;
}

.custom-textarea {
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
}

.field-hint {
  font-size: 11px;
  color: #9ca3af;
}

/* 角色定义表单 */
.char-definition-form {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.def-form-title {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  padding-bottom: 6px;
  border-bottom: 1px solid #f3f4f6;
}

.def-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.def-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.def-field-sm {
  flex: 2;
  min-width: 0;
}

.def-field-lg {
  flex: 3;
  min-width: 0;
}

.def-label {
  font-size: 12px;
  font-weight: 500;
  color: #4b5563;
  line-height: 1.3;
}

/* 造型区网格 */
.identities-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.identity-card {
  background: #fafbfc;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 14px 16px;
  transition: border-color 0.2s;
}

.identity-card:hover {
  border-color: #cbd5e1;
}

.ident-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px dashed #e5e7eb;
}

.ident-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}

.ident-index-badge {
  font-size: 11px;
  background: #f3f4f6;
  color: #4b5563;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.ident-name-input {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
  border: 1px solid transparent;
  background: transparent;
  padding: 2px 6px;
  border-radius: 4px;
  outline: none;
  max-width: 320px;
  transition: all 0.2s;
}

.ident-name-input:hover,
.ident-name-input:focus {
  background: #ffffff;
  border-color: #d1d5db;
}

.delete-ident-btn {
  color: #9ca3af;
}

.delete-ident-btn:hover {
  color: #ef4444;
}

.ident-card-body {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 18px;
  align-items: flex-start;
}

.ident-image-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 320px;
}

.ident-img-frame {
  width: 320px;
  aspect-ratio: 16 / 9;
  height: auto;
  border-radius: 8px;
  overflow: hidden;
  background: #181824;
  position: relative;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  border: 1px solid #e5e7eb;
}

.ident-img-view {
  width: 100%;
  height: 100%;
  object-fit: contain;
  transition: transform 0.3s;
}

.ident-img-view:hover {
  transform: scale(1.04);
}

.ident-img-empty {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: #9ca3af;
}

.empty-shirt-icon {
  opacity: 0.6;
}

.empty-shirt-text {
  font-size: 11px;
}

.ident-gen-btn {
  background: #10b981;
  border: none;
  font-size: 12px;
  font-weight: 500;
  border-radius: 6px;
}

.ident-info-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ident-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ident-field-label {
  font-size: 12px;
  font-weight: 600;
  color: #4b5563;
}

.mini-link-btn {
  padding: 0;
  height: auto;
  font-size: 11px;
}

.add-costume-btn {
  background: #7047f6;
  border: none;
  font-size: 12px;
}

/* ================== B. 场景三大机位工作区 (严格参考 source2 scene-asset-card) ================== */
.scene-workspace-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.scene-three-columns-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 10px;
}

@media (max-width: 1200px) {
  .scene-three-columns-grid {
    grid-template-columns: 1fr;
  }
}

.scene-slot-column {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: #fafbfc;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 12px;
}

/* 核心插槽 AssetImageSlot 样式 (完全参考 source2 AssetImageSlot) */
.asset-image-slot {
  width: 100%;
}

.slot-preview-frame {
  position: relative;
  width: 100%;
  aspect-ratio: 16/9;
  border-radius: 8px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.slot-preview-frame.pano-frame {
  background: #0f172a;
}

.slot-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s;
}

.slot-preview-frame:hover .slot-image {
  transform: scale(1.03);
}

.slot-image.pano-img {
  object-fit: contain;
}

.slot-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: #9ca3af;
}

.slot-empty-icon {
  opacity: 0.6;
}

.slot-empty-text {
  font-size: 11px;
}

/* 左上角覆盖标签 (参考 source2 overlay label) */
.slot-overlay-badge {
  position: absolute;
  left: 8px;
  top: 8px;
  z-index: 20;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(0, 0, 0, 0.6);
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(4px);
}

.slot-overlay-badge.reverse-tag {
  background: rgba(51, 65, 85, 0.75);
}

.slot-overlay-badge.pano-tag {
  background: rgba(3, 105, 161, 0.75);
}

.slot-overlay-badge.prop-tag {
  background: rgba(180, 83, 9, 0.75);
}

/* 右上角动作栏 (参考 source2 top-right actions) */
.slot-actions-bar {
  position: absolute;
  right: 6px;
  top: 6px;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 4px;
}

.slot-icon-btn {
  background: rgba(0, 0, 0, 0.6);
  color: #ffffff;
  border: none;
  width: 22px;
  height: 22px;
  border-radius: 4px;
  display: grid;
  place-items: center;
  cursor: pointer;
  backdrop-filter: blur(4px);
  transition: all 0.2s;
}

.slot-icon-btn:hover {
  background: rgba(239, 68, 68, 0.8);
}

/* 按钮栏 (参考 source2 h-7 gap-1 rounded-[8px] px-2 text-xs) */
.slot-actions-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.slot-btn {
  height: 28px;
  border-radius: 6px;
  font-size: 12px;
  padding: 0 8px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.slot-btn.generate-btn {
  background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
  border: none;
  font-weight: 500;
}

.slot-btn.reverse-action-btn {
  background: linear-gradient(135deg, #475569 0%, #334155 100%);
}

.slot-btn.pano-action-btn {
  background: linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%);
}

.slot-btn.prop-btn {
  background: linear-gradient(135deg, #d97706 0%, #b45309 100%);
}

.slot-btn.viewer-btn {
  color: #0284c7;
  border-color: #bae6fd;
  background: #f0f9ff;
}

.slot-prompt-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 4px;
}

.slot-prompt-lbl {
  font-size: 11px;
  font-weight: 600;
  color: #4b5563;
}

/* ================== C. 道具工作区样式 (三重视角：参考图 + 三视图 + 细节特写) ================== */
.prop-workspace-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.prop-three-columns-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  align-items: flex-start;
}

@media (max-width: 1200px) {
  .prop-three-columns-grid {
    grid-template-columns: 1fr;
  }
}

.prop-slot-column {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: #fafbfc;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 12px;
}

.turnaround-tag {
  background: rgba(16, 185, 129, 0.85) !important;
  color: #fff !important;
}

.detail-tag {
  background: rgba(245, 158, 11, 0.85) !important;
  color: #fff !important;
}

.turnaround-action-btn {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
  border-color: #059669 !important;
}

.detail-action-btn {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%) !important;
  border-color: #d97706 !important;
}

.header-right-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-edit-btn {
  background: #f8fafc;
  border-color: #cbd5e1;
  color: #334155;
  font-weight: 500;
}
.header-edit-btn:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
  color: #0f172a;
}

.modal-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #0891b2;
  margin: 12px 0 10px 0;
  padding-bottom: 6px;
  border-bottom: 1px dashed #e2e8f0;
}

.create-asset-modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.create-asset-modal-footer .ant-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.scene-env-contract-preview {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
  max-height: 120px;
  overflow-y: auto;
}

.contract-text-preview {
  font-size: 12px;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
  font-family: monospace;
}

/* 360 全景查看器弹窗 */
.pano-viewer-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pano-image-container {
  width: 100%;
  height: 480px;
  border-radius: 8px;
  overflow: auto;
  background: #000000;
  border: 1px solid #334155;
  display: flex;
  align-items: center;
}

.pano-panoramic-img {
  width: 100%;
  min-width: 1200px;
  height: auto;
  object-fit: cover;
}

.pano-viewer-tips {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #64748b;
  background: #f8fafc;
  padding: 8px 12px;
  border-radius: 6px;
}

.download-link {
  color: #0284c7;
  font-weight: 500;
}
</style>
