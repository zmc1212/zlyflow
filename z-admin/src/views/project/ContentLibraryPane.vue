<template>
  <div class="content-library-pane">
    <!-- 顶部操作栏 -->
    <div class="sub-pane-header">
      <div>
        <h2 class="sub-pane-title">内容库</h2>
        <p class="sub-pane-subtitle">
          导入标准分镜剧本，系统自动高精度拆解分集、镜头、人物、道具、场景及全局视觉设定，并支持全链路协同流转。
        </p>
      </div>

      <a-space>
        <a-button @click="formatModalVisible = true">
          <template #icon><BookOpen :size="15" /></template>
          标准剧本规范
        </a-button>
        <a-button type="primary" class="primary-btn" @click="openImportModal">
          <template #icon><Plus :size="16" /></template>
          导入剧本文档
        </a-button>
      </a-space>
    </div>

    <!-- 加载与主内容 -->
    <a-spin :spinning="loading">
      <div v-if="documents.length === 0" class="empty-doc-box">
        <div class="empty-icon-wrap">
          <FileText :size="40" />
        </div>
        <h3>暂无导入的剧本文档</h3>
        <p>支持导入符合《短剧详细分镜规范》的标准文档，系统将自动识别镜头、角色、道具与场景要素。</p>
        <a-space>
          <a-button type="primary" @click="openImportModal">立即导入剧本</a-button>
          <a-button @click="quickImportSample">一键导入《寒门硕士》标准范例</a-button>
        </a-space>
      </div>

      <div v-else class="content-layout">
        <!-- 左侧文档列表 -->
        <div class="doc-list-sidebar">
          <div class="doc-list-header">
            <span>已导入剧本 ({{ documents.length }})</span>
          </div>
          <div class="doc-items-scroll">
            <div
              v-for="doc in documents"
              :key="doc.id"
              class="doc-item"
              :class="{ active: selectedDoc && selectedDoc.id === doc.id }"
              @click="selectedDoc = doc"
            >
              <div class="doc-item-title">
                <FileText :size="16" class="doc-icon" />
                <span class="name" :title="doc.filename">{{ doc.filename }}</span>
              </div>
              <div class="doc-item-meta">
                <a-tag color="purple" size="small">
                  {{ doc.analysis?.episodes?.length ? `${doc.analysis.episodes.length} 集` : '单篇' }}
                </a-tag>
                <span class="time">{{ doc.created_at.slice(5, 16) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 右侧剧本与分析详情 -->
        <div v-if="selectedDoc" class="doc-detail-main">
          <!-- 概览栏 -->
          <div class="detail-top-card">
            <div class="detail-top-header">
              <div>
                <h3 class="detail-title">{{ selectedDoc.filename }}</h3>
                <div class="detail-tags">
                  <a-tag color="purple">{{ selectedDoc.spine_template === 'drama' ? '精品分镜剧' : '解说剧模板' }}</a-tag>
                  <a-tag v-if="selectedDoc.analysis?.positioning?.genre" color="blue">
                    {{ selectedDoc.analysis.positioning.genre }}
                  </a-tag>
                  <a-tag v-if="selectedDoc.analysis?.positioning?.worldview" color="cyan">
                    {{ selectedDoc.analysis.positioning.worldview }}
                  </a-tag>
                  <span class="char-count">约 {{ selectedDoc.file_size }} 字符</span>
                </div>
              </div>

              <a-space>
                <a-button
                  type="primary"
                  :loading="transferring"
                  class="transfer-btn"
                  @click="handleTransferAssets"
                >
                  <template #icon><Users :size="15" /></template>
                  转入资产库
                </a-button>

                <a-button
                  :loading="transferringEp"
                  class="sync-ep-btn"
                  @click="handleTransferEpisodes"
                >
                  <template #icon><Film :size="15" /></template>
                  同步至剧集工坊
                </a-button>

                <a-popconfirm
                  title="确认删除该剧本文档？"
                  ok-text="删除"
                  cancel-text="取消"
                  ok-type="danger"
                  @confirm="handleDeleteDoc(selectedDoc.id)"
                >
                  <a-button danger type="text">删除</a-button>
                </a-popconfirm>
              </a-space>
            </div>

            <!-- 全文摘要 -->
            <div v-if="selectedDoc.analysis?.summary" class="summary-box">
              <span class="summary-label">内容解析摘要：</span>
              <p class="summary-text">{{ selectedDoc.analysis.summary }}</p>
            </div>
          </div>

          <!-- 结构化多维展示 Tab -->
          <div class="analysis-tabs-wrap">
            <a-tabs v-model:activeKey="activeTab" type="card">
              <!-- Tab 1: 分集与镜头 -->
              <a-tab-pane key="episodes">
                <template #tab>
                  <span class="tab-label">
                    <Film :size="15" />
                    分集与镜头 ({{ selectedDoc.analysis?.episodes?.length || 0 }}集 / {{ totalShotsCount }}镜)
                  </span>
                </template>

                <div v-if="!selectedDoc.analysis?.episodes?.length" class="empty-sub-tab">
                  暂未识别到标准分集信息（可参考「标准剧本规范」采用「# 第X集」及「### 镜头X」编排）
                </div>

                <div v-else class="episodes-container">
                  <a-collapse v-model:activeKey="activeEpisodeKeys" :bordered="false" class="episodes-collapse">
                    <a-collapse-panel
                      v-for="ep in selectedDoc.analysis.episodes"
                      :key="String(ep.episode_num)"
                    >
                      <template #header>
                        <div class="ep-collapse-header">
                          <div class="ep-title-group">
                            <span class="ep-badge">第 {{ ep.episode_num }} 集</span>
                            <span class="ep-main-title">{{ ep.title }}</span>
                            <a-tag color="blue">{{ ep.shots_count || ep.shots?.length || 0 }} 个分镜</a-tag>
                          </div>
                          <span v-if="ep.summary" class="ep-header-summary" :title="ep.summary">
                            {{ ep.summary }}
                          </span>
                        </div>
                      </template>

                      <!-- 镜头卡片流 -->
                      <div class="shots-grid">
                        <div
                          v-for="shot in ep.shots"
                          :key="shot.shot_num"
                          class="shot-card"
                        >
                          <div class="shot-card-header">
                            <span class="shot-badge">镜头 {{ shot.shot_num }}</span>
                            <h4 class="shot-title">{{ shot.title }}</h4>
                            <a-tag v-if="shot.camera" color="purple" size="small">{{ shot.camera }}</a-tag>
                          </div>

                          <div class="shot-meta-rows">
                            <!-- 场景 -->
                            <div v-if="shot.scene" class="shot-meta-row">
                              <span class="meta-lbl"><MapPin :size="13" /> 场景：</span>
                              <span class="meta-val scene-val">{{ shot.scene }}</span>
                            </div>

                            <!-- 人物 -->
                            <div v-if="shot.characters?.length" class="shot-meta-row">
                              <span class="meta-lbl"><Users :size="13" /> 人物：</span>
                              <div class="tags-cluster">
                                <a-tag
                                  v-for="c in shot.characters"
                                  :key="c"
                                  color="purple"
                                  size="small"
                                >
                                  {{ c }}
                                </a-tag>
                              </div>
                            </div>

                            <!-- 道具 -->
                            <div v-if="shot.props?.length" class="shot-meta-row">
                              <span class="meta-lbl"><Package :size="13" /> 道具：</span>
                              <div class="tags-cluster">
                                <a-tag
                                  v-for="p in shot.props"
                                  :key="p"
                                  color="orange"
                                  size="small"
                                >
                                  {{ p }}
                                </a-tag>
                              </div>
                            </div>

                            <!-- 动作 -->
                            <div v-if="shot.action" class="shot-meta-row">
                              <span class="meta-lbl"><Activity :size="13" /> 动作：</span>
                              <span class="meta-val">{{ shot.action }}</span>
                            </div>

                            <!-- 台词 -->
                            <div v-if="shot.dialogue" class="shot-meta-row dialogue-row">
                              <span class="meta-lbl"><MessageSquareQuote :size="13" /> 台词：</span>
                              <div class="dialogue-bubble">{{ shot.dialogue }}</div>
                            </div>

                            <!-- 音效与字幕 -->
                            <div v-if="shot.audio || shot.subtitle" class="shot-meta-row audio-row">
                              <span v-if="shot.audio" class="audio-text">🔊 {{ shot.audio }}</span>
                              <span v-if="shot.subtitle" class="subtitle-text">💬 {{ shot.subtitle }}</span>
                            </div>

                            <!-- AI 生图提示词 -->
                            <div v-if="shot.visual_prompt" class="shot-prompt-box">
                              <div class="prompt-head">
                                <span><Sparkles :size="12" /> AI 画面提示词 (Prompt)</span>
                                <a-button type="link" size="small" class="copy-link" @click="copyText(shot.visual_prompt)">
                                  复制
                                </a-button>
                              </div>
                              <p class="prompt-text">{{ shot.visual_prompt }}</p>
                            </div>
                          </div>
                        </div>
                      </div>
                    </a-collapse-panel>
                  </a-collapse>
                </div>
              </a-tab-pane>

              <!-- Tab 2: 识别人物 -->
              <a-tab-pane key="characters">
                <template #tab>
                  <span class="tab-label">
                    <Users :size="15" />
                    识别人物 ({{ selectedDoc.analysis?.characters?.length || 0 }})
                  </span>
                </template>

                <div v-if="!selectedDoc.analysis?.characters?.length" class="empty-sub-tab">
                  未识别到人物角色
                </div>

                <div v-else class="cards-grid">
                  <div
                    v-for="char in selectedDoc.analysis.characters"
                    :key="char.name"
                    class="character-card"
                  >
                    <div class="char-header">
                      <div class="char-avatar" :style="getCharGradient(char.name)">
                        {{ char.name.slice(0, 1) }}
                      </div>
                      <div class="char-title-meta">
                        <div class="char-name-row">
                          <h4 class="char-name">{{ char.name }}</h4>
                          <a-tag color="blue">{{ char.role || char.role_position }}</a-tag>
                          <a-tag v-if="char.role_position" color="purple" size="small">{{ char.role_position }}</a-tag>
                          <a-tag v-if="char.age_group || char.age" color="cyan" size="small">{{ char.age_group || char.age }}</a-tag>
                          <a-tag :color="char.gender === '女' ? 'magenta' : 'geekblue'" size="small">
                            {{ char.gender || '未指定' }}
                          </a-tag>
                        </div>
                        <span v-if="formatAliases(char.aliases)" class="shots-stat">别名：{{ formatAliases(char.aliases) }}</span>
                        <span class="shots-stat">出现分镜：{{ char.shots_count || 0 }} 次</span>
                      </div>
                    </div>

                    <!-- 固定道具 -->
                    <div v-if="char.fixed_props?.length" class="char-props-section">
                      <span class="prop-lbl"><Package :size="13" /> 固定道具：</span>
                      <div class="tags-cluster">
                        <a-tag v-for="fp in char.fixed_props" :key="fp" color="orange">
                          {{ fp }}
                        </a-tag>
                      </div>
                    </div>

                    <!-- 外观设定 -->
                    <div class="char-desc-section">
                      <p class="char-desc">{{ char.description }}</p>
                    </div>

                    <div v-if="char.face_prompt" class="char-prompt-section">
                      <div class="prompt-head">
                        <span><Sparkles :size="12" /> 面部提示词</span>
                        <a-button type="link" size="small" class="copy-link" @click="copyText(char.face_prompt)">
                          复制
                        </a-button>
                      </div>
                      <p class="prompt-text">{{ char.face_prompt }}</p>
                    </div>

                    <div v-if="char.art_style_id || char.visual_style || char.body_type" class="char-props-section">
                      <span class="prop-lbl">画风设定：</span>
                      <div class="tags-cluster">
                        <a-tag v-if="char.art_style_id" color="green">{{ char.art_style_id }}</a-tag>
                        <a-tag v-if="char.visual_style">{{ char.visual_style }}</a-tag>
                        <a-tag v-if="char.body_type">{{ char.body_type }}</a-tag>
                      </div>
                    </div>

                    <!-- 人物一致性提示词 -->
                    <div v-if="char.visual_prompt" class="char-prompt-section">
                      <div class="prompt-head">
                        <span><Sparkles :size="12" /> 一致性生图 Prompt</span>
                        <a-button type="link" size="small" class="copy-link" @click="copyText(char.visual_prompt)">
                          复制
                        </a-button>
                      </div>
                      <p class="prompt-text">{{ char.visual_prompt }}</p>
                    </div>
                  </div>
                </div>
              </a-tab-pane>

              <!-- Tab 3: 规划场景 -->
              <a-tab-pane key="scenes">
                <template #tab>
                  <span class="tab-label">
                    <MapPin :size="15" />
                    规划场景 ({{ selectedDoc.analysis?.scenes?.length || 0 }})
                  </span>
                </template>

                <div v-if="!selectedDoc.analysis?.scenes?.length" class="empty-sub-tab">
                  未识别到规划场景
                </div>

                <div v-else class="cards-grid">
                  <div
                    v-for="sc in selectedDoc.analysis.scenes"
                    :key="sc.name"
                    class="scene-card"
                  >
                    <div class="scene-header">
                      <div class="scene-icon-wrap">
                        <MapPin :size="20" />
                      </div>
                      <div class="scene-meta">
                        <h4 class="scene-name">{{ sc.name }}</h4>
                        <div class="scene-badges">
                          <a-tag :color="sc.type === '固定场景' || sc.type === '固定场景库' ? 'green' : 'blue'">
                            {{ sc.type || '拍摄场地' }}
                          </a-tag>
                          <span v-if="sc.shots_count" class="shots-stat">引用 {{ sc.shots_count }} 镜头</span>
                        </div>
                      </div>
                    </div>

                    <p class="scene-desc">{{ sc.description }}</p>

                    <!-- 场景元素 -->
                    <div v-if="sc.elements?.length" class="scene-elements">
                      <span class="elem-lbl">陈设元素：</span>
                      <div class="tags-cluster">
                        <a-tag v-for="el in sc.elements" :key="el" color="default" size="small">
                          {{ el }}
                        </a-tag>
                      </div>
                    </div>
                  </div>
                </div>
              </a-tab-pane>

              <!-- Tab 4: 关键道具 -->
              <a-tab-pane key="props">
                <template #tab>
                  <span class="tab-label">
                    <Package :size="15" />
                    关键道具 ({{ selectedDoc.analysis?.props?.length || 0 }})
                  </span>
                </template>

                <div v-if="!selectedDoc.analysis?.props?.length" class="empty-sub-tab">
                  未识别到道具要素
                </div>

                <div v-else class="props-grid">
                  <div
                    v-for="pr in selectedDoc.analysis.props"
                    :key="pr.name"
                    class="prop-card"
                  >
                    <div class="prop-card-top">
                      <div class="prop-icon-wrap">
                        <Package :size="18" />
                      </div>
                      <div class="prop-name-box">
                        <h4 class="prop-name">{{ pr.name }}</h4>
                        <a-tag :color="getPropTagColor(pr.kind)" size="small">{{ pr.kind }}</a-tag>
                      </div>
                    </div>
                    <div class="prop-card-bottom">
                      <div class="prop-info-item">
                        <span class="lbl">关联角色/场景：</span>
                        <span class="val">{{ pr.related_character || '场景共用' }}</span>
                      </div>
                      <div class="prop-info-item">
                        <span class="lbl">出现频次：</span>
                        <span class="val count-val">{{ pr.count || 1 }} 次</span>
                      </div>
                    </div>
                  </div>
                </div>
              </a-tab-pane>

              <!-- Tab 5: 视觉与全局设定 -->
              <a-tab-pane key="globals">
                <template #tab>
                  <span class="tab-label">
                    <Sparkles :size="15" />
                    视觉与全局设定
                  </span>
                </template>

                <div class="globals-layout">
                  <!-- 视频定位 -->
                  <div class="global-card">
                    <div class="global-card-title">
                      <Film :size="16" />
                      <span>视频定位与世界观</span>
                    </div>
                    <div class="positioning-list">
                      <div v-if="selectedDoc.analysis?.positioning?.genre" class="pos-item">
                        <span class="k">作品类型：</span>
                        <span class="v">{{ selectedDoc.analysis.positioning.genre }}</span>
                      </div>
                      <div v-if="selectedDoc.analysis?.positioning?.worldview" class="pos-item">
                        <span class="k">世界观设定：</span>
                        <span class="v">{{ selectedDoc.analysis.positioning.worldview }}</span>
                      </div>
                      <div v-if="selectedDoc.analysis?.positioning?.duration_per_episode" class="pos-item">
                        <span class="k">单集时长：</span>
                        <span class="v">{{ selectedDoc.analysis.positioning.duration_per_episode }}</span>
                      </div>
                      <div v-if="selectedDoc.analysis?.positioning?.shots_per_episode" class="pos-item">
                        <span class="k">镜头规划：</span>
                        <span class="v">{{ selectedDoc.analysis.positioning.shots_per_episode }}</span>
                      </div>
                      <div v-if="selectedDoc.analysis?.positioning?.main_storyline" class="pos-item">
                        <span class="k">主线剧情：</span>
                        <span class="v storyline-v">{{ selectedDoc.analysis.positioning.main_storyline }}</span>
                      </div>
                    </div>
                  </div>

                  <!-- 统一视觉风格 -->
                  <div class="global-card">
                    <div class="global-card-title">
                      <Sparkles :size="16" />
                      <span>统一视觉风格基调</span>
                    </div>
                    <div v-if="selectedDoc.analysis?.visual_style?.description" class="style-quote">
                      {{ selectedDoc.analysis.visual_style.description }}
                    </div>
                    <div v-if="selectedDoc.analysis?.visual_style?.prohibited" class="prohibited-box">
                      <span class="prohibited-title">⚠️ 禁止与负向提示词：</span>
                      <p class="prohibited-text">{{ selectedDoc.analysis.visual_style.prohibited }}</p>
                    </div>
                  </div>

                  <!-- 制作建议 -->
                  <div v-if="selectedDoc.analysis?.production_advice" class="global-card full-width">
                    <div class="global-card-title">
                      <BookOpen :size="16" />
                      <span>视频制作建议与控制策略</span>
                    </div>
                    <p class="advice-text">{{ selectedDoc.analysis.production_advice }}</p>
                  </div>
                </div>
              </a-tab-pane>

              <!-- Tab 6: 剧本原文 -->
              <a-tab-pane key="raw">
                <template #tab>
                  <span class="tab-label">
                    <FileText :size="15" />
                    剧本原文预览
                  </span>
                </template>
                <div class="script-preview-card">
                  <div class="preview-actions">
                    <span class="preview-info">全文共 {{ selectedDoc.raw_text?.length || 0 }} 字符</span>
                    <a-button size="small" @click="copyText(selectedDoc.raw_text)">复制全文</a-button>
                  </div>
                  <pre class="script-text-box">{{ selectedDoc.raw_text }}</pre>
                </div>
              </a-tab-pane>
            </a-tabs>
          </div>
        </div>
      </div>
    </a-spin>

    <!-- 导入剧本弹窗 -->
    <a-modal
      v-model:open="importModalVisible"
      title="导入剧本文档 (支持标准分镜格式)"
      :confirm-loading="importing"
      ok-text="确认并深度解析"
      cancel-text="取消"
      :width="720"
      destroy-on-close
      @ok="handleImportSubmit"
    >
      <a-form layout="vertical">
        <div class="quick-fill-bar">
          <span class="quick-lbl">测试快捷操作：</span>
          <a-button type="dashed" size="small" @click="fillSampleData">
            ✨ 一键填入《寒门硕士》官方标准分镜范例
          </a-button>
        </div>

        <a-form-item label="剧本标题 / 作品名称" required>
          <a-input v-model:value="importForm.filename" placeholder="例如：《寒门硕士：穿越古代逆袭记》第一季" />
        </a-form-item>

        <a-form-item label="Markdown 文件">
          <div class="script-file-picker">
            <a-upload accept=".md,.markdown,text/markdown" :show-upload-list="false" :before-upload="handleScriptFile">
              <a-button><template #icon><FileText :size="14" /></template>选择 .md 文件</a-button>
            </a-upload>
            <span v-if="selectedScriptFileName" class="script-file-name">{{ selectedScriptFileName }}</span>
            <span v-else class="script-file-hint">选择后会自动读取到下方编辑区</span>
          </div>
        </a-form-item>

        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="骨架模板">
              <a-select v-model:value="importForm.spine_template">
                <a-select-option value="drama">精品短剧 (分镜/镜头/人物/道具标准结构)</a-select-option>
                <a-select-option value="narrated">解说剧 (画外旁白与画面)</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="视觉风格预设">
              <a-select v-model:value="importForm.visual_style">
                <a-select-option value="chinese_period_drama">写实古装剧 (宋式古典电影感)</a-select-option>
                <a-select-option value="anime">动漫日漫二次元</a-select-option>
                <a-select-option value="guoman_fantasy">3D玄幻国漫</a-select-option>
                <a-select-option value="realistic">写实现代都市</a-select-option>
                <a-select-option value="post_apocalyptic">废土科幻末日</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="分镜剧本正文内容 (支持直接粘贴 Markdown / 文本)" required>
          <a-textarea
            v-model:value="importForm.raw_text"
            placeholder="粘贴剧本文档，支持包含【视频定位、人物设定、视觉风格、分集分镜、固定场景库、人物一致性提示词】的标准格式..."
            :rows="12"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 剧本规范说明弹窗 -->
    <a-modal v-model:open="formatModalVisible" title="标准短剧分镜剧本编排规范" :footer="null" :width="700">
      <div class="format-guide">
        <p class="guide-lead">
          系统支持标准 Markdown 结构化剧本导入，能自动区分<strong>镜头、人物、道具、场景</strong>以及生成 <strong>AI Prompt</strong>：
        </p>
        <div class="guide-sections">
          <div class="guide-sec">
            <h5>1. 主要人物固定设定</h5>
            <pre class="guide-pre">
## 一、主要人物固定设定
### 沈砚——男主
17岁古代少年；清瘦高挑；剑眉；黑色长发、少年发髻；青灰粗布长衫。固定道具：旧木书箱、破旧古书、毛笔、砚台、宣纸。
            </pre>
          </div>

          <div class="guide-sec">
            <h5>2. 分集与分镜编排格式（兼容列表式与紧凑分号式）</h5>
            <pre class="guide-pre">
# 第1集：硕士穿越，醒来成了穷小子
**剧情：** 现代硕士意外穿越，醒来成为贫苦农家少年。

### 镜头1｜现代图书馆
- 人物：现代26岁沈砚
- 场景：现代大学图书馆深夜
- 道具：古籍、电脑、台灯、笔记本
- 动作：整理古籍、揉眼
- 镜头：中近景缓慢推进
- 台词：“这篇古文，到底是谁写的……”
- 提示词：现代大学图书馆深夜，年轻男硕士研究生研究古代文献，桌面古籍和电脑，暖黄台灯，电影感写实摄影。
            </pre>
          </div>

          <div class="guide-sec">
            <h5>3. 固定场景库与人物一致性提示词</h5>
            <pre class="guide-pre">
# 三、固定场景库
## 沈家
破旧茅草屋、土墙、木床、破木桌、陶碗、旧木箱、米缸、柴火。

# 四、人物一致性提示词
**沈砚：** 17岁中国古代少年，清瘦高挑，清秀脸庞，剑眉，沉静眼神，浅青灰色粗布长衫，气质沉稳聪慧。
            </pre>
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  Plus,
  FileText,
  Users,
  MapPin,
  Film,
  Package,
  Sparkles,
  BookOpen,
  Activity,
  MessageSquareQuote,
} from 'lucide-vue-next'
import {
  listDocuments,
  createDocument,
  deleteDocument,
  transferAssetsFromDoc,
  transferEpisodesFromDoc,
} from '../../api/projects'

const props = defineProps({
  projectId: { type: String, required: true },
})
const emit = defineEmits(['assets-transferred', 'episodes-transferred'])

const documents = ref([])
const selectedDoc = ref(null)
const loading = ref(false)
const importing = ref(false)
const transferring = ref(false)
const transferringEp = ref(false)
const importModalVisible = ref(false)
const formatModalVisible = ref(false)
const selectedScriptFileName = ref('')
const activeTab = ref('episodes')
const activeEpisodeKeys = ref(['1'])

const importForm = ref({
  filename: '',
  spine_template: 'drama',
  visual_style: 'chinese_period_drama',
  raw_text: '',
  input_mode: 'paste',
})

// 计算所有镜头的总数
const totalShotsCount = computed(() => {
  if (!selectedDoc.value?.analysis?.episodes) return 0
  return selectedDoc.value.analysis.episodes.reduce((acc, ep) => acc + (ep.shots?.length || 0), 0)
})

function getPropTagColor(kind) {
  if (kind === '人物固定道具') return 'orange'
  if (kind === '场景陈设道具') return 'cyan'
  return 'blue'
}

function getCharGradient(name) {
  const gradients = [
    'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
    'linear-gradient(135deg, #3b82f6 0%, #2dd4bf 100%)',
    'linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)',
    'linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)',
    'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)',
  ]
  const charCode = (name || '').charCodeAt(0) || 0
  return { background: gradients[charCode % gradients.length] }
}

function formatAliases(value) {
  if (Array.isArray(value)) return value.filter(Boolean).join('、')
  return String(value || '').trim()
}

function copyText(txt) {
  if (!txt) return
  navigator.clipboard.writeText(txt).then(() => {
    message.success('已复制到剪贴板')
  }).catch(() => {
    message.info('请手动复制内容')
  })
}

async function loadDocs() {
  loading.value = true
  try {
    const res = await listDocuments(props.projectId)
    documents.value = res || []
    if (documents.value.length > 0) {
      selectedDoc.value = documents.value[0]
      activeEpisodeKeys.value = ['1']
    } else {
      selectedDoc.value = null
    }
  } catch (err) {
    message.error('加载文档列表失败')
  } finally {
    loading.value = false
  }
}

function openImportModal() {
  importForm.value = {
    filename: '',
    spine_template: 'drama',
    visual_style: 'chinese_period_drama',
    raw_text: '',
    input_mode: 'paste',
  }
  selectedScriptFileName.value = ''
  importModalVisible.value = true
}

function handleScriptFile(file) {
  const filename = String(file?.name || '')
  if (!/\.(md|markdown)$/i.test(filename)) {
    message.warning('请选择 Markdown 文件（.md 或 .markdown）')
    return false
  }
  const reader = new FileReader()
  reader.onload = () => {
    const text = typeof reader.result === 'string' ? reader.result : ''
    if (!text.trim()) {
      message.warning('所选 Markdown 文件内容为空')
      return
    }
    importForm.value.raw_text = text
    importForm.value.filename = filename.replace(/\.(md|markdown)$/i, '')
    importForm.value.input_mode = 'file'
    selectedScriptFileName.value = filename
    message.success(`已读取 ${filename}`)
  }
  reader.onerror = () => message.error('读取 Markdown 文件失败')
  reader.readAsText(file, 'utf-8')
  return false
}

async function handleImportSubmit() {
  if (!importForm.value.raw_text.trim()) {
    message.warning('请填写或粘贴剧本正文')
    return
  }
  importing.value = true
  try {
    await createDocument(props.projectId, {
      ...importForm.value,
      input_mode: importForm.value.input_mode || 'paste',
    })
    message.success('剧本文档导入并解析成功，已拆解镜头、人物、道具与场景')
    importModalVisible.value = false
    await loadDocs()
  } catch (err) {
    message.error(err?.response?.data?.detail || '导入失败')
  } finally {
    importing.value = false
  }
}

async function handleDeleteDoc(id) {
  try {
    await deleteDocument(props.projectId, id)
    message.success('文档已删除')
    await loadDocs()
  } catch (err) {
    message.error('删除失败')
  }
}

async function handleTransferAssets() {
  if (!selectedDoc.value) return
  transferring.value = true
  try {
    const res = await transferAssetsFromDoc(props.projectId, selectedDoc.value.id)
    const transferred = res.transferred || {}
    message.success(`已转入资产库：${transferred.characters || 0} 角色、${transferred.scenes || 0} 场景、${transferred.props || 0} 道具。请到资产库选中条目后点击「大模型补全」`)
    emit('assets-transferred')
  } catch (err) {
    message.error(err?.response?.data?.detail || '转入资产库失败')
  } finally {
    transferring.value = false
  }
}

async function handleTransferEpisodes() {
  if (!selectedDoc.value) return
  transferringEp.value = true
  try {
    const res = await transferEpisodesFromDoc(props.projectId, selectedDoc.value.id)
    message.success(`已同步至剧集工坊：共 ${res.transferred_episodes} 集、${res.transferred_shots} 个分镜`)
    emit('episodes-transferred')
  } catch (err) {
    message.error(err?.response?.data?.detail || '同步至剧集工坊失败')
  } finally {
    transferringEp.value = false
  }
}

// 快速填入官方范例文本
function fillSampleData() {
  importForm.value.filename = '《寒门硕士：穿越古代逆袭记》第一季——AI视频详细分镜版'
  importForm.value.spine_template = 'drama'
  importForm.value.visual_style = 'chinese_period_drama'
  importForm.value.raw_text = SAMPLE_SCRIPT
}

async function quickImportSample() {
  importing.value = true
  try {
    await createDocument(props.projectId, {
      filename: '《寒门硕士：穿越古代逆袭记》第一季——AI视频详细分镜版',
      spine_template: 'drama',
      visual_style: 'chinese_period_drama',
      raw_text: SAMPLE_SCRIPT,
    })
    message.success('已导入《寒门硕士》标准分镜剧本并完成结构化解析')
    await loadDocs()
  } catch (err) {
    message.error('导入范例失败')
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  loadDocs()
})

const SAMPLE_SCRIPT = `# 《寒门硕士：穿越古代逆袭记》第一季——AI视频详细分镜版

## 视频定位
- 类型：古装 / 穿越 / 寒门逆袭 / 科举 / 爽文
- 世界观：架空“大晟王朝”
- 单集：约30秒
- 每集：6个镜头，每镜头约5秒
- 主线：现代硕士 → 穿越寒门 → 进入陆家 → 富家少爷伴读 → 夫子看中 → 免费入学 → 替少爷写诗 → 一诗成名

## 一、主要人物固定设定

### 沈砚——男主
17岁古代少年；清瘦高挑；清秀脸庞；剑眉；沉静眼神；黑色长发、少年发髻；前期穿洗得发白的青灰粗布长衫、旧布鞋；后期换浅青色长衫。气质贫寒但不卑微、聪明沉稳。固定道具：旧木书箱、破旧古书、毛笔、砚台、宣纸。

### 陆承安——富家少爷
16岁；白净少年脸；浅蓝锦袍；整齐束发；腰佩玉佩；贪玩骄傲但本性不坏。固定道具：折扇、玉佩、书卷。

### 林夫子——贵人
55岁；灰白胡须；深灰长袍；儒巾；严肃锐利；严厉、公正、爱才。固定道具：戒尺、《论语》、毛笔、砚台、木质讲案。

### 苏婉——女主
17岁；清秀温婉；纤细；黑色长发；淡青古装长裙；聪慧安静、喜欢读书。固定道具：书卷、团扇、绣花香囊。

### 周景明——竞争对手
18岁；修长英俊；深蓝锦袍；束发；腰佩玉佩；家境优越、自幼读书；性格骄傲，前期看不起寒门读书人。

## 二、统一视觉风格
> 中国古代架空王朝，大晟朝，写实古装电影风格，真实人物皮肤质感，真实布料纹理，柔和自然光，青砖黛瓦，宋式审美，低饱和古典色调，浅景深，电影构图，人物面部稳定，服装保持一致，写实而非动漫。

禁止：现代汽车、电线杆、手机、手表、拉链、现代家具、现代发型、西式建筑。

---

# 第1集：硕士穿越，醒来成了穷小子

**剧情：** 现代硕士沈砚意外穿越，醒来成为贫苦农家少年。

### 镜头1｜现代图书馆
- 人物：现代26岁沈砚
- 场景：现代大学图书馆深夜
- 道具：古籍、电脑、台灯、笔记本
- 动作：整理古籍、揉眼
- 镜头：中近景缓慢推进
- 台词：“这篇古文，到底是谁写的……”
- 提示词：现代大学图书馆深夜，年轻男硕士研究生研究古代文献，桌面古籍和电脑，暖黄台灯，电影感写实摄影。

### 镜头2｜穿越
- 场景：图书馆
- 道具：古籍
- 动作：古书掉落，沈砚伸手接，突然白光
- 镜头：快速推进→白光
- 音效：书落地、风声

### 镜头3｜破屋醒来
- 人物：沈砚、母亲
- 场景：破旧茅屋
- 道具：木床、陶碗、旧被褥
- 动作：沈砚猛然睁眼，看房顶
- 台词：“这里……是什么地方？”

### 镜头4｜母亲出现
- 动作：母亲端破陶碗进屋
- 台词：“砚儿，你终于醒了。”

### 镜头5｜家徒四壁
- 场景：土墙、木床、木桌、缺口陶碗
- 动作：沈砚环顾四周，表情从疑惑变震惊

### 镜头6｜最后半袋米
- 动作：母亲打开米缸，只有少量米
- 台词：“最后半袋米，也快吃完了。”
- 字幕：**堂堂硕士，穿越第一天，先解决吃饭问题。**

# 第2集：硕士的第一桶金

**剧情：** 沈砚利用知识解决村中灌溉问题，获得第一笔钱。

### 镜头1｜村口争论
人物：沈砚、村民；场景：村口田地；道具：农具、竹筐、木车；村民因灌溉争论。

### 镜头2｜沈砚开口
沈砚听完说道：“如果把水渠从这里引过去，不但能解决田里的水，还能少花一半工。”

### 镜头3｜画水渠
沈砚蹲地，用树枝画路线；俯拍树枝与泥地。

### 镜头4｜水渠成功
村民照做，水流进入田地，众人震惊。

### 镜头5｜众人询问
村民：“沈家小子，你什么时候懂这些了？”沈砚：“书上看的。”

### 镜头6｜第一桶金
沈砚拿钱回家，买回一袋粮食；母亲眼眶微红。沈砚：“至少，今天不用饿肚子了。”

# 第3集：进入陆家，当富家少爷伴读

### 镜头1｜陆家大门
青砖大宅、朱红大门、石狮；沈砚背旧书箱站门外。

### 镜头2｜管家考察
管家：“识字？”沈砚：“识一些。”

### 镜头3｜第一次见陆承安
陆承安穿浅蓝锦袍，坐石桌摇折扇，打量沈砚。

### 镜头4｜富少爷嘲笑
陆承安：“你这么穷，也读过书？”

### 镜头5｜第一次反击
沈砚：“读书，不看家里有几亩田。”陆承安脸色微变。

### 镜头6｜陆老爷观察
陆老爷远处看着：“这个孩子……倒是不卑不亢。”
结尾：沈砚正式成为陆承安伴读。

# 第4集：伴读竟然比少爷还会读书

### 镜头1｜陆家书房
沈砚、陆承安；书卷、砚台、毛笔；陆承安趴桌打瞌睡。

### 镜头2｜少爷求教
陆承安：“这文章到底是什么意思？”沈砚拿起书。

### 镜头3｜沈砚讲解
沈砚用简单方式解释，陆承安逐渐听懂。

### 镜头4｜私塾课堂
林夫子提问，陆承安答不上来，沈砚小声提醒。

### 镜头5｜夫子发现
林夫子突然转头：“沈砚，你来说。”所有学生看向沈砚。

### 镜头6｜惊艳回答
沈砚回答后，林夫子问：“你以前在哪里读书？”沈砚：“回夫子，学生没有正式读过书。”林夫子震惊。

# 第5集：夫子破格，免费入学

### 镜头1｜考经义
林夫子拿《论语》：“解释这一句。”沈砚回答。

### 镜头2｜考文章
林夫子：“若让你写一篇文章，如何立意？”沈砚认真回答。

### 镜头3｜众人震惊
周景明第一次认真看向沈砚。

### 镜头4｜夫子收徒
林夫子：“你可愿意拜我为师？”沈砚愣住。

### 镜头5｜说出难处
沈砚：“学生家贫，交不起束脩。”

### 镜头6｜免费入学
林夫子：“有才之人，不该因贫寒而废学。你的束脩，免了。”沈砚眼神微红。

# 第6集：替少爷写诗

### 镜头1｜书房求助
陆承安急得踱步：“父亲让我今日必须作诗。”

### 镜头2｜沈砚回应
沈砚：“那就自己写。”陆承安：“我要是会，还找你干什么？”

### 镜头3｜执笔
沈砚拿毛笔沉思。

### 镜头4｜写诗
特写笔尖、墨汁、宣纸。

### 镜头5｜少爷震惊
陆承安：“这是你写的？”沈砚：“记住，是你自己写的。”

### 镜头6｜文会
陆承安念诗，众人安静；名士：“好诗！此诗何人所作？”陆承安犹豫，画面切黑。

# 第7集：寒门才子，一诗成名

### 镜头1｜揭晓作者
陆承安：“我的伴读，沈砚。”众人哗然。

### 镜头2｜沈砚出现
沈砚站远处，众人打量他的破旧衣服。

### 镜头3｜议论
“一个伴读？”“他能写出这种诗？”

### 镜头4｜周景明挑战
周景明：“明日，我与你比试。”

### 镜头5｜沈砚接受
沈砚：“可以。”

### 镜头6｜旁白
周景明离开。旁白：“他不知道，自己从这一刻开始，已经走进了真正的读书人世界。”

# 第8集：才华带来的麻烦

### 镜头1｜茶楼议论
几个读书人在县城茶楼议论沈砚。

### 镜头2｜质疑
“一个穷伴读，怎么可能写出这种诗？”

### 镜头3｜诬陷
“我看，八成是偷来的。”

### 镜头4｜陆承安愤怒
陆承安：“他们凭什么说你？”沈砚：“因为他们不相信。”

### 镜头5｜证明
沈砚拿原稿，通过纸张、墨迹、书写习惯等细节证明文章为自己完成。

### 镜头6｜夫子评价
林夫子：“有才而不浮，有志而不狂。”沈砚拱手。林夫子：“继续读书。”

# 第9集：真正的大人物

### 镜头1｜大型文会
亭台、水榭、竹林、石桥，众多读书人聚集。

### 镜头2｜京城大儒
大儒出现，众人行礼，沈砚站在人群后。

### 镜头3｜被点名
大儒：“你就是沈砚？”沈砚：“学生正是。”

### 镜头4｜提出难题
大儒提出难题，其他学子沉默。

### 镜头5｜沈砚作答
沈砚思考后：“学生认为，此题真正的问题，并不在题面。”众人震惊。

### 镜头6｜乡试邀请
大儒：“明年乡试，你可敢参加？”沈砚：“学生，敢。”

# 第10集：寒门少年，踏上科举路

### 镜头1｜回到破屋
沈砚把赚来的钱放在桌上。

### 镜头2｜母亲拒收
母亲：“这是你的。”沈砚：“给家里买粮。”母亲：“你拿去读书。”

### 镜头3｜沈砚动容
沈砚沉默片刻，郑重点头。

### 镜头4｜陆家门口
陆承安背书箱：“沈砚，乡试一起去！”沈砚：“好。”

### 镜头5｜苏婉送书
苏婉递书：“愿你此去，得偿所愿。”沈砚：“多谢。”

### 镜头6｜第一季结尾
清晨，沈砚背书箱走在古道上，群山、晨雾、古树；镜头高空拉远。旁白：“那一年，他还只是一个吃不饱饭的寒门少年。没人知道，这个少年未来会走到哪里。”

大字：**乡试，开始。**

# 三、固定场景库

## 沈家
破旧茅草屋、土墙、木床、破木桌、陶碗、旧木箱、米缸、柴火。

## 陆家
青砖灰瓦大宅院、朱红木门、石狮、木质回廊、假山、水池、亭台。

## 私塾
木质讲案、书架、宣纸、砚台、毛笔、学生木桌、竹简。

## 文会
江南园林、水榭、竹林、石桥、亭台、灯笼、曲水。

## 古道
青石路、群山、晨雾、古树、竹林、远山。

# 四、人物一致性提示词

**沈砚：** 17岁中国古代少年，清瘦高挑，清秀脸庞，剑眉，沉静眼神，黑色长发，少年发髻，浅青灰色粗布长衫，旧布鞋，贫寒但不卑微，气质沉稳聪慧。

**陆承安：** 16岁中国古代富家少年，白净脸庞，少年感，浅蓝色锦袍，整齐束发，腰佩玉佩，手持折扇，富贵气质，略带骄傲。

**林夫子：** 55岁中国古代老夫子，灰白胡须，深灰色长袍，儒巾，严肃面容，锐利眼神，手持戒尺。

**苏婉：** 17岁中国古代少女，清秀温婉，纤细身材，黑色长发，淡青色古装长裙，清雅气质，手持书卷。

**周景明：** 18岁中国古代年轻书生，修长身材，英俊面容，深蓝色锦袍，束发，腰佩玉佩，气质骄傲。

# 五、视频制作建议

每个镜头控制在5秒左右。建议“1个镜头=1条视频”，生成后再剪辑成约30秒一集。这样更容易控制人物一致性、场景一致性、动作、台词和节奏。`
</script>

<style scoped>
.content-library-pane {
  padding: 4px 0;
}

.sub-pane-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
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

.primary-btn {
  background: linear-gradient(135deg, #7047f6 0%, #8b5cf6 100%);
  border: none;
}

.empty-doc-box {
  background: #ffffff;
  border: 1px dashed rgba(0, 0, 0, 0.1);
  border-radius: 12px;
  padding: 64px 20px;
  text-align: center;
}

.empty-icon-wrap {
  width: 64px;
  height: 64px;
  margin: 0 auto 16px;
  border-radius: 16px;
  background: rgba(112, 71, 246, 0.08);
  display: grid;
  place-items: center;
  color: #7047f6;
}

.content-layout {
  display: flex;
  gap: 20px;
  align-items: flex-start;
}

.doc-list-sidebar {
  width: 250px;
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px;
  padding: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  flex-shrink: 0;
}

.doc-list-header {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  padding: 4px 8px 10px;
  border-bottom: 1px solid #f3f4f6;
  margin-bottom: 8px;
}

.doc-items-scroll {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 620px;
  overflow-y: auto;
}

.doc-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  background: #fafafa;
  border: 1px solid transparent;
}

.doc-item:hover {
  background: #f3f4f6;
}

.doc-item.active {
  background: rgba(112, 71, 246, 0.06);
  border-color: rgba(112, 71, 246, 0.3);
}

.doc-item-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 6px;
}

