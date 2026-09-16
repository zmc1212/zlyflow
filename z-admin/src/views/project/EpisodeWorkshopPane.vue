<template>
  <div class="workshop-container" :class="{ 'in-episode-detail': !!currentEpisodeId }">
    <!-- ==================== 层级 1: 剧集工坊概览列表 (xiaji-workshop) ==================== -->
    <div v-if="!currentEpisodeId" class="xiaji-workshop">
      <header class="xiaji-workshop-hero">
        <span class="xiaji-ingest-hero-icon" aria-hidden="true">
          <Clapperboard :size="20" />
        </span>
        <div class="hero-text-col">
          <h1>剧集工坊</h1>
          <p>把内容库规划落成剧集，生成脚本 Beat，再按镜头出草图与视频。</p>
        </div>
        <a-space>
          <a-button :loading="loading" @click="fetchEpisodes">
            <template #icon><RefreshCw :size="14" /></template>
            刷新
          </a-button>
          <a-button type="primary" class="primary-action-btn" @click="openCreateModal">
            <template #icon><Plus :size="15" /></template>
            新增分集
          </a-button>
        </a-space>
      </header>

      <!-- 统计栏 (对齐 source1) -->
      <div class="xiaji-workshop-stats">
        <span>总集数 <strong>{{ stats.total }}</strong></span>
        <span>已就绪脚本 <strong>{{ stats.ready }}</strong></span>
        <span>出场身份 <strong>{{ stats.characters }}</strong></span>
        <span>规划场景 <strong>{{ stats.scenes }}</strong></span>
        <span>关键道具 <strong>{{ stats.props }}</strong></span>
        <span>规划 Beat 分镜 <strong>{{ stats.beats }}</strong></span>
      </div>

      <!-- 列表内容区 -->
      <a-spin :spinning="loading">
        <div v-if="episodes.length === 0" class="empty-workshop-box">
          <Film :size="48" class="empty-icon" />
          <h3>暂无编排剧集</h3>
          <p>可直接在上方新增剧集，或在「内容库」导入剧本后一键同步各集分镜。</p>
          <a-button type="primary" @click="openCreateModal">新增第 1 集</a-button>
        </div>

        <div v-else class="xiaji-episode-grid">
          <div
            v-for="ep in episodes"
            :key="ep.id"
            class="xiaji-episode-card"
            @click="openEpisodeDetail(ep.id)"
          >
            <div class="card-head">
              <strong class="card-title">第 {{ ep.episode_num }} 集 · {{ ep.title }}</strong>
              <a-tag :color="getStatusColor(ep.status)">{{ getStatusText(ep.status) }}</a-tag>
            </div>
            <p class="card-summary">
              {{ ep.script_text ? ep.script_text.replace(/[#\n-]/g, ' ').slice(0, 85) + '...' : '暂未编排镜头对白内容' }}
            </p>
            <div class="card-footer">
              <em class="card-meta">
                {{ ep.shots_count || 0 }} 个分镜 · {{ getEpisodeCharCount(ep) }} 身份 · {{ getEpisodeSceneCount(ep) }} 场景
              </em>
              <div class="card-actions" @click.stop>
                <a-button type="link" size="small" @click="openEditModal(ep)">
                  修改分集
                </a-button>
                <a-popconfirm
                  title="确定删除此集？"
                  ok-text="删除"
                  cancel-text="取消"
                  ok-type="danger"
                  @confirm="handleDeleteEpisode(ep.id)"
                >
                  <a-button type="link" danger size="small">删除</a-button>
                </a-popconfirm>
              </div>
            </div>
          </div>
        </div>
      </a-spin>
    </div>

    <!-- ==================== 层级 2: 分集详细工作区 (完全对齐 source1 EpisodeWorkspace) ==================== -->
    <div v-else-if="currentEpisode" class="xiaji-episode">
      <!-- 顶部 Header 导航条 -->
      <header class="xiaji-episode-head">
        <div class="xiaji-episode-head-main">
          <div class="xiaji-episode-head-title">
            <a-button class="back-btn" @click="handleBackToOverview">
              <template #icon><ArrowLeft :size="14" /></template>
              返回概览
            </a-button>
            <h2>第 {{ currentEpisode.number }} 集 {{ currentEpisode.title }}</h2>
            <a-tag :color="getStatusColor(currentEpisode.status)">{{ getStatusText(currentEpisode.status) }}</a-tag>
          </div>
          <p class="episode-meta-line">
            {{ currentEpisode.line_count || (currentEpisode.beats?.length || 0) * 4 }} 行原文 ·
            {{ currentEpisode.beats?.length || 0 }} 个 Beat 分镜 ·
            {{ currentEpisode.character_count || 0 }} 个身份 ·
            {{ currentEpisode.scene_count || 0 }} 个场景 ·
            {{ currentEpisode.prop_count || 0 }} 个道具
          </p>
        </div>

        <a-space class="xiaji-episode-head-actions" :size="8">
          <div class="head-param-item">
            <span class="head-param-lbl">镜头画质</span>
            <a-select v-model:value="globalVideoQuality" size="small" style="width: 148px">
              <a-select-option value="0.4">0.4 MP (标清 480P)</a-select-option>
              <a-select-option value="0.7">0.7 MP (高清 720P)</a-select-option>
              <a-select-option value="1.0">1.0 MP (超清 768P)</a-select-option>
              <a-select-option value="2.0">2.0 MP (全高清 1080P)</a-select-option>
            </a-select>
          </div>
          <div class="head-param-item">
            <span class="head-param-lbl">镜头时长</span>
            <a-select v-model:value="globalVideoDuration" size="small" style="width: 115px">
              <a-select-option :value="5">5 秒 (124帧)</a-select-option>
              <a-select-option :value="8">8 秒 (192帧)</a-select-option>
              <a-select-option :value="10">10 秒 (243帧)</a-select-option>
              <a-select-option :value="15">15 秒 (362帧)</a-select-option>
            </a-select>
          </div>
          <a-button :loading="generatingEpisodeVideo" @click="handleGenerateEpisodeVideo">
            <template #icon><Video :size="14" /></template>
            一键生成视频
          </a-button>
          <a-button :loading="refreshingDetail" @click="refreshCurrentEpisode">
            <template #icon><RefreshCw :size="14" /></template>
            刷新数据
          </a-button>
          <a-button type="primary" :loading="regeneratingScript" @click="handleRegenerateScript">
            <template #icon><Sparkles :size="14" /></template>
            重新生成脚本
          </a-button>
        </a-space>
      </header>

      <!-- 三大核心 Tab: 镜头 (Shots) | 剧本 (Script) | 合成 (Compose) -->
      <a-tabs v-model:activeKey="currentTab" class="episode-tabs">
        <!-- ==================== Tab 1: 🎬 镜头工作台 (XiajiShotsWorkbench) ==================== -->
        <a-tab-pane key="shots" tab="🎬 镜头">
          <div class="xiaji-shots-workbench">
            <!-- 镜头工具条 -->
            <div class="xiaji-shots-toolbar">
              <div class="toolbar-left">
                <a-checkbox v-model:checked="showSketch">显示草图</a-checkbox>
                <span class="sketched-count-label">
                  {{ sketchedCount }}/{{ currentEpisode.beats?.length || 0 }} 张草图 ·
                  {{ renderedCount }}/{{ currentEpisode.beats?.length || 0 }} 张渲染图
                </span>
              </div>
              <div class="toolbar-right">
                <a-button
                  size="small"
                  :loading="batchGeneratingRequiredAssets"
                  @click="enqueueRequiredAssets"
                >
                  <template #icon><Boxes :size="13" /></template>
                  生成所有所需资源
                </a-button>
                <a-button
                  type="primary"
                  size="small"
                  :loading="batchGenerating"
                  @click="enqueueBatch('sketch')"
                >
                  <template #icon><Sparkles :size="13" /></template>
                  批量生成分镜草图
                </a-button>
                <a-button
                  type="primary"
                  size="small"
                  :loading="batchGeneratingRenders"
                  @click="enqueueBatch('render')"
                >
                  <template #icon><Sparkles :size="13" /></template>
                  批量生成渲染图
                </a-button>
              </div>
            </div>

            <!-- 分栏布局：左侧缩略图卡片网格 + 右侧检视器 -->
            <div ref="splitRef" class="xiaji-shots-split">
              <!-- 左侧分镜卡片栅格 (BeatGrid) -->
              <div class="xiaji-shots-grid-pane" :style="{ width: splitPct + '%' }">
                <div class="xiaji-shot-tiles">
                  <button
                    v-for="beat in currentEpisode.beats"
                    :key="beat.id"
                    type="button"
                    :class="['xiaji-shot-tile', { 'is-selected': selectedBeat?.id === beat.id }]"
                    @click="selectBeat(beat)"
                  >
                    <span class="xiaji-shot-tile-num">Beat {{ beat.sequence }}</span>
                    <div class="xiaji-shot-tile-media">
                      <img
                        v-if="showSketch && beat.sketch_url"
                        :src="beat.sketch_url"
                        :alt="`Beat ${beat.sequence}`"
                      />
                      <div v-else-if="generatingBeatIds.has(beat.id) || generatingRenderBeatIds.has(beat.id)" class="xiaji-shot-tile-busy">
                        <a-spin size="small" />
                        <em>{{ generationStatusText(beat.id, generatingBeatIds.has(beat.id) ? 'sketch' : 'render') || 'GRS 生成中' }}</em>
                      </div>
                      <div v-else class="shot-tile-empty">
                        <ImageIcon :size="24" />
                      </div>
                    </div>
                    <p class="tile-caption" :title="beat.action || beat.dialogue || beat.heading">
                      {{ beat.dialogue ? `「${beat.speaker || '对白'}」${beat.dialogue}` : (beat.action || beat.heading || '未填写画面描述') }}
                    </p>
                  </button>
                </div>
              </div>

              <!-- 分栏手柄 (Gutter) -->
              <div
                class="xiaji-shots-gutter"
                @mousedown="startDragging"
              />

              <!-- 右侧分镜检视器 (Inspector) -->
              <div class="xiaji-shots-detail" :style="{ width: (100 - splitPct) + '%' }">
                <div v-if="selectedBeat" class="xiaji-shot-pane-container">
                  <!-- 顶部 Header 状态栏 -->
                  <div class="xiaji-shot-pane-topbar">
                    <span class="topbar-title">
                      Beat {{ selectedBeat.sequence }} 镜头检视
                    </span>
                    <a-space size="small">
                      <button type="button" class="xiaji-pane-btn" @click="saveCurrentBeat">
                        <Check :size="12" />
                        <span>保存设定</span>
                      </button>
                      <button type="button" class="xiaji-pane-btn" @click="refreshCurrentEpisode">
                        <RefreshCw :size="12" />
                        <span>重建索引</span>
                      </button>
                    </a-space>
                  </div>

                  <!-- 检视器纵向滚动内容 -->
                  <div class="xiaji-pane-scroll-area">
                    <!-- 1. 文案 Section -->
                    <div class="xiaji-pane-section">
                      <div class="xiaji-pane-section-header" @click="toggleSection('text')">
                        <div class="section-title-wrap">
                          <ChevronDown
                            :size="14"
                            :class="['arrow-icon', { 'is-collapsed': !openSections.text }]"
                          />
                          <FileText :size="15" />
                          <span class="section-title">文案与分镜台词</span>
                        </div>
                        <span class="status-chip is-active">
                          <span class="chip-dot" /> 已同步
                        </span>
                      </div>

                      <div v-show="openSections.text" class="xiaji-pane-section-body">
                        <div class="xiaji-shot-form">
                          <!-- 对白台词 -->
                          <div class="form-group">
                            <label class="form-label">台词对白 (Dialogue)</label>
                            <a-textarea
                              v-model:value="selectedBeat.dialogue"
                              :rows="3"
                              placeholder="输入对白台词..."
                              @blur="saveCurrentBeat"
                            />
                          </div>

                          <!-- 说话人 + 景别机位 -->
                          <div class="form-row-two">
                            <div class="form-group">
                              <label class="form-label">说话人 (Speaker)</label>
                              <a-select
                                v-model:value="selectedBeat.speaker"
                                allow-clear
                                placeholder="选择说话人"
                                :options="characterOptions"
                                @change="saveCurrentBeat"
                              />
                            </div>
                            <div class="form-group">
                              <label class="form-label">景别机位 (Camera)</label>
                              <a-select
                                v-model:value="selectedBeat.camera"
                                placeholder="选择景别机位"
                                :options="cameraOptions"
                                @change="saveCurrentBeat"
                              />
                            </div>
                          </div>

                          <!-- 场景环境 + 时间氛围 -->
                          <div class="form-row-two">
                            <div class="form-group">
                              <label class="form-label">场景环境 (Scene)</label>
                              <a-select
                                v-model:value="selectedBeat.scene_id"
                                allow-clear
                                placeholder="选择关联场景"
                                :options="sceneOptions"
                                @change="onSceneSelectChange"
                              />
                            </div>
                            <div class="form-group">
                              <label class="form-label">时间氛围 (Time)</label>
                              <a-select
                                v-model:value="selectedBeat.time_of_day"
                                allow-clear
                                placeholder="日 / 夜 / 晨 / 昏"
                                :options="timeOptions"
                                @change="saveCurrentBeat"
                              />
                            </div>
                          </div>

                          <!-- 场景说明 Heading -->
                          <div class="form-group">
                            <label class="form-label">场景与镜头标题 (Heading)</label>
                            <a-input
                              v-model:value="selectedBeat.heading"
                              placeholder="如：现代大学图书馆夜景 · 中景"
                              @blur="saveCurrentBeat"
                            />
                          </div>

                          <!-- 画面动作描述 Action -->
                          <div class="form-group">
                            <label class="form-label">画面动作与视觉描述 (Action)</label>
                            <a-textarea
                              v-model:value="selectedBeat.action"
                              :rows="4"
                              placeholder="描述画面中角色动作、神态与空间视觉细节..."
                              @blur="saveCurrentBeat"
                            />
                          </div>

                          <!-- 出场身份 Chips -->
                          <div class="form-group">
                            <label class="form-label">出场身份 (Characters)</label>
                            <div class="chips-flex-row">
                              <button
                                v-for="c in projectCharacters"
                                :key="c.id"
                                type="button"
                                :class="['xiaji-ref-chip', { 'is-on': selectedBeat.character_ids?.includes(c.id) }]"
                                @click="toggleBeatCharacter(c.id)"
                              >
                                <img v-if="c.image_url" :src="c.image_url" alt="" />
                                <span v-else class="chip-avatar-fallback">{{ c.name.slice(0, 1) }}</span>
                                {{ c.name }}
                              </button>
                              <span v-if="!projectCharacters.length" class="empty-hint">资产库暂无角色</span>
                            </div>
                          </div>

                          <div class="form-group">
                            <label class="form-label">出场角色服饰造型 (Pictures)</label>
                            <div v-if="selectedBeatCharacters.length" class="character-look-list">
                              <div v-for="(character, index) in selectedBeatCharacters" :key="character.id" class="character-look-row">
                                <div class="character-look-heading">
                                  <img v-if="character.image_url" :src="character.image_url" alt="" />
                                  <span v-else class="chip-avatar-fallback">{{ character.name.slice(0, 1) }}</span>
                                  <strong>{{ character.name }}</strong>
                                  <span>Picture {{ index + 1 }}</span>
                                </div>
                                <a-select
                                  :value="getBeatCharacterLookId(character) || undefined"
                                  allow-clear
                                  show-search
                                  option-filter-prop="label"
                                  style="width: 100%"
                                  placeholder="选择该角色在当前镜头的服饰造型"
                                  @change="value => onCharacterLookChange(character.id, value)"
                                >
                                  <a-select-option
                                    v-for="look in getCharacterLookOptions(character)"
                                    :key="look.value"
                                    :value="look.value"
                                    :label="look.label"
                                  >
                                    <span class="look-option">
                                      <img v-if="look.imageUrl" :src="look.imageUrl" alt="" />
                                      <span>{{ look.label }}</span>
                                    </span>
                                  </a-select-option>
                                </a-select>
                                <div v-if="getSelectedCharacterLook(character)" class="selected-look-preview">
                                  <img :src="getSelectedCharacterLook(character).imageUrl" :alt="`${character.name}当前服饰造型`" />
                                  <div>
                                    <strong>{{ getSelectedCharacterLook(character).label }}</strong>
                                    <p>{{ getSelectedCharacterLook(character).description || '已选择为该角色当前镜头的造型参考图' }}</p>
                                  </div>
                                </div>
                                <p v-else-if="!getCharacterLookOptions(character).length" class="look-empty-hint">
                                  该角色还没有可用服饰造型，请先到资产库生成造型图。
                                </p>
                              </div>
                            </div>
                            <p v-else class="look-empty-hint">请先在“出场身份”中选择角色。</p>
                          </div>

                          <!-- 出场道具 Chips -->
                          <div class="form-group">
                            <label class="form-label">出场道具 (Props)</label>
                            <div class="chips-flex-row">
                              <button
                                v-for="p in projectProps"
                                :key="p.id"
                                type="button"
                                :class="['xiaji-ref-chip', { 'is-on': selectedBeat.prop_ids?.includes(p.id) }]"
                                @click="toggleBeatProp(p.id)"
                              >
                                <img v-if="p.image_url" :src="p.image_url" alt="" />
                                <span v-else class="chip-avatar-fallback">{{ p.name.slice(0, 1) }}</span>
                                {{ p.name }}
                              </button>
                              <span v-if="!projectProps.length" class="empty-hint">资产库暂无道具</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- 2. 草图 Section (Sketch) -->
                    <div v-show="false" class="xiaji-pane-section">
                      <div class="xiaji-pane-section-header" @click="toggleSection('sketch')">
                        <div class="section-title-wrap">
                          <ChevronDown
                            :size="14"
                            :class="['arrow-icon', { 'is-collapsed': !openSections.sketch }]"
                          />
                          <Pencil :size="15" />
                          <span class="section-title">分镜草图 (Sketch 2:3)</span>
                        </div>
                        <span :class="['status-chip', selectedBeat.sketch_url ? 'is-active' : 'is-idle']">
                          <span class="chip-dot" /> {{ selectedBeat.sketch_url ? '草图已就绪' : '待出图' }}
                        </span>
                      </div>

                      <div v-show="openSections.sketch" class="xiaji-pane-section-body">
                        <div class="sketch-block">
                          <!-- 绑定的角色/身份 Pill -->
                          <div class="sketch-actor-row">
                            <span
                              v-for="cid in selectedBeat.character_ids"
                              :key="cid"
                              class="sketch-actor-pill"
                            >
                              <span class="dot" />
                              <span>{{ getCharName(cid) }}</span>
                            </span>
                            <span v-if="!selectedBeat.character_ids?.length" class="sketch-actor-pill is-none">
                              <span class="dot" />
                              <span>{{ selectedBeat.speaker || '未指定主角色' }}</span>
                            </span>
                          </div>

                          <!-- 主草图大卡片 + 版本缩略图 -->
                          <div class="sketch-cards-row">
                            <div class="sketch-main-card">
                              <a-image
                                v-if="selectedBeat.sketch_url"
                                :src="selectedBeat.sketch_url"
                                class="main-preview-img"
                              />
                              <div
                                v-else-if="generatingBeatIds.has(selectedBeat.id)"
                                class="sketch-placeholder is-busy"
                              >
                                <a-spin />
                                <span>{{ generationStatusText(selectedBeat.id, 'sketch') || 'GRS 正在生成' }}</span>
                              </div>
                              <div
                                v-else
                                class="sketch-placeholder"
                                @click="enqueueSingleSketch"
                              >
                                <ImageIcon :size="32" />
                                <span>点此使用 GRS (gpt-image-2) 生成草图</span>
                              </div>
                            </div>

                            <!-- 右侧缩略卡片 -->
                            <div class="sketch-thumb-card">
                              <img
                                v-if="selectedBeat.sketch_url"
                                :src="selectedBeat.sketch_url"
                                alt=""
                              />
                              <div v-else class="thumb-empty" />
                              <span class="version-badge">2:3 1K</span>
                            </div>
                          </div>

                          <!-- 8 个专业工具操作按钮条 (对齐 source1) -->
                          <div class="sketch-bottom-toolbar">
                            <button
                              type="button"
                              class="tool-btn is-primary"
                              :disabled="generatingBeatIds.has(selectedBeat.id)"
                              @click="enqueueSingleSketch"
                            >
                              <RefreshCw :size="12" :class="{ 'animate-spin': generatingBeatIds.has(selectedBeat.id) }" />
                              <span>{{ generatingBeatIds.has(selectedBeat.id) ? '生成中' : (selectedBeat.sketch_url ? '重新生成草图' : '✨ 生成草图') }}</span>
                            </button>

                            <button type="button" class="tool-btn" @click="handleToolNotice('姿势骨骼编辑')">
                              <Users :size="12" />
                              <span>姿势编辑</span>
                            </button>

                            <button type="button" class="tool-btn" @click="handleToolNotice('画幅智能裁剪')">
                              <Crop :size="12" />
                              <span>裁剪保存</span>
                            </button>

                            <button type="button" class="tool-btn" @click="toggleSceneBackground">
                              <LucideImage :size="12" />
                              <span>{{ currentSceneView === 'front' ? '场景正面' : '场景背面' }}</span>
                            </button>

                            <a
                              :href="selectedBeat.sketch_url || undefined"
                              target="_blank"
                              download
                              :class="['tool-btn', { 'is-disabled': !selectedBeat.sketch_url }]"
                            >
                              <Download :size="12" />
                              <span>下载原图</span>
                            </a>

                            <a-upload
                              accept="image/*"
                              :show-upload-list="false"
                              :before-upload="handleUploadSketch"
                            >
                              <button type="button" class="tool-btn">
                                <UploadIcon :size="12" />
                                <span>上传替换</span>
                              </button>
                            </a-upload>

                            <button type="button" class="tool-btn" @click="handleToolNotice('导演世界资产同步')">
                              <Box :size="12" />
                              <span>导演世界</span>
                            </button>

                            <button type="button" class="tool-btn" @click="handleToolNotice('画板深度精绘')">
                              <ExternalLink :size="12" />
                              <span>虾画编辑</span>
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- 3. 渲染精绘 Section (Render) -->
                    <div v-show="false" class="xiaji-pane-section">
                      <div class="xiaji-pane-section-header" @click="toggleSection('render')">
                        <div class="section-title-wrap">
                          <ChevronDown
                            :size="14"
                            :class="['arrow-icon', { 'is-collapsed': !openSections.render }]"
                          />
                          <LucideImage :size="15" />
                          <span class="section-title">高精渲染图 (Render 2:3)</span>
                        </div>
                        <div class="section-header-actions" @click.stop>
                          <a-button
                            type="primary"
                            size="small"
                            :loading="generatingRenderBeatIds.has(selectedBeat.id)"
                            @click="enqueueSingleRender"
                          >
                            {{
                              generatingRenderBeatIds.has(selectedBeat.id)
                                ? '生成中'
                                : selectedBeat.render_url
                                  ? '重新生成渲染图'
                                  : '✨ 生成渲染图'
                            }}
                          </a-button>
                          <span :class="['status-chip', selectedBeat.render_url ? 'is-active' : 'is-idle']">
                            <span class="chip-dot" /> {{ selectedBeat.render_url ? '已渲染' : '待渲染' }}
                          </span>
                        </div>
                      </div>

                      <div v-show="openSections.render" class="xiaji-pane-section-body">
                        <div class="sketch-block">
                          
                          <!-- 绑定的角色/身份 Pill -->
                          <div class="sketch-actor-row">
                            <span
                              v-for="cid in selectedBeat.character_ids"
                              :key="cid"
                              class="sketch-actor-pill"
                            >
                              <span class="dot" />
                              <span>{{ getCharName(cid) }}</span>
                            </span>
                            <span v-if="!selectedBeat.character_ids?.length" class="sketch-actor-pill is-none">
                              <span class="dot" />
                              <span>{{ selectedBeat.speaker || '未指定主角色' }}</span>
                            </span>
                          </div>

                          <div class="sketch-cards-row">
                            <div class="sketch-main-card">
                              <a-image
                                v-if="selectedBeat.render_url"
                                :src="selectedBeat.render_url"
                                class="main-preview-img"
                              />
                              <div
                                v-else-if="generatingRenderBeatIds.has(selectedBeat.id)"
                                class="sketch-placeholder is-busy"
                              >
                                <a-spin />
                                <span>{{ generationStatusText(selectedBeat.id, 'render') || 'GRS 正在按草图精绘渲染图' }}</span>
                              </div>
                              <div v-else class="sketch-placeholder" @click="enqueueSingleRender">
                                <LucideImage :size="32" />
                                <span>点此使用 GRS 生成渲染图</span>
                              </div>
                            </div>
                            <div class="sketch-thumb-card">
                              <img v-if="selectedBeat.render_url" :src="selectedBeat.render_url" alt="" />
                              <div v-else class="thumb-empty" />
                              <span class="version-badge">2:3 1K</span>
                            </div>
                          </div>

                          <div class="sketch-bottom-toolbar">
                            <button
                              type="button"
                              class="tool-btn is-primary"
                              :disabled="generatingRenderBeatIds.has(selectedBeat.id)"
                              @click="enqueueSingleRender"
                            >
                              <Sparkles :size="12" :class="{ 'animate-spin': generatingRenderBeatIds.has(selectedBeat.id) }" />
                              <span>{{ generatingRenderBeatIds.has(selectedBeat.id) ? '生成中' : (selectedBeat.render_url ? '重新生成渲染图' : '✨ 生成渲染图') }}</span>
                            </button>
                            <button type="button" class="tool-btn" @click="handleToolNotice('画质增强')">
                              <Sparkles :size="12" />
                              <span>画质增强</span>
                            </button>
                            <button type="button" class="tool-btn" @click="handleToolNotice('画幅智能裁剪')">
                              <Crop :size="12" />
                              <span>裁剪保存</span>
                            </button>
                            <button type="button" class="tool-btn" @click="toggleSceneBackground">
                              <LucideImage :size="12" />
                              <span>背景对齐</span>
                            </button>
                            <a
                              :href="selectedBeat.render_url || undefined"
                              target="_blank"
                              download
                              :class="['tool-btn', { 'is-disabled': !selectedBeat.render_url }]"
                            >
                              <Download :size="12" />
                              <span>下载</span>
                            </a>
                            <a-upload
                              accept="image/*"
                              :show-upload-list="false"
                              :before-upload="handleUploadRender"
                            >
                              <button type="button" class="tool-btn">
                                <UploadIcon :size="12" />
                                <span>上传精绘</span>
                              </button>
                            </a-upload>
                            <button type="button" class="tool-btn" @click="handleToolNotice('导演世界资产同步')">
                              <Box :size="12" />
                              <span>导演世界</span>
                            </button>
                            <button type="button" class="tool-btn" @click="handleToolNotice('虾画精修')">
                              <ExternalLink :size="12" />
                              <span>虾画精修</span>
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- 4. 视频 Section (Video & LightX2V) -->
                    <div v-show="false" class="xiaji-pane-section">
                      <div class="xiaji-pane-section-header" @click="toggleSection('video')">
                        <div class="section-title-wrap">
                          <ChevronDown
                            :size="14"
                            :class="['arrow-icon', { 'is-collapsed': !openSections.video }]"
                          />
                          <Video :size="15" />
                          <span class="section-title">分镜动态视频 (Video)</span>
                        </div>
                        <span class="status-chip is-idle">
                          <span class="chip-dot" /> {{ selectedBeat.video_url ? '已生成' : '未生成' }}
                        </span>
                      </div>

                      <div v-show="openSections.video" class="xiaji-pane-section-body">
                        <div class="video-settings-block">
                          <div class="video-toolbar-row">
                            <div class="param-item">
                              <span class="param-lbl">工作流</span>
                              <a-select v-model:value="videoWorkflow" size="small" style="width: 170px">
                                <a-select-option value="lightx2v">LightX2V 多参考视频</a-select-option>
                                <a-select-option value="comfy_svd">SVD 首帧生成</a-select-option>
                              </a-select>
                            </div>
                            <div class="param-item">
                              <span class="param-lbl">时长</span>
                              <a-select v-model:value="selectedBeat.video_duration" size="small" style="width: 75px">
                                <a-select-option value="3">3 秒</a-select-option>
                                <a-select-option value="5">5 秒</a-select-option>
                                <a-select-option value="8">8 秒</a-select-option>
                              </a-select>
                            </div>
                            <div class="param-item">
                              <span class="param-lbl">画质</span>
                              <a-select v-model:value="videoQuality" size="small" style="width: 80px">
                                <a-select-option value="0.2">0.2 MP</a-select-option>
                                <a-select-option value="0.5">0.5 MP</a-select-option>
                              </a-select>
                            </div>
                            <div class="param-item">
                              <span class="param-lbl">部署步数</span>
                              <a-select v-model:value="videoSpeed" size="small" style="width: 110px">
                                <a-select-option value="balanced">均衡 (8 步)</a-select-option>
                                <a-select-option value="fast">极速 (4 步)</a-select-option>
                              </a-select>
                            </div>
                          </div>

                          <div class="form-group mt-3">
                            <div class="prompt-head-row">
                              <label class="form-label">本 Beat 视频运镜与运体提示词</label>
                              <a-button type="link" size="small" @click="generateVideoPrompt">
                                <template #icon><Sparkles :size="12" /></template>
                                自动提取生成
                              </a-button>
                            </div>
                            <a-textarea
                              v-model:value="selectedBeat.video_prompt_zh"
                              :rows="4"
                              placeholder="描述摄像机推拉摇移、主体人物的面部微表情与动作演进..."
                              @blur="saveCurrentBeat"
                            />
                          </div>

                          <!-- 视频预览/播放卡片 -->
                          <div class="video-preview-stage mt-3">
                            <div class="video-main-card">
                              <video
                                v-if="selectedBeat.video_url"
                                :src="selectedBeat.video_url"
                                controls
                                playsinline
                                class="video-player-element"
                              />
                              <div v-else-if="generatingVideo" class="video-placeholder is-busy">
                                <a-spin />
                                <span>LightX2V 正在生成视频中...</span>
                              </div>
                              <div v-else-if="selectedBeat.render_url || selectedBeat.sketch_url" class="video-preview-cover">
                                <img :src="selectedBeat.render_url || selectedBeat.sketch_url" alt="" />
                                <div class="cover-overlay">
                                  <Video :size="24" />
                                  <span>基于分镜图首帧驱动生成</span>
                                </div>
                              </div>
                              <div v-else class="video-placeholder">
                                <Video :size="32" />
                                <span>请先生成草图或渲染图，再生成动态视频</span>
                              </div>
                            </div>
                          </div>

                          <!-- 底部视频工具条与生成按钮 -->
                          <div class="sketch-bottom-toolbar mt-3">
                            <button
                              type="button"
                              class="tool-btn is-primary"
                              :disabled="generatingVideo || (!selectedBeat.sketch_url && !selectedBeat.render_url)"
                              @click="handleGenerateVideo"
                            >
                              <Video :size="12" :class="{ 'animate-spin': generatingVideo }" />
                              <span>{{ generatingVideo ? '生成中...' : (selectedBeat.video_url ? '重新生成视频' : '生成分镜视频 (LightX2V)') }}</span>
                            </button>

                            <button type="button" class="tool-btn" @click="handleToolNotice('运镜微调')">
                              <Sparkles :size="12" />
                              <span>镜头微调</span>
                            </button>

                            <a
                              :href="selectedBeat.video_url || undefined"
                              target="_blank"
                              download
                              :class="['tool-btn', { 'is-disabled': !selectedBeat.video_url }]"
                            >
                              <Download :size="12" />
                              <span>下载视频</span>
                            </a>

                            <button type="button" class="tool-btn" @click="handleToolNotice('导演世界时间轴')">
                              <Box :size="12" />
                              <span>导演世界</span>
                            </button>

                            <button type="button" class="tool-btn" @click="handleToolNotice('全屏监视器')">
                              <ExternalLink :size="12" />
                              <span>全屏监视</span>
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- 5. 素材组 Section (H3 Material Group) -->
                    <div class="xiaji-pane-section h3-material-section">
                      <div class="xiaji-pane-section-header" @click="toggleSection('material')">
                        <div class="section-title-wrap">
                          <ChevronDown
                            :size="14"
                            :class="['arrow-icon', { 'is-collapsed': !openSections.material }]"
                          />
                          <Layers :size="15" />
                          <span class="section-title">素材组</span>
                        </div>
                        <div class="section-header-actions" @click.stop>
                          <a-button
                            type="primary"
                            size="small"
                            :loading="generatingH3Prompt"
                            @click="handleGenerateH3Prompt"
                          >
                            <template #icon><Sparkles :size="12" /></template>
                            {{ generatingH3Prompt ? '生成中' : '生成 H3 提示词' }}
                          </a-button>
                          <span :class="['status-chip', selectedBeat.h3_prompt ? 'is-active' : 'is-idle']">
                            <span class="chip-dot" /> {{ selectedBeat.h3_prompt ? '已生成' : '未生成' }}
                          </span>
                        </div>
                      </div>

                      <div v-show="openSections.material" class="xiaji-pane-section-body">
                        <!-- 主内容：左侧参考图片 + 右侧提示词 -->
                        <div class="h3-material-content">
                          <!-- 左侧：参考图片 -->
                          <div class="h3-material-left">
                            <div class="h3-ref-block">
                              <div class="h3-ref-block-head">
                                <span class="h3-ref-label">参考图片</span>
                                <a-button size="small" @click="handleSelectExistingImages">
                                  选已有 {{ h3RefImages.length }}/9
                                </a-button>
                              </div>
                              <div class="h3-ref-grid">
                                <div
                                  v-for="(img, idx) in h3RefImagesVisible"
                                  :key="img.id || idx"
                                  class="h3-ref-img-cell"
                                >
                                  <img v-if="img.url" :src="img.url" :alt="`图片${idx + 1}`" />
                                  <div v-else class="h3-ref-img-empty">
                                    <ImageIcon :size="18" />
                                    <span>图片{{ idx + 1 }}</span>
                                  </div>
                                  <div class="h3-ref-info">
                                    <span class="h3-ref-seq">图片{{ idx + 1 }}</span>
                                    <span v-if="img.name" class="h3-ref-name" :title="img.name">
                                      <i v-if="img.category === 'prop'" class="h3-ref-cat-dot is-prop" title="道具" />
                                      <i v-else-if="img.category === 'scene'" class="h3-ref-cat-dot is-scene" title="场景" />
                                      <i v-else class="h3-ref-cat-dot is-char" title="角色" />
                                      {{ img.name }}
                                    </span>
                                  </div>
                                  <button
                                    type="button"
                                    class="h3-ref-del-btn"
                                    title="移除此参考图"
                                    @click.stop="removeH3RefImage(idx)"
                                  >
                                    ×
                                  </button>
                                </div>
                                <a-upload
                                  :show-upload-list="false"
                                  accept="image/*"
                                  :before-upload="f => handleUploadH3Image(f)"
                                >
                                  <div class="h3-ref-add-btn">
                                    <Plus :size="16" />
                                  </div>
                                </a-upload>
                              </div>
                              <div v-if="h3RefImages.length > 3" class="h3-ref-expand" @click="h3ImagesExpanded = !h3ImagesExpanded">
                                {{ h3ImagesExpanded ? '收起' : `展开更多 (+${h3RefImages.length - 3})` }}
                              </div>
                            </div>
                          </div>

                          <!-- 右侧：H3 提示词展示 -->
                          <div class="h3-prompt-panel">
                            <div class="h3-prompt-head">
                              <span class="h3-prompt-title">提示词</span>
                              <a-button
                                v-if="selectedBeat.h3_prompt"
                                type="link"
                                size="small"
                                @click="copyH3Prompt"
                              >
                                <template #icon><Copy :size="12" /></template>
                                复制
                              </a-button>
                            </div>
                            <div v-if="selectedBeat.h3_prompt" ref="promptDisplayRef" class="h3-prompt-display" v-html="renderH3Prompt(selectedBeat.h3_prompt)" />
                            <div v-else-if="generatingH3Prompt" class="h3-prompt-loading">
                              <a-spin size="small" />
                              <span>正在生成 H3 提示词...</span>
                            </div>
                            <div v-else class="h3-prompt-empty">
                              <span>尚未生成 H3 提示词</span>
                              <p>点击「生成 H3 提示词」，按技能规则调用大模型生成。</p>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                  </div>
                </div>
              </div>
            </div>
          </div>
        </a-tab-pane>

        <!-- ==================== Tab 2: 📝 原文剧本 (ScriptPane) ==================== -->
        <a-tab-pane key="script" tab="📝 剧本">
          <div class="xiaji-script-grid">
            <!-- 左侧：出场资产规划 + 原文 -->
            <div class="xiaji-script-col">
              <section class="script-section-box">
                <header class="section-head">
                  <Users :size="15" />
                  <h3>资产规划</h3>
                  <em>{{ currentEpisode.links?.filter(l => l.kind === 'character').length || 0 }} 个身份</em>
                </header>
                <ul class="xiaji-workshop-assets">
                  <li
                    v-for="c in projectCharacters"
                    :key="c.id"
                  >
                    <img v-if="c.image_url" :src="c.image_url" alt="" />
                    <span v-else class="xiaji-workshop-asset-fallback">{{ c.name.slice(0, 1) }}</span>
                    <div class="asset-info">
                      <strong>{{ c.name }}</strong>
                      <em>{{ c.role || '主要人物' }}</em>
                    </div>
                  </li>
                </ul>
              </section>

              <section class="script-section-box">
                <header class="section-head">
                  <FileText :size="15" />
                  <h3>原文剧本</h3>
                  <em>共 {{ currentEpisode.original_lines?.length || 0 }} 行</em>
                </header>
                <ol class="xiaji-original-lines">
                  <li
                    v-for="(line, idx) in currentEpisode.original_lines"
                    :key="idx"
                  >
                    <span class="line-no">{{ idx + 1 }}.</span>
                    <p class="line-content">{{ line }}</p>
                  </li>
                </ol>
              </section>
            </div>

            <!-- 右侧：脚本预览列表 (BeatCards) -->
            <div class="xiaji-script-col">
              <section class="script-section-box">
                <header class="section-head">
                  <Clapperboard :size="15" />
                  <h3>编排脚本预览</h3>
                  <em>{{ currentEpisode.beats?.length || 0 }} 个 Beat</em>
                </header>
                <div class="xiaji-beat-list">
                  <div
                    v-for="beat in currentEpisode.beats"
                    :key="beat.id"
                    class="xiaji-beat"
                  >
                    <span class="beat-header">Beat {{ beat.sequence }} · {{ beat.heading || '分镜' }}</span>
                    <p v-if="beat.dialogue" class="beat-dialogue">
                      <strong>{{ beat.speaker || '角色' }}</strong>：{{ beat.dialogue }}
                    </p>
                    <p v-if="beat.action" class="beat-action">
                      <span class="lbl">画面：</span>{{ beat.action }}
                    </p>
                  </div>
                </div>
              </section>
            </div>
          </div>
        </a-tab-pane>

        <!-- ==================== Tab 3: 🎞️ 成片合成 (ComposePane) ==================== -->
        <a-tab-pane key="compose" tab="🎞️ 合成">
          <div class="xiaji-compose-pane">
            <div class="compose-summary-card">
              <Clapperboard :size="32" class="text-purple" />
              <div class="summary-info">
                <h3>第 {{ currentEpisode.number }} 集成片合成流水线</h3>
                <p>
                  已完成镜头：{{ sketchedCount }}/{{ currentEpisode.beats?.length || 0 }} ·
                  音频通道：就绪 ·
                  字幕 SRT：自动同步
                </p>
              </div>
              <a-space>
                <a-button type="primary" @click="handleToolNotice('全片自动渲染与剪辑合成')">
                  <template #icon><Sparkles :size="14" /></template>
                  一键合成全集成片
                </a-button>
                <a-button @click="handleToolNotice('字幕导出')">
                  导出字幕 SRT
                </a-button>
              </a-space>
            </div>

            <!-- 分镜时间线片段序列 -->
            <div class="timeline-preview-section mt-4">
              <h4>分镜轨道时间线预览 (Timeline Track)</h4>
              <div class="timeline-tiles-scroll">
                <div
                  v-for="b in currentEpisode.beats"
                  :key="b.id"
                  class="timeline-shot-card"
                >
                  <div class="shot-thumb">
                    <img v-if="b.sketch_url" :src="b.sketch_url" alt="" />
                    <div v-else class="placeholder-thumb">Shot {{ b.sequence }}</div>
                  </div>
                  <div class="shot-title">Shot {{ b.sequence }} ({{ b.video_duration || 5 }}s)</div>
                </div>
              </div>
            </div>
          </div>
        </a-tab-pane>
      </a-tabs>
    </div>

    <!-- 加载中占位 -->
    <div v-else-if="currentEpisodeId && !currentEpisode" class="workshop-loading-box">
      <a-spin size="large" />
      <span class="loading-text">正在加载剧集分镜数据...</span>
    </div>

    <!-- ==================== 新建/编辑分集弹窗 ==================== -->
    <a-modal
      v-model:open="modalVisible"
      :title="isEdit ? '编辑分集信息' : '新增剧集'"
      :confirm-loading="submitting"
      ok-text="确认保存"
      cancel-text="取消"
      :width="600"
      destroy-on-close
      @ok="handleSubmit"
    >
      <a-form layout="vertical">
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="集数序号" required>
              <a-input-number v-model:value="form.episode_num" :min="1" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="16">
            <a-form-item label="分集标题" required>
              <a-input v-model:value="form.title" placeholder="例如：风起青萍" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="制作状态">
          <a-select v-model:value="form.status">
            <a-select-option value="draft">草稿规划</a-select-option>
            <a-select-option value="script_ready">脚本就绪</a-select-option>
            <a-select-option value="sketching">出图中</a-select-option>
            <a-select-option value="sketched">分镜完成</a-select-option>
          </a-select>
        </a-form-item>

        <a-form-item label="分镜剧本内容">
          <a-textarea
            v-model:value="form.script_text"
            placeholder="输入分集对白、画面提示与镜头描述..."
            :rows="6"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  Plus,
  Film,
  Clapperboard,
  RefreshCw,
  Sparkles,
  Users,
  FileText,
  Check,
  ChevronDown,
  Image as LucideImage,
  ImageIcon,
  Pencil,
  Crop,
  Download,
  Upload as UploadIcon,
  Box,
  ExternalLink,
  Video,
  ArrowLeft,
  Boxes,
  Layers,
  Copy,
} from 'lucide-vue-next'
import {
  listEpisodes,
  createEpisode,
  updateEpisode,
  deleteEpisode,
  getEpisodeDetail,
  updateEpisodeBeat,
  generateBeatSketch,
  generateBeatRender,
  generateBeatImagesBatch,
  generateEpisodeRequiredAssets,
  generateEpisodeVideo,
  generateBeatH3Prompt,
  listAssets,
  listJobs,
} from '../../api/projects'

const props = defineProps({
  projectId: { type: String, required: true },
})

const emit = defineEmits(['detail-mode-change'])

const route = useRoute()
const router = useRouter()

// 剧集列表与当前选中的分集
const episodes = ref([])
const loading = ref(false)
const currentEpisodeId = ref(null)
const currentEpisode = ref(null)
const refreshingDetail = ref(false)
const regeneratingScript = ref(false)
const generatingEpisodeVideo = ref(false)
const globalVideoQuality = ref('0.4')
const globalVideoDuration = ref(8)

// 当前分集工作区 Tab: shots | script | compose
const currentTab = ref('shots')

// 镜头工作台状态
const showSketch = ref(true)
const selectedBeatId = ref(null)
const splitPct = ref(40)
const isDragging = ref(false)
const splitRef = ref(null)

// 资产关联与选项
const projectAssets = ref([])
const projectCharacters = computed(() => projectAssets.value.filter(a => a.kind === 'character'))
const projectScenes = computed(() => projectAssets.value.filter(a => a.kind === 'scene'))
const projectProps = computed(() => projectAssets.value.filter(a => a.kind === 'prop'))

const characterOptions = computed(() => projectCharacters.value.map(c => ({ value: c.name, label: c.name })))
const sceneOptions = computed(() => projectScenes.value.map(s => ({ value: s.id, label: s.name })))
const cameraOptions = [
  { value: '特写', label: '特写 (Close-up)' },
  { value: '中景', label: '中景 (Medium Shot)' },
  { value: '全景', label: '全景 (Wide / Establishing)' },
  { value: '俯视全景', label: '俯视鸟瞰 (Bird-eye)' },
  { value: '仰拍微距', label: '仰拍微距 (Low angle macro)' },
]

const timeOptions = [
  { value: '日', label: '日间 (Day)' },
  { value: '夜', label: '夜间 (Night)' },
  { value: '清晨', label: '清晨 (Dawn)' },
  { value: '黄昏', label: '黄昏 (Dusk)' },
  { value: '室内', label: '室内 (Interior)' },
  { value: '室外', label: '室外 (Exterior)' },
]

// 检视器手风琴状态 (默认全部展开)
const openSections = ref({
  text: true,
  sketch: true,
  render: true,
  video: true,
  material: true,
})

// H3 素材组状态
const h3RefImages = ref([])
const h3RefVideos = ref([])
const h3ImagesExpanded = ref(false)
const h3ImageSize = ref('match')
const h3Duration = ref(10)
const generatingH3Prompt = ref(false)
const trackedH3PromptJobId = ref(null)

const h3RefImagesVisible = computed(() =>
  h3ImagesExpanded.value ? h3RefImages.value : h3RefImages.value.slice(0, 3)
)


function renderH3Prompt(text) {
  if (!text) return ''
  // 将 H3 提示词格式化为带高亮的 HTML（支持中文与英文章节关键词与分镜标号）
  return text
    .replace(/(?:^|\n)(?:##\s*|###\s*)?(subject_definitions|summary|retention_analysis|detailed_description|overall_soundscape|non_diegetic_music|主体定义|摘要|保留分析|详细描述|整体声景|非叙事配乐|画面广告文案):/gm,
      '<br><span class="h3-section-key">$1:</span>')
    .replace(/<Picture (\d+)>/g, '<span class="h3-ref-chip-inline"><span class="h3-chip-dot"></span>图片$1</span>')
    .replace(/<Subject (\d+)>/g, '<span class="h3-subject-tag">&lt;Subject $1&gt;</span>')
    .replace(/\[Shot (\d+)\]/g, '<span class="h3-shot-tag">[Shot $1]</span>')
    .replace(/\n/g, '<br>')
    .replace(/^(?:<br>)+/, '')
}

async function handleGenerateH3Prompt() {
  if (!selectedBeat.value || generatingH3Prompt.value) return
  generatingH3Prompt.value = true
  try {
    const payload = {
      ref_images: h3RefImages.value.map((img, i) => ({
        index: i + 1,
        name: img.name,
        category: img.category,
        url: img.url,
      })),
      ref_videos: h3RefVideos.value.map((item, i) => ({
        index: i + 1,
        name: item.name,
        url: item.url,
      })),
      existing_prompt: selectedBeat.value.h3_prompt || '',
    }
    // 调用后端接口提交任务到「全部任务」
    const res = await generateBeatH3Prompt(
      props.projectId,
      currentEpisode.value.id,
      selectedBeat.value.id,
      payload
    )
    if (res?.job_id) {
      trackedH3PromptJobId.value = res.job_id
      message.success({
        content: `已提交 H3 提示词生成任务：${res.job_id}，可在「全部任务」查看进度`,
        key: 'h3PromptGen',
        duration: 4,
      })
      pollImageJobs()
    } else if (res?.prompt) {
      selectedBeat.value.h3_prompt = res.prompt
      openSections.value.material = true
      message.success({ content: '已生成电影级 H3 提示词', key: 'h3PromptGen' })
      generatingH3Prompt.value = false
    }
  } catch (err) {
    console.error('调用大模型生成 H3 提示词失败', err)
    const errText = err?.response?.data?.detail || err?.message || '生成失败'
    message.error({ content: `大模型生成失败: ${errText}`, key: 'h3PromptGen' })
    generatingH3Prompt.value = false
  }
}

function handleClearH3Material() {
  h3RefImages.value = []
  h3RefVideos.value = []
  if (selectedBeat.value) selectedBeat.value.h3_prompt = ''
  message.success('素材组已清空')
}

function getCharacterImage(char) {
  if (!char) return ''
  const look = getSelectedCharacterLook(char)
  if (look?.imageUrl) return look.imageUrl
  return char.image_url || char.extra?.avatar_url || char.extra?.reference_url || char.extra?.master_url || ''
}

function getSceneImage(scene) {
  if (!scene) return ''
  return scene.extra?.master_url || scene.image_url || scene.extra?.reference_url || ''
}

function getPropImage(prop) {
  if (!prop) return ''
  return prop.image_url || prop.extra?.reference_url || prop.extra?.turnaround_url || prop.extra?.master_url || ''
}

function getBeatSceneAsset(beat) {
  if (!beat) return null
  if (beat.scene_id) {
    const found = projectScenes.value.find(s => s.id === beat.scene_id)
    if (found) return found
  }
  if (beat.scene) {
    const found = projectScenes.value.find(s => s.name === beat.scene)
    if (found) return found
  }
  return projectScenes.value.length ? projectScenes.value[0] : null
}

function handleSelectExistingImages() {
  // 从项目资产中选择已有图片：出场角色图 + 场景主视图 + 出场道具参考图
  const beatCharIds = selectedBeat.value?.character_ids || []
  const beatChars = beatCharIds
    .map(id => projectCharacters.value.find(c => c.id === id))
    .filter(Boolean)
  let charImgs = (beatChars.length ? beatChars : projectCharacters.value)
    .map(c => ({ id: c.id, url: getCharacterImage(c), name: c.name, category: 'character' }))
    .filter(item => item.url)

  const sceneAsset = getBeatSceneAsset(selectedBeat.value)
  const sceneUrl = getSceneImage(sceneAsset)
  const sceneImgs = sceneUrl ? [{
    id: sceneAsset.id,
    url: sceneUrl,
    name: sceneAsset.name || '场景',
    category: 'scene'
  }] : []

  const beatPropIds = selectedBeat.value?.prop_ids || []
  const beatPropNames = selectedBeat.value?.props || []
  let beatProps = beatPropIds
    .map(id => projectProps.value.find(p => p.id === id))
    .filter(Boolean)
  for (const pName of beatPropNames) {
    if (!beatProps.some(p => p.name === pName)) {
      const found = projectProps.value.find(p => p.name === pName)
      if (found) beatProps.push(found)
    }
  }
  const propImgs = (beatProps.length ? beatProps : projectProps.value)
    .map(p => ({ id: p.id, url: getPropImage(p), name: p.name, category: 'prop' }))
    .filter(item => item.url)

  const imgs = [...charImgs, ...sceneImgs, ...propImgs]
  if (imgs.length) {
    h3RefImages.value = imgs.slice(0, 9)
    message.success(`已选入 ${Math.min(imgs.length, 9)} 张参考图片（包含出场角色、场景与道具）`)
  } else {
    message.info('资产库暂无可用图片，请先在资产库上传或生成角色/场景/道具图片')
  }
}

function removeH3RefImage(idx) {
  h3RefImages.value.splice(idx, 1)
}

function handleSelectExistingVideos() {
  message.info('视频选择功能待接入资产库')
}

function handleUploadH3Image(file) {
  const url = URL.createObjectURL(file)
  h3RefImages.value.push({ id: Date.now(), url, name: file.name })
  message.success(`已添加参考图片：${file.name}`)
  return false
}

function copyH3Prompt() {
  if (!selectedBeat.value?.h3_prompt) return
  navigator.clipboard.writeText(selectedBeat.value.h3_prompt)
    .then(() => message.success('H3 提示词已复制到剪贴板'))
    .catch(() => message.error('复制失败'))
}

// 各种生成 Loading 状态
const generatingBeatIds = reactive(new Set())
const generatingRenderBeatIds = reactive(new Set())
const batchGenerating = ref(false)
const batchGeneratingRenders = ref(false)
const batchGeneratingRequiredAssets = ref(false)
const generatingVideo = ref(false)
const currentSceneView = ref('front')
let imageJobPollTimer = null
const trackedBatchJobs = reactive(new Map())
const beatJobStates = reactive(new Map())

function generationStatusText(beatId, stage) {
  const status = beatJobStates.get(`${stage}:${beatId}`)
  if (status === 'queued') return '排队中'
  if (status === 'preparing') return '准备素材'
  if (status === 'storing') return '保存结果'
  if (status === 'failed') return '生成失败'
  return status === 'running' ? '生成中' : ''
}

// 视频设置参数
const videoWorkflow = ref('lightx2v')
const videoQuality = ref('0.2')
const videoSpeed = ref('balanced')

// 新增/编辑分集弹窗表单
const modalVisible = ref(false)
const isEdit = ref(false)
const submitting = ref(false)
const form = ref({
  id: '',
  episode_num: 1,
  title: '',
  status: 'draft',
  script_text: '',
  shots_count: 8,
})

// 计算属性
const selectedBeat = computed(() => {
  if (!currentEpisode.value?.beats?.length) return null
  return currentEpisode.value.beats.find(b => b.id === selectedBeatId.value) || currentEpisode.value.beats[0]
})

const promptDisplayRef = ref(null)

watch(
  () => [selectedBeat.value?.id, selectedBeat.value?.h3_prompt],
  ([newBeatId], [oldBeatId]) => {
    nextTick(() => {
      if (promptDisplayRef.value) {
        promptDisplayRef.value.scrollTop = 0
      }
    })
    if (newBeatId && newBeatId !== oldBeatId) {
      pollImageJobs()
    }
  }
)

const episodeProtagonist = computed(() => {
  const beats = currentEpisode.value?.beats || []
  for (const beat of beats) {
    const assetId = beat.character_ids?.[0]
    const character = projectCharacters.value.find(item => item.id === assetId)
    if (character) return character
  }
  return null
})

const selectedBeatCharacters = computed(() => {
  const ids = selectedBeat.value?.character_ids || []
  return ids
    .map(id => projectCharacters.value.find(item => item.id === id))
    .filter(Boolean)
})

function getCharacterLookOptions(character) {
  const looks = character?.extra?.identities || []
  return looks
    .filter(look => look?.id && look?.image_url)
    .map(look => ({
      value: look.id,
      label: look.name || look.description || look.id,
      imageUrl: look.image_url,
      description: look.appearance_details || look.description || '',
    }))
}

function getBeatCharacterLookId(character) {
  const mapped = selectedBeat.value?.character_look_ids?.[character.id]
  if (mapped) return mapped
  const legacy = selectedBeat.value?.character_look_id
  return getCharacterLookOptions(character).some(look => look.value === legacy) ? legacy : ''
}

function getSelectedCharacterLook(character) {
  const lookId = getBeatCharacterLookId(character)
  return getCharacterLookOptions(character).find(look => look.value === lookId) || null
}

const sketchedCount = computed(() => {
  return (currentEpisode.value?.beats || []).filter(b => Boolean(b.sketch_url)).length
})

const renderedCount = computed(() => {
  return (currentEpisode.value?.beats || []).filter(b => Boolean(b.render_url)).length
})

const stats = computed(() => {
  const eps = episodes.value || []
  return {
    total: eps.length,
    ready: eps.filter(e => e.status !== 'draft').length,
    characters: projectCharacters.value.length,
    scenes: projectScenes.value.length,
    props: projectProps.value.length,
    beats: eps.reduce((sum, e) => sum + (e.shots_count || 0), 0),
  }
})

function getStatusColor(s) {
  const map = { draft: 'default', script_ready: 'blue', scripting: 'processing', sketching: 'processing', sketched: 'green' }
  return map[s] || 'default'
}

function getStatusText(s) {
  const map = { draft: '草稿', script_ready: '脚本就绪', scripting: '生成中', sketching: '出图中', sketched: '分镜完成' }
  return map[s] || s || '草稿'
}

function getEpisodeCharCount(ep) {
  return projectCharacters.value.length || 2
}

function getEpisodeSceneCount(ep) {
  return projectScenes.value.length || 1
}

function getCharName(cid) {
  const c = projectCharacters.value.find(item => item.id === cid)
  return c ? c.name : '角色'
}

// ---------------- 剧集列表与详情流转 ----------------
async function fetchEpisodes() {
  loading.value = true
  try {
    const res = await listEpisodes(props.projectId)
    episodes.value = res || []
  } catch (err) {
    message.error('加载剧集列表失败')
  } finally {
    loading.value = false
  }
}

async function loadAssets() {
  try {
    const res = await listAssets(props.projectId)
    projectAssets.value = res || []
    if (selectedBeat.value && (h3RefImages.value.length === 0 || !selectedBeat.value.h3_prompt)) {
      initH3MaterialForBeat()
    }
  } catch (err) {
    console.error('加载资产列表失败', err)
  }
}

watch(
  () => projectCharacters.value,
  (chars) => {
    if (chars && chars.length && selectedBeat.value && h3RefImages.value.length === 0) {
      initH3MaterialForBeat()
    }
  },
  { deep: true }
)

function openEpisodeDetail(epId) {
  router.push(`/projects/${props.projectId}/workshop/${epId}`)
}

function handleBackToOverview() {
  router.push(`/projects/${props.projectId}/workshop`)
}

watch(
  () => route.params.episodeId,
  async (newEpId) => {
    if (newEpId) {
      currentEpisodeId.value = newEpId
      emit('detail-mode-change', true)
      await loadEpisodeDetail(newEpId)
    } else {
      currentEpisodeId.value = null
      currentEpisode.value = null
      emit('detail-mode-change', false)
    }
  },
  { immediate: true }
)

async function loadEpisodeDetail(epId) {
  refreshingDetail.value = true
  try {
    const res = await getEpisodeDetail(props.projectId, epId)
    currentEpisode.value = res
    if (res.beats?.length) {
      if (!selectedBeatId.value || !res.beats.some(b => b.id === selectedBeatId.value)) {
        selectedBeatId.value = res.beats[0].id
      }
    }
  } catch (err) {
    message.error('加载分集详细信息失败')
  } finally {
    refreshingDetail.value = false
  }
  await nextTick()
  h3RefImages.value = []
  initH3MaterialForBeat()
}

async function refreshCurrentEpisode() {
  if (currentEpisodeId.value) {
    await loadEpisodeDetail(currentEpisodeId.value)
    message.success('分集分镜数据已刷新')
  }
}

// 初始化当前 Beat 的 H3 素材组：自动填充参考图 + 生成默认提示词
function initH3MaterialForBeat() {
  if (!selectedBeat.value) return
  const beat = selectedBeat.value
  const beatCharIds = beat.character_ids || []
  const beatChars = beatCharIds
    .map(id => projectCharacters.value.find(c => c.id === id))
    .filter(Boolean)

  // 1. 参考图：出场角色参考图 + 场景主视图 + 出场道具参考图
  if (h3RefImages.value.length === 0) {
    let charImgs = []
    if (beatChars.length) {
      charImgs = beatChars
        .map(c => ({ id: c.id, url: getCharacterImage(c), name: c.name, category: 'character' }))
        .filter(item => item.url)
    }
    // 如果当前 Beat 角色未生成图片或未选角色，从项目所有角色中挑选已有图的角色
    if (!charImgs.length && projectCharacters.value.length) {
      charImgs = projectCharacters.value
        .map(c => ({ id: c.id, url: getCharacterImage(c), name: c.name, category: 'character' }))
        .filter(item => item.url)
        .slice(0, 2)
    }

    // 场景主视图参考图 (Picture N，与视频生成任务严格一致)
    const sceneAsset = getBeatSceneAsset(beat)
    const sceneUrl = getSceneImage(sceneAsset)
    const sceneImgs = sceneUrl ? [{
      id: sceneAsset.id,
      url: sceneUrl,
      name: sceneAsset.name || '场景',
      category: 'scene'
    }] : []

    // 出场道具参考图
    const beatPropIds = beat.prop_ids || []
    const beatPropNames = beat.props || []
    let beatProps = beatPropIds
      .map(id => projectProps.value.find(p => p.id === id))
      .filter(Boolean)
    for (const pName of beatPropNames) {
      if (!beatProps.some(p => p.name === pName)) {
        const found = projectProps.value.find(p => p.name === pName)
        if (found) beatProps.push(found)
      }
    }
    const propImgs = beatProps
      .map(p => ({
        id: p.id,
        url: getPropImage(p),
        name: p.name,
        category: 'prop'
      }))
      .filter(item => item.url)

    let source = [...charImgs, ...sceneImgs, ...propImgs]

    // 如果还没有，尝试项目其它带图资产兜底
    if (!source.length && projectAssets.value.length) {
      source = projectAssets.value
        .map(a => ({
          id: a.id,
          url: a.image_url || a.extra?.master_url || a.extra?.reference_url || a.extra?.avatar_url || '',
          name: a.name,
          category: a.kind
        }))
        .filter(item => item.url)
        .slice(0, 9)
    }
    if (source.length) {
      h3RefImages.value = source
    }
  }
}

function selectBeat(beat) {
  selectedBeatId.value = beat.id
  // 切换 Beat 时自动初始化素材组：填充参考图 + 生成默认提示词
  h3RefImages.value = []
  nextTick(() => {
    initH3MaterialForBeat()
  })
}

function toggleSection(key) {
  openSections.value[key] = !openSections.value[key]
}


// ---------------- 分镜数据编辑与保存 ----------------
const editableBeatFields = [
  'heading', 'speaker', 'dialogue', 'dialogue_turns', 'visible_text', 'action', 'camera', 'scene', 'scene_id', 'time_of_day',
  'characters', 'character_ids', 'character_look_id', 'character_look_ids', 'props', 'prop_ids', 'visual_prompt', 'video_prompt_zh', 'video_duration',
]

async function saveCurrentBeat(fields = null) {
  if (!currentEpisode.value || !selectedBeat.value) return
  const episodeId = currentEpisode.value.id
  const beatId = selectedBeat.value.id
  const keys = Array.isArray(fields) ? fields : editableBeatFields
  const payload = Object.fromEntries(
    keys.filter(key => key in selectedBeat.value).map(key => [key, selectedBeat.value[key]]),
  )
  try {
    await updateEpisodeBeat(props.projectId, episodeId, beatId, payload)
    message.success('分镜设定已同步保存')
  } catch (err) {
    message.error('保存分镜失败')
  }
}

function onSceneSelectChange(val) {
  if (!selectedBeat.value) return
  const s = projectScenes.value.find(item => item.id === val)
  if (s) {
    selectedBeat.value.scene = s.name
  }
  saveCurrentBeat()
  h3RefImages.value = []
  nextTick(() => {
    initH3MaterialForBeat()
  })
}

function toggleBeatCharacter(cid) {
  if (!selectedBeat.value) return
  if (!selectedBeat.value.character_ids) selectedBeat.value.character_ids = []
  const idx = selectedBeat.value.character_ids.indexOf(cid)
  if (idx === -1) {
    selectedBeat.value.character_ids.push(cid)
  } else {
    selectedBeat.value.character_ids.splice(idx, 1)
  }
  if (!selectedBeat.value.character_look_ids || typeof selectedBeat.value.character_look_ids !== 'object') {
    selectedBeat.value.character_look_ids = {}
  }
  if (idx !== -1) {
    delete selectedBeat.value.character_look_ids[cid]
    if (episodeProtagonist.value?.id === cid) selectedBeat.value.character_look_id = undefined
  }
  saveCurrentBeat()
  h3RefImages.value = []
  nextTick(() => {
    initH3MaterialForBeat()
  })
}

function onCharacterLookChange(characterId, lookId) {
  if (!selectedBeat.value.character_look_ids || typeof selectedBeat.value.character_look_ids !== 'object') {
    selectedBeat.value.character_look_ids = {}
  }
  if (lookId) selectedBeat.value.character_look_ids[characterId] = lookId
  else delete selectedBeat.value.character_look_ids[characterId]
  if (episodeProtagonist.value?.id === characterId) {
    selectedBeat.value.character_look_id = lookId || undefined
  }
  saveCurrentBeat(['character_look_id', 'character_look_ids'])
  h3RefImages.value = []
  nextTick(() => {
    initH3MaterialForBeat()
  })
}

function toggleBeatProp(pid) {
  if (!selectedBeat.value) return
  if (!selectedBeat.value.prop_ids) selectedBeat.value.prop_ids = []
  const idx = selectedBeat.value.prop_ids.indexOf(pid)
  if (idx === -1) {
    selectedBeat.value.prop_ids.push(pid)
  } else {
    selectedBeat.value.prop_ids.splice(idx, 1)
  }
  saveCurrentBeat(['prop_ids'])
  h3RefImages.value = []
  nextTick(() => {
    initH3MaterialForBeat()
  })
}

// ---------------- GRS 分镜生图调用 ----------------
function applyBeatGenerationResult(episodeId, res, stage) {
  if (!res?.image_url || currentEpisode.value?.id !== episodeId) return
  const target = currentEpisode.value.beats?.find(item => item.id === res.beat_id)
  if (!target) return
  if (stage === 'sketch') {
    target.sketch_url = res.image_url
    target.sketch_prompt = res.beat?.sketch_prompt || target.sketch_prompt
    target.sketch_job_id = res.job_id
    target.status = res.beat?.status || 'sketched'
  } else {
    target.render_url = res.image_url
    target.render_prompt = res.beat?.render_prompt || target.render_prompt
    target.render_job_id = res.job_id
    target.render_status = res.beat?.render_status || 'succeeded'
  }
}

async function generateSingleBeatSketch() {
  if (!currentEpisode.value || !selectedBeat.value) return
  const beat = selectedBeat.value
  const episodeId = currentEpisode.value.id
  if (generatingBeatIds.has(beat.id)) return
  generatingBeatIds.add(beat.id)
  try {
    const res = await generateBeatSketch(props.projectId, episodeId, beat.id, {
      scene_view: currentSceneView.value,
      force: true,
    })
    message.success(`Beat ${beat.sequence} 草图生成成功！`)
    applyBeatGenerationResult(episodeId, res, 'sketch')
  } catch (err) {
    message.error(err?.response?.data?.detail || err?.message || '草图生成失败')
  } finally {
    generatingBeatIds.delete(beat.id)
  }
}

async function generateSingleBeatRender() {
  if (!currentEpisode.value || !selectedBeat.value) return
  const beat = selectedBeat.value
  if (!beat.sketch_url) {
    message.warning('请先生成草图')
    return
  }
  const episodeId = currentEpisode.value.id
  if (generatingRenderBeatIds.has(beat.id)) return
  generatingRenderBeatIds.add(beat.id)
  try {
    const res = await generateBeatRender(props.projectId, episodeId, beat.id, {
      scene_view: currentSceneView.value,
      force: true,
    })
    message.success(`Beat ${beat.sequence} 渲染图生成成功！`)
    applyBeatGenerationResult(episodeId, res, 'render')
  } catch (err) {
    message.error(err?.response?.data?.detail || err?.message || '渲染图生成失败')
  } finally {
    generatingRenderBeatIds.delete(beat.id)
  }
}

async function handleBatchGenerateSketches() {
  if (!currentEpisode.value?.beats?.length) return
  const unsketched = currentEpisode.value.beats.filter(b => !b.sketch_url)
  if (!unsketched.length) {
    message.info('当前分集所有分镜草图已全部就绪！')
    return
  }
  batchGenerating.value = true
  const episodeId = currentEpisode.value.id
  const batchBeatIds = new Set()
  message.loading({ content: `开始批量生成 ${unsketched.length} 张草图...`, key: 'batchGen' })
  try {
    for (const b of unsketched) {
      if (generatingBeatIds.has(b.id)) continue
      generatingBeatIds.add(b.id)
      batchBeatIds.add(b.id)
      try {
        const res = await generateBeatSketch(props.projectId, episodeId, b.id, {
          scene_view: currentSceneView.value,
          force: true,
        })
        applyBeatGenerationResult(episodeId, res, 'sketch')
      } finally {
        generatingBeatIds.delete(b.id)
      }
    }
    message.success({ content: '批量草图生成完成！', key: 'batchGen' })
  } catch (err) {
    message.error({ content: err?.response?.data?.detail || '部分草图生成失败', key: 'batchGen' })
  } finally {
    batchGenerating.value = false
    batchBeatIds.forEach(id => generatingBeatIds.delete(id))
  }
}

async function handleBatchGenerateRenders() {
  if (!currentEpisode.value?.beats?.length) return
  const pending = currentEpisode.value.beats.filter((b) => b.sketch_url && !b.render_url)
  if (!pending.length) {
    const missingSketch = currentEpisode.value.beats.filter((b) => !b.sketch_url).length
    message.info(missingSketch ? '请先为分镜生成草图，再批量生成渲染图' : '当前分集渲染图已全部就绪')
    return
  }
  batchGeneratingRenders.value = true
  const episodeId = currentEpisode.value.id
  const batchBeatIds = new Set()
  message.loading({ content: `开始批量生成 ${pending.length} 张渲染图...`, key: 'batchRender' })
  try {
    for (const b of pending) {
      if (generatingRenderBeatIds.has(b.id)) continue
      generatingRenderBeatIds.add(b.id)
      batchBeatIds.add(b.id)
      try {
        const res = await generateBeatRender(props.projectId, episodeId, b.id, {
          scene_view: currentSceneView.value,
          force: true,
        })
        applyBeatGenerationResult(episodeId, res, 'render')
      } finally {
        generatingRenderBeatIds.delete(b.id)
      }
    }
    message.success({ content: '批量渲染图生成完成！', key: 'batchRender' })
  } catch (err) {
    message.error({ content: err?.response?.data?.detail || '部分渲染图生成失败', key: 'batchRender' })
  } finally {
    batchGeneratingRenders.value = false
    batchBeatIds.forEach(id => generatingRenderBeatIds.delete(id))
  }
}

async function enqueueSingleSketch() {
  if (!currentEpisode.value || !selectedBeat.value || generatingBeatIds.has(selectedBeat.value.id)) return
  const beat = selectedBeat.value
  generatingBeatIds.add(beat.id)
  try {
    const res = await generateBeatSketch(props.projectId, currentEpisode.value.id, beat.id, {
      scene_view: currentSceneView.value, force: true,
    })
    beat.sketch_job_id = res.job_id
    message.success(`Beat ${beat.sequence} 草图任务已提交`)
  } catch (err) {
    generatingBeatIds.delete(beat.id)
    message.error(err?.response?.data?.detail || err?.message || '草图任务提交失败')
  }
}

async function enqueueSingleRender() {
  if (!currentEpisode.value || !selectedBeat.value || generatingRenderBeatIds.has(selectedBeat.value.id)) return
  const beat = selectedBeat.value
  if (!beat.sketch_url) {
    message.warning('请先生成草图')
    return
  }
  generatingRenderBeatIds.add(beat.id)
  try {
    const res = await generateBeatRender(props.projectId, currentEpisode.value.id, beat.id, {
      scene_view: currentSceneView.value, force: true,
    })
    beat.render_job_id = res.job_id
    beat.render_status = res.status
    message.success(`Beat ${beat.sequence} 渲染图任务已提交`)
  } catch (err) {
    generatingRenderBeatIds.delete(beat.id)
    message.error(err?.response?.data?.detail || err?.message || '渲染图任务提交失败')
  }
}

async function enqueueRequiredAssets() {
  if (!currentEpisode.value) return
  batchGeneratingRequiredAssets.value = true
  message.loading({ content: '正在索引本集主角、场景、道具…', key: 'batchRequiredAssets' })
  try {
    const res = await generateEpisodeRequiredAssets(props.projectId, currentEpisode.value.id, {
      model: 'gpt-image-2',
    })
    const queued = res.queued || 0
    const skippedExisting = (res.skipped || []).filter((item) => item.reason === '已有主图').length
    const indexed = res.indexed || {}
    const indexedCount = (indexed.characters?.length || 0) + (indexed.scenes?.length || 0) + (indexed.props?.length || 0)
    if (!queued) {
      message.info({
        content: skippedExisting
          ? `本集 ${indexedCount} 个主角/场景/道具主图已就绪，无需再提交`
          : ((res.skipped || [])[0]?.reason || '本集没有可提交的主角、场景或道具主图任务'),
        key: 'batchRequiredAssets',
      })
      return
    }
    message.success({
      content: `已提交 ${queued} 个主图任务（主角/场景/道具），按最大并发 ${res.concurrency || 5} 执行，请到「全部任务」查看`,
      key: 'batchRequiredAssets',
    })
  } catch (err) {
    message.error({ content: err?.response?.data?.detail || '提交所需资源任务失败', key: 'batchRequiredAssets' })
  } finally {
    batchGeneratingRequiredAssets.value = false
  }
}

async function enqueueBatch(stage) {
  if (!currentEpisode.value?.beats?.length) return
  const candidates = stage === 'sketch'
    ? currentEpisode.value.beats.filter(beat => !beat.sketch_url && !generatingBeatIds.has(beat.id))
    : currentEpisode.value.beats.filter(beat => beat.sketch_url && !beat.render_url && !generatingRenderBeatIds.has(beat.id))
  if (!candidates.length) {
    message.info(stage === 'sketch' ? '当前分集没有待生成草图' : '当前分集没有可生成的渲染图')
    return
  }
  const loadingRef = stage === 'sketch' ? batchGenerating : batchGeneratingRenders
  const messageKey = stage === 'sketch' ? 'batchGen' : 'batchRender'
  loadingRef.value = true
  message.loading({ content: `正在提交 ${candidates.length} 个任务...`, key: messageKey })
  try {
    const res = await generateBeatImagesBatch(props.projectId, currentEpisode.value.id, {
      stage, beat_ids: candidates.map(beat => beat.id), scene_view: currentSceneView.value, force: true,
    })
    const activeSet = stage === 'sketch' ? generatingBeatIds : generatingRenderBeatIds
    res.jobs.forEach(job => activeSet.add(job.beat_id))
    trackedBatchJobs.set(stage, new Set(res.jobs.map(job => job.job_id)))
    message.success({
      content: `已提交 ${res.jobs.length} 个任务${res.skipped.length ? `，跳过 ${res.skipped.length} 个` : ''}`,
      key: messageKey,
    })
  } catch (err) {
    message.error({ content: err?.response?.data?.detail || '批量任务提交失败', key: messageKey })
  } finally {
    loadingRef.value = false
  }
}

async function pollImageJobs() {
  if (!currentEpisode.value) return
  try {
    const previouslyActive = new Set([...generatingBeatIds, ...generatingRenderBeatIds])
    const jobs = await listJobs(props.projectId)
    const episodeJobs = jobs.filter(job => job.payload?.episode_id === currentEpisode.value.id)
    const activeStatuses = new Set(['queued', 'preparing', 'running', 'storing'])
    generatingBeatIds.clear()
    generatingRenderBeatIds.clear()
    beatJobStates.clear()
    episodeJobs.forEach(job => {
      const stage = job.payload?.target_type === 'beat_sketch' ? 'sketch' : (job.payload?.target_type === 'beat_render' ? 'render' : '')
      if (!stage) return
      const key = `${stage}:${job.payload.beat_id}`
      if (!beatJobStates.has(key)) beatJobStates.set(key, job.status)
      if (!activeStatuses.has(job.status)) return
      if (stage === 'sketch') generatingBeatIds.add(job.payload.beat_id)
      if (stage === 'render') generatingRenderBeatIds.add(job.payload.beat_id)
    })

    let refresh = false
    // 检测当前分镜的 H3 提示词任务状态
    const currentBeatId = selectedBeat.value?.id
    const activePromptJob = episodeJobs.find(job =>
      (job.job_type === 'h3_prompt' || job.payload?.target_type === 'h3_prompt') &&
      job.payload?.beat_id === currentBeatId &&
      activeStatuses.has(job.status)
    )
    if (activePromptJob) {
      generatingH3Prompt.value = true
      trackedH3PromptJobId.value = activePromptJob.id
    } else if (trackedH3PromptJobId.value) {
      const trackedJob = episodeJobs.find(job => job.id === trackedH3PromptJobId.value)
      if (trackedJob && !activeStatuses.has(trackedJob.status)) {
        generatingH3Prompt.value = false
        trackedH3PromptJobId.value = null
        if (trackedJob.status === 'completed' || trackedJob.status === 'succeeded') {
          const newPrompt = trackedJob.payload?.h3_prompt || trackedJob.payload?.result_prompt
          if (newPrompt && selectedBeat.value && selectedBeat.value.id === trackedJob.payload?.beat_id) {
            selectedBeat.value.h3_prompt = newPrompt
          }
          message.success({ content: 'H3 提示词已生成完成！', key: 'h3PromptGen' })
          refresh = true
        } else if (trackedJob.status === 'failed') {
          message.error({ content: `H3 提示词生成失败: ${trackedJob.error_message || '未知错误'}`, key: 'h3PromptGen' })
        }
      }
    }

    for (const [stage, ids] of trackedBatchJobs.entries()) {
      const relevant = episodeJobs.filter(job => ids.has(job.id))
      if (relevant.length !== ids.size || relevant.some(job => activeStatuses.has(job.status))) continue
      const completed = relevant.filter(job => ['completed', 'succeeded'].includes(job.status)).length
      const failed = relevant.filter(job => job.status === 'failed').length
      message[failed ? 'warning' : 'success'](`${stage === 'sketch' ? '批量草图' : '批量渲染图'}完成：成功 ${completed}，失败 ${failed}`)
      trackedBatchJobs.delete(stage)
      refresh = true
    }
    const currentlyActive = new Set([...generatingBeatIds, ...generatingRenderBeatIds])
    if ([...previouslyActive].some(beatId => !currentlyActive.has(beatId))) refresh = true
    if (refresh) await loadEpisodeDetail(currentEpisode.value.id)
  } catch (_) {
    // Explicit actions surface errors; transient polling errors stay silent.
  }
}

function toggleSceneBackground() {
  currentSceneView.value = currentSceneView.value === 'front' ? 'reverse' : 'front'
  message.info(`已切换场景机位视角：${currentSceneView.value === 'front' ? '正面源图' : '背面反打'}`)
}

function handleUploadSketch(file) {
  const reader = new FileReader()
  reader.onload = (e) => {
    if (selectedBeat.value) {
      selectedBeat.value.sketch_url = e.target.result
      saveCurrentBeat(['sketch_url'])
      message.success('已替换分镜草图')
    }
  }
  reader.readAsDataURL(file)
  return false
}

function handleUploadRender(file) {
  const reader = new FileReader()
  reader.onload = (e) => {
    if (selectedBeat.value) {
      selectedBeat.value.render_url = e.target.result
      saveCurrentBeat(['render_url'])
      message.success('已上传高精渲染图')
    }
  }
  reader.readAsDataURL(file)
  return false
}

function generateVideoPrompt() {
  if (!selectedBeat.value) return
  const action = selectedBeat.value.action || selectedBeat.value.heading
  selectedBeat.value.video_prompt_zh = `${action}，电影级流畅运镜，景深层次逼真流动`
  saveCurrentBeat(['video_prompt_zh'])
  message.success('已自动提炼视频运镜提示词')
}

async function handleGenerateVideo() {
  if (!selectedBeat.value) return
  generatingVideo.value = true
  try {
    message.loading({ content: '正在调用 LightX2V 发起视频生成任务...', key: 'vGen' })
    await new Promise(r => setTimeout(r, 2000))
    message.success({ content: '视频任务已进入渲染队列', key: 'vGen' })
  } finally {
    generatingVideo.value = false
  }
}

async function handleRegenerateScript() {
  regeneratingScript.value = true
  try {
    await refreshCurrentEpisode()
    message.success('剧本 Beat 分镜已重新编排就绪')
  } finally {
    regeneratingScript.value = false
  }
}

async function handleGenerateEpisodeVideo() {
  if (!currentEpisode.value || generatingEpisodeVideo.value) return
  generatingEpisodeVideo.value = true
  try {
    const beats = currentEpisode.value.beats || []
    const beatPrompts = beats
      .map(b => ({
        beat_id: b.id,
        prompt: (b.h3_prompt || '').trim(),
      }))
      .filter(p => p.prompt.length > 20)

    const payload = {
      duration_per_beat: Number(globalVideoDuration.value) || 8,
      quality: globalVideoQuality.value || '0.4',
    }
    // 当分集所有 Beat 在素材组中已有生成的 H3 提示词时，明确作为预生成提示词传入
    if (beatPrompts.length === beats.length && beats.length > 0) {
      payload.prompts = beatPrompts
      payload.prompt_source = 'workshop_material'
    }

    const res = await generateEpisodeVideo(props.projectId, currentEpisode.value.id, payload)
    message.success({
      content: `视频任务已创建：${res.job_id}，可在「全部任务」中查看进度`,
      duration: 6,
    })
  } catch (err) {
    const detail = err?.response?.data?.detail || err?.message || '视频任务创建失败'
    const queuedScenes = String(detail).includes('已自动提交场景主视图任务')
    const notice = queuedScenes ? message.warning : message.error
    notice({ content: detail, duration: queuedScenes ? 12 : 10 })
  } finally {
    generatingEpisodeVideo.value = false
  }
}

function handleToolNotice(name) {
  message.info(`已开启「${name}」模式`)
}

// ---------------- 左右拖拽调节分栏 ----------------
function startDragging(e) {
  isDragging.value = true
  document.addEventListener('mousemove', onDragging)
  document.addEventListener('mouseup', stopDragging)
}

function onDragging(e) {
  if (!isDragging.value || !splitRef.value) return
  const rect = splitRef.value.getBoundingClientRect()
  const offset = e.clientX - rect.left
  const pct = Math.max(25, Math.min(65, (offset / rect.width) * 100))
  splitPct.value = pct
}

function stopDragging() {
  isDragging.value = false
  document.removeEventListener('mousemove', onDragging)
  document.removeEventListener('mouseup', stopDragging)
}

// ---------------- 新建/修改分集弹窗 ----------------
function openCreateModal() {
  isEdit.value = false
  form.value = {
    id: '',
    episode_num: episodes.value.length + 1,
    title: `第 ${episodes.value.length + 1} 集`,
    status: 'draft',
    script_text: '',
    shots_count: 6,
  }
  modalVisible.value = true
}

function openEditModal(ep) {
  isEdit.value = true
  form.value = { ...ep }
  modalVisible.value = true
}

async function handleSubmit() {
  if (!form.value.title.trim()) {
    message.warning('请输入分集标题')
    return
  }
  submitting.value = true
  try {
    if (isEdit.value) {
      await updateEpisode(props.projectId, form.value.id, form.value)
      message.success('分集已更新')
    } else {
      await createEpisode(props.projectId, form.value)
      message.success('分集已创建')
    }
    modalVisible.value = false
    await fetchEpisodes()
  } catch (err) {
    message.error('操作失败')
  } finally {
    submitting.value = false
  }
}

async function handleDeleteEpisode(id) {
  try {
    await deleteEpisode(props.projectId, id)
    message.success('分集已删除')
    await fetchEpisodes()
  } catch (err) {
    message.error('删除失败')
  }
}

onMounted(async () => {
  await Promise.all([fetchEpisodes(), loadAssets()])
  await pollImageJobs()
  imageJobPollTimer = window.setInterval(pollImageJobs, 3000)
})

onUnmounted(() => {
  stopDragging()
  if (imageJobPollTimer) window.clearInterval(imageJobPollTimer)
})
</script>

<style scoped>
/* 样式系统：统一明亮白色现代设计规范 */
.workshop-container {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  background: #f8fafc;
  color: #0f172a;
}

.workshop-container.in-episode-detail {
  height: 100%;
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

.workshop-loading-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  min-height: 300px;
  gap: 12px;
  color: #64748b;
  font-size: 13px;
}

/* ==================== 1. 剧集工坊概览列表 (xiaji-workshop) ==================== */
.xiaji-workshop {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 20px;
}

.xiaji-workshop-hero {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
}

.xiaji-ingest-hero-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: rgba(112, 71, 246, 0.1);
  color: #7047f6;
  border: 1px solid rgba(112, 71, 246, 0.2);
}

.hero-text-col {
  flex: 1;
  min-width: 220px;
}

.hero-text-col h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}

.hero-text-col p {
  margin: 4px 0 0;
  font-size: 13px;
  color: #64748b;
}

.primary-action-btn {
  background: #7047f6;
  border-color: #7047f6;
}

.xiaji-workshop-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
  font-size: 13px;
  padding: 10px 16px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  color: #64748b;
}

.xiaji-workshop-stats strong {
  color: #0f172a;
  font-weight: 600;
  margin-left: 4px;
}

.empty-workshop-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 280px;
  border: 1px dashed #cbd5e1;
  background: #ffffff;
  border-radius: 12px;
  gap: 12px;
  color: #64748b;
}

