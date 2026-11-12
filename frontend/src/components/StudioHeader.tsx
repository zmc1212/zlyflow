import { Avatar, Button, Dropdown, Tooltip, type MenuProps } from "antd"
import { BookOpen, ChevronDown, ExternalLink, Link2, LoaderCircle, LogOut, Moon, Sun, UserRound, Users } from "lucide-react"
import { useState } from "react"
import type { User } from "../api"
import { useStudioTheme } from "../ThemeProvider"
import ThemeToggle from "./ThemeToggle"
import { StudioBrandSymbol } from "./StudioSymbols"
import "./studio-header.css"

const STUDIO_DOCS_URL = "https://ycntl2htf1l6.feishu.cn/docx/KLXadbEvboRaIAxRqTEcKBMmnTh"

type StudioHeaderProps = {
  compact?: boolean
  user: User | null
  onRequestLogin?: () => void
  provider: "视频服务" | "图片服务" | "音乐服务"
  providerStatus: "checking" | "online" | "offline"
  providerStatusLabel?: string
  providerMessage?: string | null
  onOpenMcp: () => void
  onOpenAdmin?: () => void
  onOpenProfile: () => void
  onLogout: () => void
  logoutPending: boolean
}

export default function StudioHeader({
  user, provider, providerStatus, providerStatusLabel, providerMessage, onOpenMcp, onOpenAdmin, onOpenProfile, onLogout, logoutPending, onRequestLogin, compact = false,
}: StudioHeaderProps) {
  const { mode, toggleMode } = useStudioTheme()
  const [accountOpen, setAccountOpen] = useState(false)
  const statusLabel = providerStatusLabel ?? { checking: "连接中", online: "已连接", offline: "未连接" }[providerStatus]
  const displayName = user?.display_name || user?.username || ""
  const items: MenuProps["items"] = [
    { key: "theme", icon: mode === "dark" ? <Sun size={16} /> : <Moon size={16} />, label: mode === "dark" ? "浅色外观" : "暗色外观" },
    { type: "divider" },
    { key: "profile", icon: <UserRound size={16} />, label: "个人资料" },
    { key: "mcp", icon: <Link2 size={16} />, label: "MCP 连接" },
    ...(onOpenAdmin ? [{ key: "admin", icon: <Users size={16} />, label: "管理设置" }] : []),
    { key: "docs", icon: <BookOpen size={16} />, label: <span className="studio-header-menu-label"><span>使用文档</span><ExternalLink size={14} aria-hidden="true" /></span> },
    { type: "divider" },
    { key: "logout", icon: logoutPending ? <LoaderCircle size={16} className="animate-spin" /> : <LogOut size={16} />, label: "退出登录", disabled: logoutPending },
  ]

  const onMenuClick: MenuProps["onClick"] = ({ key }) => {
    setAccountOpen(false)
    if (key === "theme") toggleMode()
    else if (key === "profile") onOpenProfile()
    else if (key === "mcp") onOpenMcp()
    else if (key === "admin") onOpenAdmin?.()
    else if (key === "docs") window.open(STUDIO_DOCS_URL, "_blank", "noopener,noreferrer")
    else if (key === "logout") onLogout()
  }

  return (
    <header className={"studio-header studio-header-floating" + (compact ? " studio-header-compact" : "")} aria-label="工作台页头">
      <div className="studio-header-island studio-header-brand">
        <span className="studio-header-brand-mark" aria-hidden="true">
          <StudioBrandSymbol />
        </span>
        <strong>ZLY AI Studio</strong>
        <span className="studio-header-divider" aria-hidden="true" />
        <h1 className="studio-header-title">创作工作台</h1>
      </div>
      <div className="studio-header-island studio-header-utilities">
        {user && <><Tooltip title={providerMessage || `${provider} · ${statusLabel}`}>
          <span className="studio-header-service" role="status" aria-live="polite">
            <span className={`studio-header-service-dot studio-header-service-${providerStatus}`} aria-hidden="true" />
            <span>{provider} · {statusLabel}</span>
          </span>
        </Tooltip>
        <span className="studio-header-divider" aria-hidden="true" /></>}
        <ThemeToggle className="studio-header-theme-toggle" />
        <span className="studio-header-divider" aria-hidden="true" />
        {user ? <Dropdown
          open={accountOpen}
          onOpenChange={setAccountOpen}
          trigger={["click"]}
          placement="bottomRight"
          classNames={{ root: "studio-header-account-dropdown" }}
          menu={{ items, onClick: onMenuClick }}
          popupRender={(menu) => (
            <div className="studio-header-account-popup">
              <div className="studio-header-account-heading">
                <strong>{displayName}</strong>
                <span>{user.username}</span>
              </div>
              {menu}
            </div>
          )}
        >
          <Button
            type="text"
            className="studio-header-account-button"
            aria-label={`账号菜单：${displayName}`}
            aria-haspopup="menu"
            aria-expanded={accountOpen}
          >
            <Avatar size={28}>{Array.from(displayName)[0]}</Avatar>
            <span className="studio-header-account-name">{displayName}</span>
            <ChevronDown size={14} aria-hidden="true" />
          </Button>
        </Dropdown> : <Button onClick={onRequestLogin} className="studio-header-login">登录</Button>}
      </div>
    </header>
  )
}
