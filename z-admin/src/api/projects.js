import axios from 'axios'

export function listProjects() {
  return axios.get('/api/projects').then((res) => res.data)
}

export function createProject(data) {
  return axios.post('/api/projects', data).then((res) => res.data)
}

export function getProject(id) {
  return axios.get(`/api/projects/${encodeURIComponent(id)}`).then((res) => res.data)
}

export function updateProject(id, data) {
  return axios.put(`/api/projects/${encodeURIComponent(id)}`, data).then((res) => res.data)
}

export function deleteProject(id) {
  return axios.delete(`/api/projects/${encodeURIComponent(id)}`).then((res) => res.data)
}

// --- 内容库 Documents ---
export function listDocuments(projectId) {
  return axios.get(`/api/projects/${encodeURIComponent(projectId)}/documents`).then((res) => res.data)
}

export function createDocument(projectId, data) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/documents`, data, { timeout: 180000 }).then((res) => res.data)
}

export function deleteDocument(projectId, docId) {
  return axios.delete(`/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(docId)}`).then((res) => res.data)
}

export function transferAssetsFromDoc(projectId, docId) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(docId)}/transfer-assets`, null, { timeout: 180000 }).then((res) => res.data)
}

export function transferEpisodesFromDoc(projectId, docId) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(docId)}/transfer-episodes`, null, { timeout: 180000 }).then((res) => res.data)
}

// --- 资产库 Assets ---
export function listAssets(projectId, kind) {
  const url = kind
    ? `/api/projects/${encodeURIComponent(projectId)}/assets?kind=${encodeURIComponent(kind)}`
    : `/api/projects/${encodeURIComponent(projectId)}/assets`
  return axios.get(url).then((res) => res.data)
}

export function createAsset(projectId, data) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/assets`, data).then((res) => res.data)
}

export function generateCharacterContent(projectId, data) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/assets/generate-character-content`, data).then((res) => res.data)
}

export function updateAsset(projectId, assetId, data) {
  return axios.put(`/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}`, data).then((res) => res.data)
}

export function deleteAsset(projectId, assetId) {
  return axios.delete(`/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}`).then((res) => res.data)
}

export function generateAssetImage(projectId, assetId, data = {}) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/generate`, data).then((res) => res.data)
}

export function generateAssetImagesBatch(projectId, data = {}) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/assets/generate-batch`, data).then((res) => res.data)
}

export function enrichAssetLlm(projectId, assetId) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/enrich-llm`).then((res) => res.data)
}

// --- 剧集工坊 Episodes ---
export function listEpisodes(projectId) {
  return axios.get(`/api/projects/${encodeURIComponent(projectId)}/episodes`).then((res) => res.data)
}

export function createEpisode(projectId, data) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/episodes`, data).then((res) => res.data)
}

export function updateEpisode(projectId, epId, data) {
  return axios.put(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}`, data).then((res) => res.data)
}

export function deleteEpisode(projectId, epId) {
  return axios.delete(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}`).then((res) => res.data)
}

export function getEpisodeDetail(projectId, epId) {
  return axios.get(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}`).then((res) => res.data)
}

export function updateEpisodeBeat(projectId, epId, beatId, data) {
  return axios.put(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/beats/${encodeURIComponent(beatId)}`, data).then((res) => res.data)
}

export function generateBeatSketch(projectId, epId, beatId, data = {}) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/beats/${encodeURIComponent(beatId)}/generate-sketch`, data).then((res) => res.data)
}

export function generateBeatRender(projectId, epId, beatId, data = {}) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/beats/${encodeURIComponent(beatId)}/generate-render`, data).then((res) => res.data)
}

export function generateBeatImagesBatch(projectId, epId, data) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/generate-images`, data).then((res) => res.data)
}

export function generateEpisodeRequiredAssets(projectId, epId, data = {}) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/generate-required-assets`, data).then((res) => res.data)
}

export function generateEpisodeVideo(projectId, epId, data = {}) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/generate-video`, data).then((res) => res.data)
}

// --- 全部任务 Jobs ---
export function listJobs(projectId) {
  return axios.get(`/api/projects/${encodeURIComponent(projectId)}/jobs`).then((res) => res.data)
}

export function createJob(projectId, data) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/jobs`, data).then((res) => res.data)
}

export function retryJob(projectId, jobId) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(jobId)}/retry`).then((res) => res.data)
}

export function cancelAllJobs(projectId) {
  return axios.post(`/api/projects/${encodeURIComponent(projectId)}/jobs/cancel-all`).then((res) => res.data)
}

export function getJob(projectId, jobId) {
  return axios.get(`/api/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(jobId)}`).then((res) => res.data)
}

// --- H3 视频提示词 ---
export function generateBeatH3Prompt(projectId, epId, beatId, payload) {
  return axios
    .post(
      `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/beats/${encodeURIComponent(beatId)}/h3-prompt`,
      payload || {},
      { timeout: 180000 }
    )
    .then((res) => res.data)
}

