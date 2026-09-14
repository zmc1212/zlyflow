import sys

with open("frontend/src/director/components/RecipeAssetWorkbench.tsx", "r", encoding="utf-8") as f:
    content = f.read()

# Remove the disabled={!shown} and only stop propagation if shown
content = content.replace(
"""      <Upload.Dragger {...uploadProps} className="director-asset-dragger">
      <button
        type="button"
        className={`director-character-visual${shown ? " has-image" : ""}`}
        onClick={(e) => { e.stopPropagation(); shown && setPreviewOpen(true); }}
        disabled={!shown}
      >""",
"""      <Upload.Dragger {...uploadProps} className="director-asset-dragger">
      <button
        type="button"
        className={`director-character-visual${shown ? " has-image" : ""}`}
        onClick={(e) => { if (shown) { e.stopPropagation(); setPreviewOpen(true); } }}
      >"""
)

content = content.replace(
"""      <Upload.Dragger {...uploadProps} className="director-asset-dragger">
      <button type="button" className="director-simple-asset-visual" onClick={(e) => { e.stopPropagation(); imageUrl && setPreviewOpen(true); }} disabled={!imageUrl}>""",
"""      <Upload.Dragger {...uploadProps} className="director-asset-dragger">
      <button type="button" className="director-simple-asset-visual" onClick={(e) => { if (imageUrl) { e.stopPropagation(); setPreviewOpen(true); } }}>"""
)

# Remove the upload item from Character action rail
character_upload_item = """            {
              key: "upload",
              label: "上传",
              icon: <UploadIcon size={14} />,
              disabled: !onUpload,
              hint: portraitApproved ? "上传定妆板图片" : "上传肖像图片",
              onClick: () => {},
              renderWrapper: (child: React.ReactNode) => (
                <Upload {...uploadProps}>
                  {child}
                </Upload>
              )
            },
"""
content = content.replace(character_upload_item, "")

# Remove the upload item from Simple action rail
simple_upload_item = """          {
            key: "upload",
            label: "上传",
            icon: <UploadIcon size={14} />,
            disabled: !onUpload,
            hint: "上传图片",
            onClick: () => {},
            renderWrapper: (child: React.ReactNode) => (
                <Upload {...uploadProps}>
                  {child}
                </Upload>
            )
          },
"""
content = content.replace(simple_upload_item, "")


with open("frontend/src/director/components/RecipeAssetWorkbench.tsx", "w", encoding="utf-8") as f:
    f.write(content)