.doc-icon {
  color: #7047f6;
  flex-shrink: 0;
}

.doc-item-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  color: #9ca3af;
}

.doc-detail-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.detail-top-card {
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px;
  padding: 18px 22px;
}

.detail-top-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}

.detail-title {
  font-size: 18px;
  font-weight: 700;
  color: #111827;
  margin: 0 0 8px;
}

.detail-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.char-count {
  font-size: 12px;
  color: #9ca3af;
}

.transfer-btn {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  border: none;
}

.sync-ep-btn {
  background: #ffffff;
  color: #7047f6;
  border-color: #7047f6;
}
.sync-ep-btn:hover {
  background: rgba(112, 71, 246, 0.06);
}

.summary-box {
  background: #f8fafc;
  border-left: 3px solid #7047f6;
  padding: 10px 14px;
  border-radius: 0 8px 8px 0;
  font-size: 13px;
}

.summary-label {
  font-weight: 600;
  color: #374151;
}

.summary-text {
  margin: 4px 0 0;
  color: #4b5563;
  line-height: 20px;
}

.analysis-tabs-wrap {
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px;
  padding: 16px;
}

.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
}

.empty-sub-tab {
  padding: 40px;
  text-align: center;
  color: #9ca3af;
  font-size: 13px;
}

/* Episodes & Shots */
.episodes-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.episodes-collapse {
  background: transparent;
}

