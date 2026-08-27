import { Button, Dropdown } from "antd"
import type { MenuProps } from "antd"
import { ArrowLeft, MoreHorizontal } from "lucide-react"

export function DirectorMobileHeader({
  title,
  onBack,
  menuItems,
}: {
  title: string
  onBack: () => void
  menuItems: MenuProps["items"]
}) {
  return (
    <header className="director-mobile-header">
      <button type="button" aria-label="返回工程库" onClick={onBack}>
        <ArrowLeft size={20} />
      </button>
      <strong>{title}</strong>
      <Dropdown trigger={["click"]} menu={{ items: menuItems }}>
        <button type="button" aria-label="更多操作">
          <MoreHorizontal size={20} />
        </button>
      </Dropdown>
    </header>
  )
}

export function DirectorMobileBottomBar({
  label,
  onClick,
  loading,
  disabled,
}: {
  label: string
  onClick: () => void
  loading?: boolean
  disabled?: boolean
}) {
  return (
    <div className="director-mobile-bottom-bar">
      <Button
        type="primary"
        className="director-mobile-generate"
        loading={loading}
        disabled={disabled}
        onClick={onClick}
      >
        {label}
      </Button>
    </div>
  )
}
