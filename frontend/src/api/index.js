import axios from 'axios'

const api = axios.create({
  baseURL: '',
  timeout: 30000,
})

// 响应拦截：统一错误处理（v2.2 起无登录态，401 由业务自行处理）
api.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(error)
)

// ===== 选项 =====
export const optionsApi = {
  get: () => api.get('/api/options'),
}

// ===== 图片列表 =====
export const imagesApi = {
  list: () => api.get('/api/list_images'),
  delete: (data) => api.delete('/api/images', { data }),
}

// ===== 任务 =====
export const tasksApi = {
  submit: (task_type, args) => api.post('/api/tasks', { task_type, args }),
  get: (id) => api.get(`/api/tasks/${id}`),
  list: (limit = 50) => api.get(`/api/tasks?limit=${limit}`),
  cancel: (id) => api.post(`/api/tasks/${id}/cancel`),
}

// ===== Prompts 文件（供筛选后导出）=====
export const promptsApi = {
  list: () => api.get('/api/prompts/list'),
  characters: (file) => api.get('/api/prompts/characters', { params: { file } }),
}

// ===== 导出 =====
export const exportApi = {
  export: (file, selectedNames) => api.post('/api/export', { file, selected_names: selectedNames }),
  exportByImages: (imageFilenames) => api.post('/api/export/by_images', { image_filenames: imageFilenames }),
  list: () => api.get('/api/export/list'),
}

// ===== 任务模板 =====
export const templateApi = {
  list: () => api.get('/api/templates'),
  create: (data) => api.post('/api/templates', data),
  delete: (id) => api.delete(`/api/templates/${id}`),
}

// ===== 提示词工程配置（md 文档）=====
export const promptGuideApi = {
  get: () => api.get('/api/prompt-guide'),
  validate: (content) => api.post('/api/prompt-guide/validate', { content }),
  save: (content) => api.put('/api/prompt-guide', { content }),
  reload: () => api.post('/api/prompt-guide/reload'),
  restore: () => api.post('/api/prompt-guide/restore'),
}

// ===== 自定义风格 =====
export const styleApi = {
  list: () => api.get('/api/styles'),
  create: (data) => api.post('/api/styles', data),
  delete: (id) => api.delete(`/api/styles/${id}`),
}

// ===== 出图质量评估 =====
export const evaluateApi = {
  evaluate: (imageFilenames, threshold) => api.post('/api/evaluate', {
    image_filenames: imageFilenames,
    threshold,
  }),
}

// ===== 系统监控 =====
export const metricsApi = {
  get: () => api.get('/api/metrics'),
}

export default api
