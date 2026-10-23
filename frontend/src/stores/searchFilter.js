import { defineStore } from 'pinia'

// 画廊/修图/任务统一搜索筛选状态
export const useSearchFilterStore = defineStore('searchFilter', {
  state: () => ({
    keyword: '',           // 关键词
    section: 'all',        // all / stills / edited
    style: '',             // 风格筛选
    sort: 'newest',        // newest / oldest / name
    viewMode: 'masonry',   // masonry / grid / list
    page: 1,
    pageSize: 50,
  }),
  actions: {
    setKeyword(kw) {
      this.keyword = kw
      this.page = 1
    },
    setSection(s) {
      this.section = s
      this.page = 1
    },
    setStyle(s) {
      this.style = s
      this.page = 1
    },
    setSort(s) {
      this.sort = s
      this.page = 1
    },
    setViewMode(m) {
      this.viewMode = m
    },
    nextPage() {
      this.page++
    },
    reset() {
      this.keyword = ''
      this.section = 'all'
      this.style = ''
      this.sort = 'newest'
      this.viewMode = 'masonry'
      this.page = 1
    },
  },
})
