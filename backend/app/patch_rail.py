import sys

with open("frontend/src/director/components/RecipeAssetActionRail.tsx", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
"""  hint?: string
}""",
"""  hint?: string
  renderWrapper?: (child: ReactNode) => ReactNode
}"""
)

content = content.replace(
"""            {item.hint ? (
              <Tooltip title={item.hint}>
                <span className="director-asset-action-rail-tooltip">{button}</span>
              </Tooltip>
            ) : button}""",
"""            {item.renderWrapper ? item.renderWrapper(
              item.hint ? (
                <Tooltip title={item.hint}>
                  <span className="director-asset-action-rail-tooltip">{button}</span>
                </Tooltip>
              ) : button
            ) : item.hint ? (
              <Tooltip title={item.hint}>
                <span className="director-asset-action-rail-tooltip">{button}</span>
              </Tooltip>
            ) : button}"""
)

with open("frontend/src/director/components/RecipeAssetActionRail.tsx", "w", encoding="utf-8") as f:
    f.write(content)
