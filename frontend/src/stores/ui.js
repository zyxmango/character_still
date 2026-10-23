import { defineStore } from 'pinia'

// 全局 UI 布局状态：侧边栏折叠、助手面板宽度等
export const useUiStore = defineStore('ui', {
  state: () => ({
    sidebarCollapsed: false, // 侧边栏折叠态（true=纯图标模式）
    assistantWidth: 360,     // 助手面板宽度（可拖拽调整）
  }),
  actions: {
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed
    },
    setAssistantWidth(w) {
      this.assistantWidth = Math.min(480, Math.max(280, w))
    },
  },
})