.empty-icon {
  color: #94a3b8;
}

.xiaji-episode-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.xiaji-episode-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  color: #0f172a;
  text-align: left;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  transition: all 0.25s ease;
}

.xiaji-episode-card:hover {
  border-color: #8b5cf6;
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(139, 92, 246, 0.12);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.card-summary {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: #64748b;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}

.card-meta {
  font-size: 12px;
  font-style: normal;
  color: #94a3b8;
}

/* ==================== 2. 分集工作区详细界面 (xiaji-episode) ==================== */
.xiaji-episode {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  flex: 1;
  padding: 0;
  gap: 10px;
  background: #f8fafc;
  overflow: hidden;
}

.xiaji-episode-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}

.xiaji-episode-head-main {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.xiaji-episode-head-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.back-btn {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #334155;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.back-btn:hover {
  background: #f1f5f9;
  color: #0f172a;
  border-color: #94a3b8;
}

.xiaji-episode-head h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.episode-meta-line {
  margin: 0;
  font-size: 12px;
  color: #64748b;
}

.xiaji-episode-head-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.head-param-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #ffffff;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.head-param-lbl {
  font-size: 12px;
  color: #475569;
  white-space: nowrap;
  font-weight: 500;
}

/* Tabs 深度定制：完全适配沉浸式 Flex 满高布局 */
:deep(.episode-tabs) {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  height: 100%;
}

:deep(.episode-tabs > .ant-tabs-nav) {
  margin-bottom: 8px;
  flex-shrink: 0;
}

:deep(.episode-tabs > .ant-tabs-content-holder) {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  height: 100%;
}

:deep(.episode-tabs > .ant-tabs-content-holder > .ant-tabs-content) {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  height: 100%;
}

:deep(.episode-tabs > .ant-tabs-content-holder > .ant-tabs-content > .ant-tabs-tabpane) {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  height: 100%;
}

/* ==================== 3. 镜头工作台 (XiajiShotsWorkbench) ==================== */
.xiaji-shots-workbench {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  height: 100%;
}

.xiaji-shots-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-bottom: 0;
  border-radius: 10px 10px 0 0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.sketched-count-label {
  font-size: 12px;
  color: #64748b;
}

.toolbar-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.xiaji-shots-split {
  display: flex;
  flex: 1;
  min-height: 0;
  border: 1px solid #e2e8f0;
  border-radius: 0 0 10px 10px;
  overflow: hidden;
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

/* 左侧分镜卡片列表 */
.xiaji-shots-grid-pane {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 12px 24px;
  border-right: 1px solid #e2e8f0;
  background: #f8fafc;
}

.xiaji-shot-tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}

.xiaji-shot-tile {
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  color: #0f172a;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.xiaji-shot-tile:hover {
  border-color: #8b5cf6;
  box-shadow: 0 2px 8px rgba(139, 92, 246, 0.15);
}

.xiaji-shot-tile.is-selected {
  border-color: #7047f6;
  box-shadow: 0 0 0 2px #7047f6;
  background: #f5f3ff;
}

.xiaji-shot-tile-num {
  padding: 6px 8px;
  font-size: 11px;
  font-weight: 700;
  color: #7047f6;
  font-variant-numeric: tabular-nums;
  background: #ffffff;
}

.xiaji-shot-tile.is-selected .xiaji-shot-tile-num {
  background: #f5f3ff;
}

.xiaji-shot-tile-media {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100px;
  background: #f1f5f9;
  border-top: 1px solid #e2e8f0;
  border-bottom: 1px solid #e2e8f0;
  color: #94a3b8;
  overflow: hidden;
}

.xiaji-shot-tile-media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.xiaji-shot-tile-busy {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #7047f6;
}

.tile-caption {
  margin: 0;
  padding: 6px 8px 8px;
  font-size: 11px;
  line-height: 1.4;
  color: #475569;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  background: #ffffff;
}

.xiaji-shot-tile.is-selected .tile-caption {
  background: #f5f3ff;
}

/* 分栏拖拽手柄 */
.xiaji-shots-gutter {
  position: relative;
  width: 6px;
  flex-shrink: 0;
  cursor: col-resize;
  background: #e2e8f0;
  transition: background 0.2s;
}

.xiaji-shots-gutter:hover {
  background: #7047f6;
}

/* 右侧检视器 */
.xiaji-shots-detail {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #ffffff;
  padding: 0;
}

.xiaji-shot-pane-container {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #ffffff;
}

.xiaji-shot-pane-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
  flex-shrink: 0;
}

