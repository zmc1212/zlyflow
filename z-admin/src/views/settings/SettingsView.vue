<template>
  <div class="settings-view">
    <div class="settings-container">
      <!-- 页面顶部导航栏 -->
      <div class="settings-header">
        <div class="header-left">
          <button class="back-btn" @click="goHome" title="返回首页">
            <ArrowLeft :size="18" />
          </button>
          <span class="divider"></span>
          <div class="header-title-box">
            <Sliders :size="18" class="text-primary" />
            <h1 class="page-title">系统服务设置</h1>
          </div>
        </div>
      </div>

      <!-- Tabs 导航 -->
      <div class="tabs-box">
        <a-tabs v-model:activeKey="activeTab" size="large">
          <a-tab-pane key="providers" tab="AI 供应商" />
          <a-tab-pane key="llm" tab="LLM 大模型" />
          <a-tab-pane key="storage" tab="媒体存储" />
        </a-tabs>
      </div>

      <!-- Tab 内容区 -->
      <div class="tab-content">
        <template v-if="activeTab === 'providers'">
          <ComfyProviderSettings />
          <GrsProviderSettings />
        </template>

        <template v-else-if="activeTab === 'llm'">
          <LlmProviderSettings />
        </template>

        <template v-else-if="activeTab === 'storage'">
          <QiniuStorageSettings />
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArrowLeft, Sliders } from 'lucide-vue-next'
import ComfyProviderSettings from './ComfyProviderSettings.vue'
import GrsProviderSettings from './GrsProviderSettings.vue'
import LlmProviderSettings from './LlmProviderSettings.vue'
import QiniuStorageSettings from './QiniuStorageSettings.vue'

const router = useRouter()
const route = useRoute()

const initialTab = route.query.tab || 'providers'
const activeTab = ref(initialTab)

const goHome = () => {
  router.push('/')
}
</script>

<style scoped>
.settings-view {
  min-height: calc(100vh - 64px);
  background: #f8f9fa;
  padding: 24px 20px 48px;
}

.settings-container {
}

.settings-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.back-btn {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: #ffffff;
  display: grid;
  place-items: center;
  color: #4b5563;
  cursor: pointer;
  transition: all 0.2s;
}

.back-btn:hover {
  background: #f3f4f6;
  color: #111827;
}

.divider {
  width: 1px;
  height: 20px;
  background: rgba(0, 0, 0, 0.1);
}

.header-title-box {
  display: flex;
  align-items: center;
  gap: 8px;
}

.text-primary {
  color: #7047f6;
}

.page-title {
  font-size: 18px;
  font-weight: 600;
  color: #111827;
  margin: 0;
}

.tabs-box {
  margin-bottom: 20px;
  background: #ffffff;
  padding: 0 20px;
  border-radius: 12px;
  border: 1px solid rgba(0, 0, 0, 0.06);
}

.tab-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
</style>