:deep(.ant-collapse-item) {
  margin-bottom: 12px;
  border: 1px solid #e5e7eb !important;
  border-radius: 10px !important;
  background: #ffffff !important;
  overflow: hidden;
}

:deep(.ant-collapse-header) {
  padding: 12px 16px !important;
  background: #f9fafb !important;
}

.ep-collapse-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
}

.ep-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ep-badge {
  background: #7047f6;
  color: #ffffff;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
}

.ep-main-title {
  font-size: 15px;
  font-weight: 600;
  color: #111827;
}

.ep-header-summary {
  font-size: 12px;
  color: #6b7280;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 600px;
}

.shots-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
  padding: 6px 0;
}

.shot-card {
  border: 1px solid #f1f5f9;
  border-radius: 8px;
  background: #fafbfc;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.2s;
}

.shot-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.03);
}

.shot-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px dashed #e2e8f0;
  padding-bottom: 8px;
}

.shot-badge {
  background: #1e293b;
  color: #ffffff;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.shot-title {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
  flex: 1;
}

.shot-meta-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}

.shot-meta-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  line-height: 18px;
}

.meta-lbl {
  color: #64748b;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 500;
  flex-shrink: 0;
}

.meta-val {
  color: #1e293b;
}

.scene-val {
  font-weight: 600;
  color: #2563eb;
}