.topbar-title {
  font-size: 13px;
  font-weight: 700;
  color: #7047f6;
}

.xiaji-pane-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  color: #334155;
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: all 0.2s;
}

.xiaji-pane-btn:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
  color: #0f172a;
}

.xiaji-pane-scroll-area {
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 16px 18px 40px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: #ffffff;
  scroll-behavior: smooth;
}

.xiaji-pane-section {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  flex-shrink: 0;
  overflow: visible;
  transition: border-color 0.2s;
}

.xiaji-pane-section:hover {
  border-color: #cbd5e1;
}

.xiaji-pane-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding: 11px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #f1f5f9;
  border-radius: 9px 9px 0 0;
  cursor: pointer;
  user-select: none;
  position: sticky;
  top: 0;
  z-index: 10;
  transition: background 0.2s;
}

.xiaji-pane-section-header:hover {
  background: #f1f5f9;
}

.section-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #0f172a;
  font-weight: 600;
  font-size: 13px;
}

.section-header-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.generate-cta-row {
  display: flex;
  width: 100%;
}

.generate-cta-row .ant-btn {
  width: 100%;
  height: 40px;
  font-size: 14px;
  font-weight: 600;
}

.arrow-icon {
  transition: transform 0.2s;
  color: #64748b;
}

.arrow-icon.is-collapsed {
  transform: rotate(-90deg);
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  padding: 3px 9px;
  border-radius: 12px;
}

