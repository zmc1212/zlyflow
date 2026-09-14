import sys

with open("frontend/src/director/components/RecipeAssetWorkbench.tsx", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    "  onSaveToLibrary,\n}: {",
    "  onSaveToLibrary,\n  onUpload,\n}: {"
)

with open("frontend/src/director/components/RecipeAssetWorkbench.tsx", "w", encoding="utf-8") as f:
    f.write(content)
