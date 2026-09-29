import { jsonMutation, requestJson } from "../api"

export type ManifestEntry = { id: string; kind: string; name: string; identity: string; aliases?: string[]; era?: string;
  evidence: Array<{ scope: number; quote: string }>; difference?: string; suggested_asset_ids?: string[]; asset_id?: string; look_id?: string }
export type ManifestState = {
  history?: Array<{version: string; confirmed_at: string; source_revision: number}>;
  manifest: { status: string; version: string; entries: ManifestEntry[] } | null;
  assets: Array<{ id: string; name: string; kind: string; looks: Array<{ id: string; name: string }> }>;
  job: { id: string; status: string; error?: string; revision: string; data: { message: string; entries: ManifestEntry[]; issues: string[]; coverage: Array<{scope: number; characters: number}> } } | null;
}
export type AssetReference = { manifest_id: string; appearance: string; location: string; evidence: string; name?: string; era?: string; kind?: string }
export type AssetAudit = { status: string; shots: Array<{ id: string; references: AssetReference[]; issues: string[] }> }
const base = (p: string, d: string) => `/api/projects/${encodeURIComponent(p)}/documents/${encodeURIComponent(d)}/asset-manifest`
export const readManifest = (p: string, d: string) => requestJson<ManifestState>(base(p, d))
export const extractManifest = (csrf: string, p: string, d: string) => requestJson<ManifestState>(base(p, d), jsonMutation(csrf, {}, "POST"))
export const actManifest = (csrf: string, p: string, d: string, j: string, body: Record<string, unknown>) => requestJson<ManifestState>(`${base(p, d)}/${encodeURIComponent(j)}/actions`, jsonMutation(csrf, body, "POST"))
