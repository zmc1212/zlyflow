import { Button, Dropdown, type MenuProps } from "antd"
import { MoreHorizontal } from "lucide-react"
import type { ReactNode } from "react"

export default function RecipeAssetStageToolbar({
  title,
  summary,
  primaryActions,
  moreMenuItems,
}: {
  title: string
  summary?: string
  primaryActions: ReactNode
  moreMenuItems?: MenuProps["items"]
}) {
  const hasMore = Boolean(moreMenuItems?.length)
  return (
    <div className="director-asset-stage-toolbar">
      <div className="director-asset-stage-toolbar-copy">
        <strong>{title}</strong>
        {summary ? <span>{summary}</span> : null}
      </div>
      <div className="director-asset-stage-toolbar-actions">
        {primaryActions}
        {hasMore ? (
          <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
            <Button size="small" icon={<MoreHorizontal size={14} />}>更多</Button>
          </Dropdown>
        ) : null}
      </div>
    </div>
  )
}
