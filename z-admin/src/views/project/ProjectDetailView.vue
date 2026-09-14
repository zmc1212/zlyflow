<template>
  <div class="project-detail-layout">
    <!-- 顶部项目条 -->
    <header class="project-topbar">
      <div class="topbar-content">
        <div class="topbar-left">
          <router-link to="/" class="back-link">
            <ChevronLeft :size="18" />
            <span>全部项目</span>
          </router-link>
          <div class="divider"></div>
          <div class="project-info">
            <h1 class="project-title">{{ project?.name || '加载中...' }}</h1>
            <span class="project-badge">进行中</span>
          </div>
        </div>

        <div class="topbar-right">
          <span class="project-id-tag">{{ project?.id }}</span>
        </div>
      </div>
    </header>

    <!-- 主体区域：左侧菜单 + 右侧工作区 -->
    <div class="project-main-body">
      <!-- 左侧 4 个菜单导航 -->
      <aside class="project-sidebar">
        <div class="menu-list">
          <div
            v-for="item in menuItems"
            :key="item.key"
            class="sidebar-menu-item"
            :class="{ active: activeMenu === item.key }"
            @click="handleMenuClick(item.key)"
          >
            <component :is="item.icon" :size="18" class="menu-icon" />
            <span class="menu-text">{{ item.label }}</span>
            <div v-if="activeMenu === item.key" class="active-indicator"></div>
          </div>
        </div>
      </aside>

      <!-- 右侧子模块内容区 -->
      <section
        class="project-content-pane"
        :class="{ 'is-workshop-detail': isWorkshopDetail }"
      >
        <transition name="fade" mode="out-in">
          <ContentLibraryPane
            v-if="activeMenu === 'content'"
            :project-id="projectId"
            @assets-transferred="onAssetsTransferred"
            @episodes-transferred="onEpisodesTransferred"
          />
          <AssetsLibraryPane
            v-else-if="activeMenu === 'assets'"
            ref="assetsPaneRef"
            :project-id="projectId"
          />
          <EpisodeWorkshopPane
            v-else-if="activeMenu === 'workshop'"
            ref="workshopPaneRef"
            :project-id="projectId"
            @detail-mode-change="onWorkshopDetailModeChange"
          />
          <JobsCenterPane
            v-else-if="activeMenu === 'jobs'"
            :project-id="projectId"
          />
        </transition>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ChevronLeft,
  BookOpen,
  Boxes,
  Film,
  ListChecks,
} from 'lucide-vue-next'
import { getProject } from '../../api/projects'
import ContentLibraryPane from './ContentLibraryPane.vue'
import AssetsLibraryPane from './AssetsLibraryPane.vue'
import EpisodeWorkshopPane from './EpisodeWorkshopPane.vue'
import JobsCenterPane from './JobsCenterPane.vue'

const route = useRoute()
const router = useRouter()
const projectId = route.params.id

const project = ref(null)
const assetsPaneRef = ref(null)
const workshopPaneRef = ref(null)

const menuItems = [
  { key: 'content', label: '内容库', icon: BookOpen },
  { key: 'assets', label: '资产库', icon: Boxes },
  { key: 'workshop', label: '剧集工坊', icon: Film },
  { key: 'jobs', label: '全部任务', icon: ListChecks },
]

// 根据当前路由地址自动计算激活菜单，实现 URL 与菜单完全双向联动
const activeMenu = computed(() => {
  const path = route.path
  if (path.includes('/assets')) return 'assets'
  if (path.includes('/workshop')) return 'workshop'
  if (path.includes('/jobs')) return 'jobs'
  return 'content'
})

// 剧集工坊分集详情模式判断（全屏工作台布局，去除外层多余滚动条）
const inWorkshopDetail = ref(false)
const isWorkshopDetail = computed(() => {
  return activeMenu.value === 'workshop' && (
    !!route.params.episodeId ||
    route.name === 'ProjectEpisodeDetail' ||
    inWorkshopDetail.value
  )
})