.status-chip.is-active {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
}

.status-chip.is-idle {
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
}

.chip-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.xiaji-pane-section-body {
  padding: 16px;
  background: #ffffff;
  border-radius: 0 0 9px 9px;
}

/* 表单结构 */
.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
  width: 100%;
}

.form-label {
  font-size: 12px;
  color: #334155;
  font-weight: 500;
}

.look-option {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.look-option img {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  border-radius: 4px;
  object-fit: cover;
  border: 1px solid #e2e8f0;
}

.character-look-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.character-look-row {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #ffffff;
}

.character-look-heading {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.character-look-heading img {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  border-radius: 50%;
  object-fit: cover;
}

.character-look-heading strong {
  min-width: 0;
  color: #1e293b;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.character-look-heading > span:last-child {
  margin-left: auto;
  color: #64748b;
  font-size: 10px;
  white-space: nowrap;
}

.selected-look-preview {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
}

.selected-look-preview img {
  width: 52px;
  height: 68px;
  border-radius: 4px;
  object-fit: cover;
  background: #e2e8f0;
}

.selected-look-preview strong {
  display: block;
  color: #1e293b;
  font-size: 12px;
  line-height: 1.4;
}

.selected-look-preview p,
.look-empty-hint {
  margin: 3px 0 0;
  color: #64748b;
  font-size: 11px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.look-empty-hint {
  margin-top: 0;
}

.form-row-two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.chips-flex-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.xiaji-ref-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 16px;
  color: #334155;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.xiaji-ref-chip:hover {
  border-color: #8b5cf6;
  background: #f5f3ff;
}

.xiaji-ref-chip img {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  object-fit: cover;
}

.chip-avatar-fallback {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
}

.xiaji-ref-chip.is-on {
  background: #ede9fe;
  border-color: #8b5cf6;
  color: #6d28d9;
  font-weight: 500;
}

.empty-hint {
  font-size: 12px;
  color: #94a3b8;
}

/* 草图/渲染图/视频卡片排版 */
.sketch-block {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.sketch-actor-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.sketch-actor-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 12px;
  background: #ede9fe;
  color: #6d28d9;
  border: 1px solid #ddd6fe;
}

.sketch-actor-pill .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #7047f6;
}

.sketch-actor-pill.is-none {
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
}

.sketch-cards-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-top: 2px;
}

