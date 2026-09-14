import sys

with open("frontend/src/director/components/RecipeAssetWorkbench.tsx", "r", encoding="utf-8") as f:
    content = f.read()

# We need to change the onUpload type for SimpleRenditionAssetCard
# Find SimpleRenditionAssetCard definition

idx = content.find("export function SimpleRenditionAssetCard(")
if idx != -1:
    before = content[:idx]
    after = content[idx:]
    after = after.replace(
        "onUpload?: (lookId: string | undefined, file: File) => void",
        "onUpload?: (file: File) => void",
        1
    )
    content = before + after

with open("frontend/src/director/components/RecipeAssetWorkbench.tsx", "w", encoding="utf-8") as f:
    f.write(content)