function onWorkshopDetailModeChange(inDetail) {
  inWorkshopDetail.value = inDetail
}

function handleMenuClick(key) {
  if (key === 'content') {
    router.push(`/projects/${projectId}/content`)
  } else if (key === 'assets') {
    router.push(`/projects/${projectId}/assets`)
  } else if (key === 'workshop') {
    router.push(`/projects/${projectId}/workshop`)
  } else if (key === 'jobs') {
    router.push(`/projects/${projectId}/jobs`)
  }
}

async function loadProjectInfo() {
  try {
    const data = await getProject(projectId)
    project.value = data
  } catch (err) {
    message.error('未找到该项目')
    router.push('/')
  }
}

function onAssetsTransferred() {
  if (assetsPaneRef.value?.fetchAssets) {
    assetsPaneRef.value.fetchAssets()
  }
}

function onEpisodesTransferred() {
  if (workshopPaneRef.value?.fetchEpisodes) {
    workshopPaneRef.value.fetchEpisodes()
  }
}

onMounted(() => {
  loadProjectInfo()
})
</script>

<style scoped>
.project-detail-layout {
  height: calc(100vh - 64px);
  display: flex;
  flex-direction: column;
  background-color: #f8fafc;
  overflow: hidden; /* 防止双重全局滚动条，由右侧内容区主导滚动 */
}

/* 顶部项目条 */
.project-topbar {
  height: 56px;
  flex-shrink: 0;
  background: #ffffff;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
  z-index: 40;
}

.topbar-content {
  height: 100%;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 500;
  color: #64748b;
  text-decoration: none;
  padding: 6px 10px;
  border-radius: 6px;
  transition: all 0.2s;
}

.back-link:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.divider {
  width: 1px;
  height: 20px;
  background: #e2e8f0;
}

.project-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.project-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
  letter-spacing: -0.2px;
}

.project-badge {
  font-size: 11px;
  font-weight: 600;
  color: #10b981;
  background: rgba(16, 185, 129, 0.1);
  padding: 2px 8px;
  border-radius: 12px;
}

.topbar-right {
  display: flex;
  align-items: center;
}

.project-id-tag {
  font-size: 12px;
  color: #94a3b8;
  font-family: monospace;
  background: #f1f5f9;
  padding: 3px 8px;
  border-radius: 6px;
}

/* 主体：左侧固定侧边栏 + 右侧自由滑动内容区 */
.project-main-body {
  width: 100%;
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 0;
}

/* 左侧 4 个菜单导航固定不动 */
.project-sidebar {
  width: 220px;
  flex-shrink: 0;
  height: 100%;
  padding: 20px 12px 20px 24px;
  overflow-y: auto;
  user-select: none;
  background: #f8fafc;
  border-right: 1px solid #eef2f6;
}

.menu-list {
  position: sticky;
  top: 0;
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 14px;
  padding: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sidebar-menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  color: #64748b;
  cursor: pointer;
  position: relative;
  transition: all 0.2s ease;
}

.sidebar-menu-item:hover {
  background: #f8fafc;
  color: #1e293b;
}

.sidebar-menu-item.active {
  background: rgba(112, 71, 246, 0.08);
  color: #7047f6;
  font-weight: 600;
}

.menu-icon {
  color: inherit;
  flex-shrink: 0;
}

.menu-text {
  flex: 1;
}

.active-indicator {
  position: absolute;
  right: 8px;
  width: 5px;
  height: 18px;
  border-radius: 4px;
  background: #7047f6;
}

/* 右侧内容区：支持随便顺畅自由滑动到底部 */
.project-content-pane {
  flex: 1;
  min-width: 0;
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 20px 24px 60px 20px;
  scroll-behavior: smooth;
}

/* 剧集工坊分集工作台详情模式：无外层多余滚动条，全屏沉浸式工作台 */
.project-content-pane.is-workshop-detail {
  padding: 14px 20px 14px 20px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.project-content-pane.is-workshop-detail > :deep(.workshop-container),
.project-content-pane.is-workshop-detail > .workshop-container {
  height: 100%;
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