.sketch-main-card {
  position: relative;
  width: 320px;
  max-width: calc(100% - 110px);
  aspect-ratio: 16 / 9;
  background: #f8fafc;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.main-preview-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.sketch-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  gap: 8px;
  color: #64748b;
  cursor: pointer;
  font-size: 12px;
  background: #f8fafc;
  padding: 16px;
  text-align: center;
  transition: all 0.2s;
}

.sketch-placeholder:hover {
  background: #f1f5f9;
  color: #7047f6;
}

.sketch-placeholder.is-busy {
  color: #7047f6;
}

.sketch-thumb-card {
  position: relative;
  width: 96px;
  aspect-ratio: 16 / 9;
  background: #f8fafc;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  flex-shrink: 0;
}

.sketch-thumb-card img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.version-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  font-size: 9px;
  padding: 1px 5px;
  background: rgba(15, 23, 42, 0.75);
  border-radius: 4px;
  color: #ffffff;
}

.sketch-bottom-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  color: #334155;
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: all 0.2s;
}

.tool-btn:hover {
  background: #f1f5f9;
  color: #0f172a;
  border-color: #94a3b8;
}

.tool-btn.is-primary {
  background: #7047f6;
  border-color: #7047f6;
  color: #fff;
}

.tool-btn.is-primary:hover {
  background: #5b21b6;
  border-color: #5b21b6;
  color: #fff;
}

