import { defineStore } from 'pinia'
import { optionsApi, styleApi } from '@/api'

export const useOptionsStore = defineStore('options', {
  state: () => ({
    styles: [],
    statuses: [],
    specials: [],
    customStyles: [],  // 自定义风格列表
    comfyuiUrl: '',
    ollamaUrl: '',
    model: '',
    maxConcurrentTasks: 1,
    loaded: false,
  }),
  getters: {
    // 内置风格名（从 styles 中排除自定义风格名）
    builtinStyles: (state) => {
      const customNames = new Set(state.customStyles.map(s => s.style_name))
      return state.styles.filter(s => !customNames.has(s))
    },
  },
  actions: {
    async fetchOptions() {
      if (this.loaded) return
      try {
        const data = await optionsApi.get()
        this.styles = data.styles || []
        this.statuses = data.statuses || []
        this.specials = data.specials || []
        this.customStyles = data.custom_styles || []
        this.comfyuiUrl = data.comfyui_url
        this.ollamaUrl = data.ollama_url
        this.model = data.model
        this.maxConcurrentTasks = data.max_concurrent_tasks
        this.loaded = true
      } catch (e) {
        console.error('获取选项失败:', e)
      }
    },
    // 刷新自定义风格（创建/删除后调用）
    async refreshCustomStyles() {
      try {
        const data = await styleApi.list()
        this.customStyles = data.items || []
        // 合并到 styles 列表
        const customNames = new Set(this.customStyles.map(s => s.style_name))
        // 移除旧的自定义风格名，重新加上
        this.styles = [...this.styles.filter(s => !this._customStyleNamesOld.has(s))]
        this._customStyleNamesOld = customNames
        this.customStyles.forEach(s => {
          if (!this.styles.includes(s.style_name)) this.styles.push(s.style_name)
        })
      } catch (e) {
        console.error('刷新自定义风格失败:', e)
      }
    },
    _customStyleNamesOld: new Set(),
  },
})
