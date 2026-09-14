import { Button, Tooltip } from "antd"
import type { ReactNode } from "react"

export type RecipeAssetActionRailItem = {
  key: string
  label: string
  icon: ReactNode
  onClick: () => void
  disabled?: boolean
  loading?: boolean
  emphasis?: "primary" | "default"
  hint?: string
  renderWrapper?: (child: ReactNode) => ReactNode
}

export default function RecipeAssetActionRail({ items }: { items: RecipeAssetActionRailItem[] }) {
  return (
    <div className="director-asset-action-rail" role="toolbar" aria-label="定妆操作">
      {items.map((item) => {
        const button = (
          <Button
            block
            size="small"
            type={item.emphasis === "primary" ? "primary" : "default"}
            icon={item.icon}
            disabled={item.disabled}
            loading={item.loading}
            onClick={item.onClick}
            className="director-asset-action-rail-btn"
          >
            {item.label}
          </Button>
        )
        return (
          <div key={item.key} className="director-asset-action-rail-cell">
            {item.renderWrapper ? item.renderWrapper(
              item.hint ? (
                <Tooltip title={item.hint}>
                  <span className="director-asset-action-rail-tooltip">{button}</span>
                </Tooltip>
              ) : button
            ) : item.hint ? (
              <Tooltip title={item.hint}>
                <span className="director-asset-action-rail-tooltip">{button}</span>
              </Tooltip>
            ) : button}
          </div>
        )
      })}
    </div>
  )
}
