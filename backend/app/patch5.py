import sys

with open("frontend/src/director/components/RecipeAssetWorkbench.tsx", "r", encoding="utf-8") as f:
    content = f.read()

# CharacterAssetCard props
content = content.replace(
    "onSaveToLibrary: () => void\n}) {",
    "onSaveToLibrary: () => void\n  onUpload?: (lookId: string | undefined, file: File) => void\n}) {"
)

# CharacterAssetCard upload integration
char_upload_block = """
  const beforeUpload = (file: File) => {
    if (onUpload) {
      onUpload(look?.id, file)
    }
    return Upload.LIST_IGNORE
  }

  const uploadProps = {
    showUploadList: false,
    beforeUpload,
    accept: "image/*",
    disabled: !onUpload,
  }
"""

content = content.replace("  const totalVersions = portrait.versions.length + (look?.sheet.versions.length || 0)", char_upload_block + "\n  const totalVersions = portrait.versions.length + (look?.sheet.versions.length || 0)")

content = content.replace(
"""      <button
        type="button"
        className={`director-character-visual${shown ? " has-image" : ""}`}
        onClick={() => shown && setPreviewOpen(true)}
        disabled={!shown}
      >""",
"""      <Upload.Dragger {...uploadProps} className="director-asset-dragger">
      <button
        type="button"
        className={`director-character-visual${shown ? " has-image" : ""}`}
        onClick={(e) => { e.stopPropagation(); shown && setPreviewOpen(true); }}
        disabled={!shown}
      >"""
)

content = content.replace(
"""        {sheetApproved ? <span className="director-asset-status-chip is-ready">已批准</span> : (
          <span className={`director-asset-status-chip is-${cardTone}`}>{statusLabel}</span>
        )}
      </button>""",
"""        {sheetApproved ? <span className="director-asset-status-chip is-ready">已批准</span> : (
          <span className={`director-asset-status-chip is-${cardTone}`}>{statusLabel}</span>
        )}
      </button>
      </Upload.Dragger>"""
)


# SimpleRenditionAssetCard props
content = content.replace(
    "onSaveToLibrary: () => void\n}) {",
    "onSaveToLibrary: () => void\n  onUpload?: (file: File) => void\n}) {"
)

# SimpleRenditionAssetCard upload integration
simple_upload_block = """
  const beforeUpload = (file: File) => {
    if (onUpload) {
      onUpload(file)
    }
    return Upload.LIST_IGNORE
  }

  const uploadProps = {
    showUploadList: false,
    beforeUpload,
    accept: "image/*",
    disabled: !onUpload,
  }
"""

content = content.replace("  const activeState = renditionPreview(rendition, jobs)", simple_upload_block + "\n  const activeState = renditionPreview(rendition, jobs)")

content = content.replace(
"""      <button
        type="button"
        className={`director-character-visual${shown ? " has-image" : ""}`}
        onClick={() => shown && setPreviewOpen(true)}
        disabled={!shown}
      >""",
"""      <Upload.Dragger {...uploadProps} className="director-asset-dragger">
      <button
        type="button"
        className={`director-character-visual${shown ? " has-image" : ""}`}
        onClick={(e) => { e.stopPropagation(); shown && setPreviewOpen(true); }}
        disabled={!shown}
      >"""
)

content = content.replace(
"""        {approved ? <span className="director-asset-status-chip is-ready">已批准</span> : (
          <span className={`director-asset-status-chip is-${cardTone}`}>{statusLabel}</span>
        )}
      </button>""",
"""        {approved ? <span className="director-asset-status-chip is-ready">已批准</span> : (
          <span className={`director-asset-status-chip is-${cardTone}`}>{statusLabel}</span>
        )}
      </button>
      </Upload.Dragger>"""
)

# Add Upload import
content = content.replace(
    "import { Card, Collapse, Drawer, Empty, Input, Progress, Space, Tabs, Typography } from \"antd\"",
    "import { Card, Collapse, Drawer, Empty, Input, Progress, Space, Tabs, Typography, Upload } from \"antd\""
)

with open("frontend/src/director/components/RecipeAssetWorkbench.tsx", "w", encoding="utf-8") as f:
    f.write(content)
