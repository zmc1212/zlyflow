import sys

with open("frontend/src/director/DirectorRecipeStudio.tsx", "r", encoding="utf-8") as f:
    content = f.read()

new_import = "import { uploadDirectorRecipeAssetImage } from \"./director-api\""
if "uploadDirectorRecipeAssetImage" not in content:
    content = content.replace("import {", new_import + "\nimport {", 1)

new_func = """
  async function handleUploadAssetImage(kind: "character" | "location" | "prop", assetId: string, lookId: string | undefined, file: File) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await uploadDirectorRecipeAssetImage(projectId, {
        kind,
        asset_id: assetId,
        look_id: lookId,
        file,
        expected_content_revision: contentRevisionRef.current || undefined,
      }, csrfToken)
      const payload = recipePayloadFromApi(row)
      projectRevisionRef.current = row.revision
      contentRevisionRef.current = row.content_revision
      if (payload) setRecipe(payload)
      messageApi.success("已上传素材图片")
    } catch (error) {
      const remote = readDirectorContentConflict(error)
      if (remote) {
        const conflict = { remote }
        conflictRef.current = conflict
        setContentConflict(conflict)
        setSaveStatus("failed")
        return
      }
      notifyFailure(error, "上传素材图片失败")
    }
  }
"""
if "handleUploadAssetImage" not in content:
    content = content.replace("async function handleUploadScriptCover(", new_func + "\n  async function handleUploadScriptCover(")

# Pass onUpload to CharacterAssetCard
# Find where CharacterAssetCard is used
import re
content = re.sub(
    r"(<CharacterAssetCard\s+key=\{character\.id\}\s+character=\{character\}\s+jobs=\{allJobs\}\s+onChange=\{[^{}]*\{.*?\}\)*\}\s+onGenerate=\{.*?\}\s+onApprove=\{.*?\}\s+onSaveToLibrary=\{.*?\})",
    r"\1\n                          onUpload={(lookId, file) => { void handleUploadAssetImage('character', character.id, lookId, file) }}",
    content,
    flags=re.DOTALL
)

# Pass onUpload to SimpleRenditionAssetCard for locations
content = re.sub(
    r"(<SimpleRenditionAssetCard\s+key=\{location\.id\}\s+asset=\{location\}\s+kind=\"location\"\s+jobs=\{allJobs\}\s+onChange=\{[^{}]*\{.*?\}\)*\}\s+onGenerate=\{.*?\}\s+onApprove=\{.*?\}\s+onSaveToLibrary=\{.*?\})",
    r"\1\n                          onUpload={(file) => { void handleUploadAssetImage('location', location.id, undefined, file) }}",
    content,
    flags=re.DOTALL
)

# Pass onUpload to SimpleRenditionAssetCard for props
content = re.sub(
    r"(<SimpleRenditionAssetCard\s+key=\{prop\.id\}\s+asset=\{prop\}\s+kind=\"prop\"\s+jobs=\{allJobs\}\s+onChange=\{[^{}]*\{.*?\}\)*\}\s+onGenerate=\{.*?\}\s+onApprove=\{.*?\}\s+onSaveToLibrary=\{.*?\})",
    r"\1\n                          onUpload={(file) => { void handleUploadAssetImage('prop', prop.id, undefined, file) }}",
    content,
    flags=re.DOTALL
)

with open("frontend/src/director/DirectorRecipeStudio.tsx", "w", encoding="utf-8") as f:
    f.write(content)
