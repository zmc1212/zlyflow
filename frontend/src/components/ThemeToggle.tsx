import { Button, Tooltip } from "antd"
import { Moon, Sun } from "lucide-react"
import { useStudioTheme } from "../ThemeProvider"

export default function ThemeToggle({
  appearance = "icon",
  className = "",
}: {
  appearance?: "icon" | "menu"
  className?: string
}) {
  const { mode, toggleMode } = useStudioTheme()
  const nextModeLabel = mode === "dark" ? "切换到浅色外观" : "切换到暗色外观"
  const Icon = mode === "dark" ? Sun : Moon

  if (appearance === "menu") {
    return (
      <Button
        type="text"
        block
        icon={<Icon size={16} />}
        onClick={toggleMode}
        aria-label={nextModeLabel}
        className={`studio-theme-toggle studio-theme-toggle-menu ${className}`}
      >
        {mode === "dark" ? "浅色外观" : "暗色外观"}
      </Button>
    )
  }

  return (
    <Tooltip title={nextModeLabel} mouseEnterDelay={0.45}>
      <Button
        type="text"
        icon={<Icon size={17} />}
        onClick={toggleMode}
        aria-label={nextModeLabel}
        aria-pressed={mode === "dark"}
        className={`studio-theme-toggle studio-theme-toggle-icon ${className}`}
      />
    </Tooltip>
  )
}