.tool-btn.is-disabled {
  opacity: 0.5;
  pointer-events: none;
}

/* 视频设置与预览 */
.video-toolbar-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.param-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.param-lbl {
  font-size: 11px;
  color: #475569;
  font-weight: 500;
}

.prompt-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.video-preview-stage {
  width: 100%;
}

.video-main-card {
  position: relative;
  width: 100%;
  max-width: 460px;
  aspect-ratio: 16 / 9;
  background: #0f172a;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.video-player-element {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #000000;
}

.video-preview-cover {
  position: relative;
  width: 100%;
  height: 100%;
}

.video-preview-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.cover-overlay {
  position: absolute;
  inset: 0;
  background: rgba(15, 23, 42, 0.6);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #ffffff;
  font-size: 12px;
}

.video-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #94a3b8;
  font-size: 12px;
  padding: 20px;
  text-align: center;
}

.video-placeholder.is-busy {
  color: #c4b5fd;
}

.generate-video-btn {
  background: #7047f6;
  border-color: #7047f6;
}

/* ==================== 4. 剧本 Tab (ScriptPane) ==================== */
.xiaji-script-grid {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  gap: 16px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.xiaji-script-col {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.script-section-box {
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.section-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.section-head h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
}

.section-head em {
  font-size: 12px;
  color: #64748b;
  font-style: normal;
}

.xiaji-workshop-assets {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.xiaji-workshop-assets li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 8px;
}

.xiaji-workshop-assets img,
.xiaji-workshop-asset-fallback {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  object-fit: cover;
}

.xiaji-workshop-asset-fallback {
  background: #e2e8f0;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}

.asset-info strong {
  display: block;
  font-size: 13px;
  color: #0f172a;
}

.asset-info em {
  font-size: 11px;
  color: #64748b;
  font-style: normal;
}

.xiaji-original-lines {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 400px;
  overflow-y: auto;
}

.xiaji-original-lines li {
  display: flex;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  font-size: 12px;
}

.line-no {
  color: #7047f6;
  font-weight: 600;
  font-family: monospace;
}

.line-content {
  margin: 0;
  color: #334155;
}

.xiaji-beat-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 520px;
  overflow-y: auto;
}

.xiaji-beat {
  padding: 10px 12px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-left: 3px solid #7047f6;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.beat-header {
  font-size: 12px;
  font-weight: 600;
  color: #7047f6;
}

.beat-dialogue {
  margin: 4px 0;
  font-size: 13px;
  color: #0f172a;
}

.beat-action {
  margin: 4px 0 0;
  font-size: 12px;
  color: #475569;
}

.beat-action .lbl {
  color: #64748b;
}

/* ==================== 5. 合成 Tab (ComposePane) ==================== */
.compose-summary-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.summary-info h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
}

.summary-info p {
  margin: 4px 0 0;
  font-size: 13px;
  color: #64748b;
}

.timeline-preview-section h4 {
  margin: 0 0 10px;
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
}

.timeline-tiles-scroll {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 8px;
}

.timeline-shot-card {
  width: 140px;
  flex-shrink: 0;
  border-radius: 8px;
  overflow: hidden;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.shot-thumb {
  height: 80px;
  background: #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid #f1f5f9;
}

.shot-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.placeholder-thumb {
  font-size: 11px;
  color: #94a3b8;
}

.shot-title {
  padding: 6px;
  font-size: 11px;
  color: #334155;
  text-align: center;
}

.xiaji-compose-pane {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

/* 优雅精致的极细滚动条设计 */
.xiaji-pane-scroll-area::-webkit-scrollbar,
.xiaji-shots-grid-pane::-webkit-scrollbar,
.xiaji-script-grid::-webkit-scrollbar,
.xiaji-compose-pane::-webkit-scrollbar,
.xiaji-original-lines::-webkit-scrollbar,
.xiaji-beat-list::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.xiaji-pane-scroll-area::-webkit-scrollbar-track,
.xiaji-shots-grid-pane::-webkit-scrollbar-track,
.xiaji-script-grid::-webkit-scrollbar-track,
.xiaji-compose-pane::-webkit-scrollbar-track,
.xiaji-original-lines::-webkit-scrollbar-track,
.xiaji-beat-list::-webkit-scrollbar-track {
  background: transparent;
}

.xiaji-pane-scroll-area::-webkit-scrollbar-thumb,
.xiaji-shots-grid-pane::-webkit-scrollbar-thumb,
.xiaji-script-grid::-webkit-scrollbar-thumb,
.xiaji-compose-pane::-webkit-scrollbar-thumb,
.xiaji-original-lines::-webkit-scrollbar-thumb,
.xiaji-beat-list::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.16);
  border-radius: 4px;
}

.xiaji-pane-scroll-area::-webkit-scrollbar-thumb:hover,
.xiaji-shots-grid-pane::-webkit-scrollbar-thumb:hover,
.xiaji-script-grid::-webkit-scrollbar-thumb:hover,
.xiaji-compose-pane::-webkit-scrollbar-thumb:hover,
.xiaji-original-lines::-webkit-scrollbar-thumb:hover,
.xiaji-beat-list::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.32);
}

