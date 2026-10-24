import { jsonMutation, requestJson } from "../../api"
import type { Capabilities, Diagnosis, DiagnosisSummary, Source } from "./model"

const BASE = "/api/script-diagnoses"
export const getCapabilities = () => requestJson<Capabilities>(BASE + "/capabilities")
export const getDiagnosis = (id: string) => requestJson<Diagnosis>(BASE + "/" + encodeURIComponent(id))
export const getDocumentSource = (projectId: string, documentId: string) =>
  requestJson<{ title: string; sources: Source[] }>(BASE + "/source-document?" + new URLSearchParams({
    project_id: projectId, document_id: documentId,
  }))
export const listDiagnoses = (page: number, documentId?: string | null) => {
  const params = new URLSearchParams({ offset: String((page - 1) * 10), limit: "10" })
  if (documentId) params.set("document_id", documentId)
  return requestJson<{ items: DiagnosisSummary[]; total: number }>(BASE + "?" + params)
}
export const createDiagnosis = (csrf: string, payload: Record<string, unknown>) =>
  requestJson<Diagnosis>(BASE, jsonMutation(csrf, payload))
export const cancelDiagnosis = (csrf: string, id: string) =>
  requestJson<Diagnosis>(BASE + "/" + encodeURIComponent(id) + "/cancel", jsonMutation(csrf))
export const retryDiagnosis = (csrf: string, id: string, key: string) =>
  requestJson<Diagnosis>(BASE + "/" + encodeURIComponent(id) + "/retry", jsonMutation(csrf, { client_request_id: key }))
export const deleteDiagnosis = (csrf: string, id: string) =>
  requestJson(BASE + "/" + encodeURIComponent(id), jsonMutation(csrf, undefined, "DELETE"))
export const extractFiles = (csrf: string, files: File[]) => {
  const body = new FormData()
  files.forEach(file => body.append("files", file))
  return requestJson<{ sources: { name: string; text?: string; error?: string }[] }>(BASE + "/extract", {
    method: "POST", headers: { "X-CSRF-Token": csrf }, body,
  })
}
