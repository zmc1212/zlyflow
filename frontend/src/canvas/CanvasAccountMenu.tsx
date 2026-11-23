import { useQuery } from "@tanstack/react-query"
import { Avatar, Button, Dropdown, type MenuProps } from "antd"
import { ChevronDown, ChevronRight, Coins, LogOut, Moon, Sun, UserRound } from "lucide-react"
import { useRef } from "react"
import { requestJson, type User } from "../api"
import RenameUserModal from "../components/RenameUserModal"
import { CreditDrawer } from "../credits/CreditDrawer"
import { formatCredits, type CreditAccount } from "../credits/credits"
import { useStudioTheme } from "../ThemeProvider"
import "./canvas-account.css"

export type CanvasAccount = {
  user: User
  onLogout: () => void
  logoutPending: boolean
}

export type CanvasAccountOverlay = "menu" | "credits" | "profile" | null

export default function CanvasAccountMenu({ user, csrfToken, onLogout, logoutPending, overlay, onOverlayChange }: CanvasAccount & {
  csrfToken: string
  overlay: CanvasAccountOverlay
  onOverlayChange: (overlay: CanvasAccountOverlay) => void
}) {
  const { mode, toggleMode } = useStudioTheme()
  const triggerRef = useRef<HTMLButtonElement>(null)
  const wallet = useQuery({
    queryKey: ["credits-me"],
    queryFn: () => requestJson<CreditAccount>("/api/credits/me"),
    refetchOnWindowFocus: true,
  })
  const displayName = user.display_name || user.username
  const avatarSrc = user.avatar_url || undefined
  const avatarInitial = Array.from(displayName)[0]
  const balance = formatCredits(wallet.data?.balance)
  const balanceLabel = wallet.data?.scope === "enterprise" ? "企业积分余额" : "积分余额"
  const balanceDetail = wallet.data ? balance : wallet.isPending ? "加载中" : "暂不可用"
  const menuOpen = overlay === "menu"
  const close = () => onOverlayChange(null)

  const items: MenuProps["items"] = [{
    type: "group",
    key: "account",
    label: <div className="canvas-account-identity">
      <Avatar size={38} src={avatarSrc}>{avatarInitial}</Avatar>
      <div className="canvas-account-name">
        <strong title={displayName}>{displayName}</strong>
        <span title={user.username}>@{user.username}</span>
      </div>
    </div>,
    children: [
      {
        key: "credits",
        className: "canvas-account-wallet",
        label: <div className="canvas-account-wallet-row">
          <span className="canvas-account-wallet-balance">
            <span>{balanceLabel}</span>
            <strong>{balanceDetail}</strong>
          </span>
          <span className="canvas-account-wallet-link">积分明细 <ChevronRight size={14} aria-hidden="true" /></span>
        </div>,
      },
      { key: "profile", icon: <UserRound size={16} />, label: "个人资料" },
      { key: "theme", icon: mode === "dark" ? <Sun size={16} /> : <Moon size={16} />, label: mode === "dark" ? "浅色外观" : "暗色外观" },
      { type: "divider" },
      { key: "logout", icon: <LogOut size={16} />, label: "退出登录", disabled: logoutPending },
    ],
  }]

  const onMenuClick: MenuProps["onClick"] = ({ key }) => {
    triggerRef.current?.focus({ preventScroll: true })
    if (key === "credits" || key === "profile") {
      onOverlayChange(key)
      return
    }
    close()
    if (key === "theme") toggleMode()
    if (key === "logout") onLogout()
  }

  return <>
    <Dropdown
      open={menuOpen}
      onOpenChange={(open, info) => {
        if (info.source !== "trigger") return
        onOverlayChange(open ? "menu" : null)
        if (open && !wallet.isFetching) void wallet.refetch()
      }}
      autoFocus
      destroyOnHidden
      trigger={["click"]}
      placement="bottomRight"
      classNames={{ root: "canvas-account-dropdown" }}
      menu={{ className: "canvas-account-popup", items, onClick: onMenuClick }}
    >
      <Button
        ref={triggerRef}
        className="canvas-account-trigger"
        aria-label={`账号菜单，${displayName}，${balanceLabel} ${balanceDetail}`}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
      >
        <span className="canvas-account-points" aria-hidden="true"><Coins size={15} />{balance}</span>
        <Avatar size={24} src={avatarSrc}>{avatarInitial}</Avatar>
        <ChevronDown className="canvas-account-chevron" size={13} aria-hidden="true" />
      </Button>
    </Dropdown>
    <CreditDrawer open={overlay === "credits"} onClose={close} />
    {overlay === "profile" ? <RenameUserModal target={user} csrfToken={csrfToken} self onClose={close} /> : null}
  </>
}
