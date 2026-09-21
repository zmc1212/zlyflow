import { Button, Dropdown, Tooltip } from "antd"
import type { MenuProps } from "antd"
import type { ReactNode } from "react"
import { VSR_SCALE_MENU, type VsrScale } from "./video-upscale"

export default function UpscaleScaleButton({
  disabled,
  loading,
  hint,
  onSelect,
  children = "超分",
  size = "small",
  className,
  ariaLabel = "超分",
  placement = "bottomLeft",
}: {
  disabled?: boolean
  loading?: boolean
  hint?: string
  onSelect: (scale: VsrScale) => void
  children?: ReactNode
  size?: "small" | "middle" | "large"
  className?: string
  ariaLabel?: string
  placement?: "bottomLeft" | "bottomRight" | "topLeft" | "topRight"
}) {
  const button = (
    <Button
      size={size}
      className={className}
      disabled={disabled}
      loading={Boolean(loading)}
      aria-label={ariaLabel}
    >
      {children}
    </Button>
  )
  if (disabled) {
    return hint ? <Tooltip title={hint}><span>{button}</span></Tooltip> : button
  }
  const items: MenuProps["items"] = VSR_SCALE_MENU.map((item) => ({
    key: item.key,
    label: item.label,
  }))
  const trigger = hint ? <Tooltip title={hint}>{button}</Tooltip> : button
  return (
    <Dropdown
      trigger={["click"]}
      placement={placement}
      menu={{
        items,
        onClick: ({ key }) => onSelect(Number(key) as VsrScale),
      }}
    >
      {trigger}
    </Dropdown>
  )
}