.tags-cluster {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.dialogue-bubble {
  background: #f3e8ff;
  border-left: 2px solid #a855f7;
  color: #581c87;
  padding: 4px 8px;
  border-radius: 0 4px 4px 0;
  font-style: italic;
  font-weight: 500;
}

.audio-row {
  background: #f1f5f9;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  color: #475569;
}

.shot-prompt-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 8px;
  margin-top: 4px;
}

.prompt-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  font-weight: 600;
  color: #7047f6;
  margin-bottom: 2px;
}

.prompt-text {
  font-size: 11px;
  color: #475569;
  line-height: 16px;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Cards Grid for Characters & Scenes */
.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.character-card,
.scene-card {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 16px;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}

.char-header,
.scene-header {
  display: flex;
  gap: 12px;
  align-items: center;
}

.char-avatar {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  color: #ffffff;
  display: grid;
  place-items: center;
  font-size: 18px;
  font-weight: 700;
  flex-shrink: 0;
}

.char-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.char-name,
.scene-name {
  font-size: 15px;
  font-weight: 700;
  color: #111827;
  margin: 0;
}

.shots-stat {
  font-size: 11px;
  color: #9ca3af;
}

.char-props-section,
.scene-elements {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
}

.prop-lbl,
.elem-lbl {
  color: #6b7280;
  font-weight: 500;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.char-desc,
.scene-desc {
  font-size: 12px;
  color: #4b5563;
  line-height: 18px;
  margin: 0;
}

.char-prompt-section {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px;
}

/* Scene */
.scene-icon-wrap {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: #eff6ff;
  color: #3b82f6;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.scene-badges {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}

/* Props Grid */
.props-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.prop-card {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
  background: #fafbfc;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.prop-card-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.prop-icon-wrap {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: #fff7ed;
  color: #f97316;
  display: grid;
  place-items: center;
}

.prop-name {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
  margin: 0 0 2px;
}

.prop-card-bottom {
  font-size: 11px;
  color: #6b7280;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-top: 1px dashed #e2e8f0;
  padding-top: 6px;
}

.prop-info-item {
  display: flex;
  justify-content: space-between;
}

.count-val {
  font-weight: 600;
  color: #7047f6;
}

/* Globals */
.globals-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.global-card {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.global-card.full-width {
  grid-column: span 2;
}

.global-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: #1f2937;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 8px;
}

.positioning-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
}

.pos-item .k {
  font-weight: 600;
  color: #4b5563;
}

.pos-item .v {
  color: #111827;
}

.storyline-v {
  line-height: 20px;
}

.style-quote {
  background: #ffffff;
  border-left: 3px solid #3b82f6;
  padding: 10px 14px;
  border-radius: 0 6px 6px 0;
  font-size: 13px;
  line-height: 20px;
  color: #374151;
}

.prohibited-box {
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 10px;
}

.prohibited-title {
  font-size: 12px;
  font-weight: 600;
  color: #b91c1c;
}

.prohibited-text {
  font-size: 12px;
  color: #991b1b;
  margin: 4px 0 0;
  line-height: 18px;
}

.advice-text {
  font-size: 13px;
  color: #374151;
  line-height: 22px;
  margin: 0;
}

/* Raw Preview */
.script-preview-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.preview-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: #6b7280;
}

.script-text-box {
  background: #0f172a;
  color: #e2e8f0;
  padding: 16px;
  border-radius: 8px;
  font-family: monospace;
  font-size: 12px;
  line-height: 20px;
  max-height: 480px;
  overflow-y: auto;
  white-space: pre-wrap;
  margin: 0;
}

/* Format Guide */
.format-guide {
  font-size: 13px;
  color: #374151;
  max-height: 520px;
  overflow-y: auto;
}

.guide-lead {
  font-size: 13px;
  color: #4b5563;
  margin-bottom: 14px;
}

.guide-sections {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.guide-sec h5 {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  margin: 0 0 6px;
}

.guide-pre {
  background: #f1f5f9;
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 12px;
  color: #1e293b;
  margin: 0;
  white-space: pre-wrap;
}

.quick-fill-bar {
  background: #f5f3ff;
  border: 1px dashed #a78bfa;
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.quick-lbl {
  font-size: 12px;
  font-weight: 600;
  color: #6d28d9;
}

.script-file-picker {
  display: flex;
  align-items: center;
  gap: 10px;
}

.script-file-name {
  color: #334155;
  font-size: 12px;
  font-weight: 600;
}

.script-file-hint {
  color: #94a3b8;
  font-size: 12px;
}
</style>
