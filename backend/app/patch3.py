import sys

with open("frontend/src/director/director-api.ts", "r", encoding="utf-8") as f:
    content = f.read()

new_api = """

export async function uploadDirectorRecipeAssetImage(
  projectId: string,
  body: { kind: string; asset_id: string; look_id?: string; file: File; expected_content_revision?: number },
  csrfToken: string,
) {
  const form = new FormData()
  form.set("kind", body.kind)
  form.set("asset_id", body.asset_id)
  form.set("file", body.file)
  if (body.look_id) {
    form.set("look_id", body.look_id)
  }
  if (body.expected_content_revision) {
    form.set("expected_content_revision", String(body.expected_content_revision))
  }
  const response = await fetch(
    `/api/director/recipes/${encodeURIComponent(projectId)}/asset-image`,
    { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } },
  )
  if (response.status === 401) notifyUnauthorized()
  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? ""
    const payload = contentType.includes("application/json")
      ? await response.json().catch(() => null)
      : await response.text().catch(() => "")
    throw new ApiRequestError(response.status, payload, "上传素材图片失败")
  }
  return response.json() as Promise<DirectorProjectResponse>
}

"""

if "uploadDirectorRecipeAssetImage" not in content:
    content = content.replace("export async function uploadDirectorShotFrame(", new_api + "\nexport async function uploadDirectorShotFrame(")
    with open("frontend/src/director/director-api.ts", "w", encoding="utf-8") as f:
        f.write(content)
