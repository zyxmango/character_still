import { createRouter, createWebHashHistory } from 'vue-router'
import PromptsView from '@/views/PromptsView.vue'
import StillsView from '@/views/StillsView.vue'
import EditView from '@/views/EditView.vue'
import PipelineView from '@/views/PipelineView.vue'
import TasksView from '@/views/TasksView.vue'
import GalleryView from '@/views/GalleryView.vue'
import PromptGuideView from '@/views/PromptGuideView.vue'
import MetricsView from '@/views/MetricsView.vue'

// 使用 hash 模式，避免后端 SPA fallback 配置
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/prompts' },
    { path: '/prompts', name: 'prompts', component: PromptsView, meta: { title: '提示词', icon: 'EditPen' } },
    { path: '/stills', name: 'stills', component: StillsView, meta: { title: '剧照', icon: 'Picture' } },
    { path: '/edit', name: 'edit', component: EditView, meta: { title: '修图', icon: 'MagicStick' } },
    { path: '/pipeline', name: 'pipeline', component: PipelineView, meta: { title: '全流程', icon: 'Connection' } },
    { path: '/tasks', name: 'tasks', component: TasksView, meta: { title: '任务', icon: 'Lightning' } },
    { path: '/gallery', name: 'gallery', component: GalleryView, meta: { title: '画廊', icon: 'Files' } },
    { path: '/guide', name: 'guide', component: PromptGuideView, meta: { title: '工程', icon: 'Document' } },
    { path: '/metrics', name: 'metrics', component: MetricsView, meta: { title: '监控', icon: 'Monitor' } },
  ],
})

export default router
