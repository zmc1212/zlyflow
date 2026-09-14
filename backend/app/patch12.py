import sys

with open("frontend/src/director/components/RecipeAssetWorkbench.tsx", "r", encoding="utf-8") as f:
    content = f.read()

# Replace lucide imports
content = content.replace("  Settings2,\n} from \"lucide-react\"", "  Settings2,\n  Upload as UploadIcon,\n} from \"lucide-react\"")

# Add Upload to character items
character_upload_item = """
            {
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

content = content.replace(
"""            {
              key: "library",""",
character_upload_item + """            {
              key: "library","""
)

# Add Upload to simple items
simple_upload_item = """
            {
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

content = content.replace(
"""          {
            key: "library",""",
simple_upload_item + """          {
            key: "library","""
)

with open("frontend/src/director/components/RecipeAssetWorkbench.tsx", "w", encoding="utf-8") as f:
    f.write(content)
