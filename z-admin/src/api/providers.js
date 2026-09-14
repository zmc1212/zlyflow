import axios from 'axios'

const http = axios.create({
  baseURL: '',
  timeout: 30000,
})

// --- ComfyUI ---
export const getComfyConfig = () => http.get('/api/admin/providers/comfy').then(res => res.data)
export const updateComfyConfig = (baseUrl) => http.put('/api/admin/providers/comfy', { base_url: baseUrl }).then(res => res.data)
export const testComfyConnection = (baseUrl) => http.post('/api/admin/providers/comfy/test', { base_url: baseUrl }).then(res => res.data)

// --- GRS ---
export const getGrsConfig = () => http.get('/api/admin/providers/grs').then(res => res.data)
export const updateGrsConfig = (data) => http.put('/api/admin/providers/grs', data).then(res => res.data)
export const testGrsConnection = (data) => http.post('/api/admin/providers/grs/test', data || {}).then(res => res.data)
export const queryGrsBalance = () => http.post('/api/admin/providers/grs/balance').then(res => res.data)
export const getGrsModels = () => http.get('/api/admin/providers/grs/models').then(res => res.data)
export const updateGrsModels = (models) => http.put('/api/admin/providers/grs/models', { models }).then(res => res.data)
export const createGrsModel = (model) => http.post('/api/admin/providers/grs/models', model).then(res => res.data)

// --- LLM ---
export const getLlmConfig = () => http.get('/api/admin/providers/llm').then(res => res.data)
export const updateLlmConfig = (data) => http.put('/api/admin/providers/llm', data).then(res => res.data)
export const testLlmConnection = (data) => http.post('/api/admin/providers/llm/test', data || {}).then(res => res.data)
export const listLlmModels = (data) => http.post('/api/admin/providers/llm/models', data || {}).then(res => res.data)

// --- Qiniu Storage ---
export const getQiniuConfig = () => http.get('/api/admin/providers/qiniu').then(res => res.data)
export const updateQiniuConfig = (data) => http.put('/api/admin/providers/qiniu', data).then(res => res.data)
export const testQiniuConnection = (data) => http.post('/api/admin/providers/qiniu/test', data || {}).then(res => res.data)
