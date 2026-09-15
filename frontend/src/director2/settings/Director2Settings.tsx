// 系统服务设置页 —— 复刻自 dev0914 z-admin/src/views/settings/SettingsView.vue
// 决策：Tab 内容复用工作台现有 /api/admin 体系的 React 供应商设置组件（与 dev0914 的
// Vue 设置组件同源同视觉），数据读写与整个工作台共享一套配置。
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Tabs } from "antd"
import { ArrowLeft, Sliders } from "lucide-react"
import ComfyProviderSettings from "./ComfyProviderSettings"
import GrsProviderSettings from "./GrsProviderSettings"
import LlmProviderSettings from "./LlmProviderSettings"
import QiniuStorageSettings from "./QiniuStorageSettings"
import { director2HomePath } from "../paths"
import "./settings.css"

export default function Director2Settings({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState("providers")

  const goHome = () => {
    navigate(director2HomePath())
  }

  return (
    <div className="d2-settings-scope settings-view">
      <div className="settings-container">
        {/* 页面顶部导航栏 */}
        <div className="settings-header">
          <div className="header-left">
            <button className="back-btn" onClick={goHome} title="返回首页">
              <ArrowLeft size={18} />
            </button>
            <span className="divider" />
            <div className="header-title-box">
              <Sliders size={18} className="text-primary" />
              <h1 className="page-title">系统服务设置</h1>
            </div>
          </div>
        </div>

        {/* Tabs 导航 */}
        <div className="tabs-box">
          <Tabs activeKey={activeTab} onChange={setActiveTab} size="large" items={[
            { key: "providers", label: "AI 供应商" },
            { key: "llm", label: "LLM 大模型" },
            { key: "storage", label: "媒体存储" },
          ]} />
        </div>

        {/* Tab 内容区 */}
        <div className="tab-content">
          {activeTab === "providers" && (
            <>
              <ComfyProviderSettings csrfToken={csrfToken} />
              <GrsProviderSettings csrfToken={csrfToken} />
            </>
          )}
          {activeTab === "llm" && <LlmProviderSettings csrfToken={csrfToken} />}
          {activeTab === "storage" && <QiniuStorageSettings csrfToken={csrfToken} />}
        </div>
      </div>
    </div>
  )
}