/* ==================== H3 素材组 Pane ==================== */
.h3-material-section {
  /* 完全继承 .xiaji-pane-section 样式，无需覆盖 */
}

.h3-material-body {
  background: #ffffff;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
}

.h3-material-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 14px;
  background: #f8fafc;
  border-bottom: 1px solid #f1f5f9;
}

.h3-group-title {
  font-size: 13px;
  font-weight: 600;
  color: #7047f6;
  letter-spacing: 0.01em;
}

.h3-material-params {
  display: flex;
  align-items: center;
  gap: 10px;
}

.h3-param-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #ffffff;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}

.h3-param-lbl {
  font-size: 12px;
  color: #475569;
  font-weight: 500;
  white-space: nowrap;
}

.h3-material-content {
  display: flex;
  min-height: 300px;
  max-height: 500px;
}

/* 左侧素材区 */
.h3-material-left {
  width: 280px;
  min-width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e2e8f0;
  overflow-y: auto;
  background: #ffffff;
}

.h3-ref-block {
  padding: 12px 14px;
  border-bottom: 1px solid #f1f5f9;
}

.h3-ref-block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.h3-ref-label {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}

.h3-ref-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.h3-ref-img-cell {
  position: relative;
  width: 72px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.h3-ref-img-cell img {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.h3-ref-del-btn {
  position: absolute;
  top: -4px;
  right: -4px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #ef4444;
  color: #ffffff;
  border: 1.5px solid #ffffff;
  display: none;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: bold;
  line-height: 1;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  transition: transform 0.15s;
  padding: 0;
  z-index: 2;
}

.h3-ref-img-cell:hover .h3-ref-del-btn {
  display: flex;
}

.h3-ref-del-btn:hover {
  transform: scale(1.15);
  background: #dc2626;
}

.h3-ref-video-thumb {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #f1f5f9;
}

.h3-ref-img-empty {
  width: 72px;
  height: 72px;
  border-radius: 6px;
  border: 1px dashed #cbd5e1;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  color: #94a3b8;
  font-size: 11px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s, color 0.2s;
}

.h3-ref-img-empty.is-dark {
  background: #f1f5f9;
}

.h3-ref-img-empty:hover {
  border-color: #8b5cf6;
  background: #f5f3ff;
  color: #7047f6;
}

.h3-ref-info {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  padding: 0 2px;
}

.h3-ref-seq {
  font-size: 11px;
  font-weight: 600;
  color: #334155;
  text-align: center;
  line-height: 1.2;
}

.h3-ref-name {
  font-size: 10px;
  color: #64748b;
  max-width: 68px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
  line-height: 1.3;
}

.h3-ref-cat-dot {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  margin-right: 2px;
  vertical-align: middle;
}

.h3-ref-cat-dot.is-char {
  background: #3b82f6;
}

.h3-ref-cat-dot.is-scene {
  background: #10b981;
}

.h3-ref-cat-dot.is-prop {
  background: #f59e0b;
}

.h3-ref-add-btn {
  width: 72px;
  height: 72px;
  border-radius: 6px;
  border: 1px dashed #c4b5fd;
  background: #f5f3ff;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #7047f6;
  cursor: pointer;
  transition: all 0.2s;
}

.h3-ref-add-btn:hover {
  border-color: #7047f6;
  background: #ede9fe;
}

.h3-ref-expand {
  margin-top: 8px;
  font-size: 12px;
  color: #7047f6;
  cursor: pointer;
  text-align: center;
  padding: 4px;
  border-radius: 4px;
  transition: background 0.15s;
}

.h3-ref-expand:hover {
  background: #f5f3ff;
}

/* 右侧提示词面板 */
.h3-prompt-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  background: #ffffff;
}

.h3-prompt-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px 8px;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
  background: #f8fafc;
}

