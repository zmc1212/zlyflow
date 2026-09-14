<template>
  <div class="app-layout">
    <!-- 顶部统一导航条 -->
    <header class="top-nav">
      <div class="nav-container">
        <!-- 左侧品牌与主导航 -->
        <div class="nav-left">
          <router-link to="/" class="brand-link">
            <div class="brand-logo">
              <Sparkles :size="18" />
            </div>
            <span class="brand-title">AI Media Studio</span>
          </router-link>

          <nav class="nav-links">
            <router-link to="/" class="nav-item" :class="{ active: isHome }">
              首页
            </router-link>
          </nav>
        </div>

        <!-- 右侧设置按钮 -->
        <div class="nav-right">
          <router-link to="/settings" class="settings-btn" :class="{ active: isSettings }">
            <Settings :size="16" />
            <span>设置</span>
          </router-link>
        </div>
      </div>
    </header>

    <!-- 视图渲染区 -->
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Sparkles, Settings } from 'lucide-vue-next'

const route = useRoute()
const isHome = computed(() => route.path === '/')
const isSettings = computed(() => route.path.startsWith('/settings'))
</script>

<style>
/* 全局重置与基础样式 */
html, body {
  margin: 0;
  padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: #1f2937;
  background-color: #f8f9fa;
  -webkit-font-smoothing: antialiased;
}

* {
  box-sizing: border-box;
}
</style>

<style scoped>
.app-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.top-nav {
  height: 64px;
  background: #ffffff;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
  position: sticky;
  top: 0;
  z-index: 50;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}

.nav-container {
  height: 100%;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 28px;
}

.brand-link {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
}

.brand-logo {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: linear-gradient(135deg, #7047f6 0%, #9333ea 100%);
  display: grid;
  place-items: center;
  color: #ffffff;
}

.brand-title {
  font-size: 16px;
  font-weight: 700;
  color: #111827;
  letter-spacing: -0.3px;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 6px;
}

.nav-item {
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  color: #4b5563;
  text-decoration: none;
  transition: all 0.2s;
}

.nav-item:hover {
  background: rgba(0, 0, 0, 0.04);
  color: #111827;
}

.nav-item.active {
  color: #7047f6;
  background: rgba(112, 71, 246, 0.08);
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.settings-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  border-radius: 8px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: #ffffff;
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.2s;
}

.settings-btn:hover {
  border-color: #7047f6;
  color: #7047f6;
  background: rgba(112, 71, 246, 0.04);
}

.settings-btn.active {
  border-color: #7047f6;
  background: #7047f6;
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(112, 71, 246, 0.25);
}

.app-main {
  flex: 1;
}
</style>
