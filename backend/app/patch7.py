import sys

with open("frontend/src/director/components/RecipeAssetWorkbench.tsx", "r", encoding="utf-8") as f:
    content = f.read()

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

content = content.replace("  const state = renditionPreview(rendition, jobs)", simple_upload_block + "\n  const state = renditionPreview(rendition, jobs)")

content = content.replace(
"""      <button type="button" className="director-simple-asset-visual" onClick={() => imageUrl && setPreviewOpen(true)} disabled={!imageUrl}>""",
"""      <Upload.Dragger {...uploadProps} className="director-asset-dragger">
      <button type="button" className="director-simple-asset-visual" onClick={(e) => { e.stopPropagation(); imageUrl && setPreviewOpen(true); }} disabled={!imageUrl}>"""
)

content = content.replace(
"""        <span className={`director-asset-status-chip is-${cardTone}`}>{statusLabel}</span>
      </button>""",
"""        <span className={`director-asset-status-chip is-${cardTone}`}>{statusLabel}</span>
      </button>
      </Upload.Dragger>"""
)

with open("frontend/src/director/components/RecipeAssetWorkbench.tsx", "w", encoding="utf-8") as f:
    f.write(content)