.h3-prompt-title {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}

.h3-prompt-display {
  flex: 1;
  overflow-y: auto;
  padding: 16px 18px;
  font-size: 13px;
  line-height: 1.85;
  color: #1e293b;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  word-break: break-word;
}

.h3-prompt-display :deep(.h3-section-key) {
  display: block;
  color: #0f172a;
  font-weight: 700;
  font-size: 13px;
  margin-top: 10px;
  margin-bottom: 2px;
}

.h3-prompt-display :deep(.h3-section-key:first-child) {
  margin-top: 0;
}

.h3-prompt-display :deep(.h3-ref-chip-inline) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  border-radius: 4px;
  padding: 1px 7px 1px 5px;
  font-size: 11.5px;
  color: #047857;
  font-weight: 600;
  white-space: nowrap;
  vertical-align: middle;
  margin: 0 2px;
}

.h3-prompt-display :deep(.h3-chip-dot) {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  flex-shrink: 0;
}

.h3-prompt-display :deep(.h3-subject-tag) {
  display: inline-flex;
  align-items: center;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 11.5px;
  color: #dc2626;
  font-weight: 600;
  white-space: nowrap;
  vertical-align: middle;
  margin: 0 2px;
}

.h3-prompt-display :deep(.h3-shot-tag) {
  display: inline-flex;
  align-items: center;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 11.5px;
  color: #475569;
  font-weight: 700;
  margin-right: 4px;
}

.h3-prompt-loading {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #64748b;
  font-size: 13px;
}

.h3-prompt-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #94a3b8;
  padding: 24px;
  text-align: center;
}

.h3-prompt-empty span {
  font-size: 13px;
  font-weight: 500;
  color: #64748b;
}

.h3-prompt-empty p {
  font-size: 12px;
  color: #94a3b8;
  margin: 0;
  line-height: 1.6;
  max-width: 280px;
}

.h3-prompt-display::-webkit-scrollbar,
.h3-material-left::-webkit-scrollbar {
  width: 4px;
}

.h3-prompt-display::-webkit-scrollbar-track,
.h3-material-left::-webkit-scrollbar-track {
  background: transparent;
}

.h3-prompt-display::-webkit-scrollbar-thumb,
.h3-material-left::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.16);
  border-radius: 4px;
}

.h3-prompt-display::-webkit-scrollbar-thumb:hover,
.h3-material-left::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.32);
}
</style>
