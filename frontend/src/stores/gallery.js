import { defineStore } from 'pinia'
import { imagesApi } from '@/api'

export const useGalleryStore = defineStore('gallery', {
  state: () => ({
    stills: { images: [], folders: [] },
    edited: { images: [], folders: [] },
    loaded: false,
    // 修图面板选中的图片
    editSelected: new Set(),
    // 画廊导出选中的图片（与修图选择分离）
    exportSelected: new Set(),
    // 图片预览：当前索引 + 预览列表（供 photoswipe 翻页）
    previewIndex: -1,
    previewList: [],
    previewSelectMode: false,
  }),
  getters: {
    previewSrc: (state) => {
      if (state.previewIndex < 0 || state.previewIndex >= state.previewList.length) return null
      return state.previewList[state.previewIndex].url
    },
  },
  actions: {
    async fetchImages() {
      try {
        const data = await imagesApi.list()
        this.stills = this._appendVersion(data.stills) || { images: [], folders: [] }
        this.edited = this._appendVersion(data.edited) || { images: [], folders: [] }
        this.loaded = true
      } catch (e) {
        console.error('获取图片列表失败:', e)
      }
    },
    // 给每张图片的 url 拼接 ?v=mtime，覆盖原图后强制浏览器刷新缓存
    _appendVersion(section) {
      if (!section) return section
      const stamp = (img) => ({ ...img, url: img.mtime ? `${img.url}?v=${img.mtime}` : img.url })
      return {
        images: (section.images || []).map(stamp),
        folders: (section.folders || []).map((f) => ({ ...f, images: (f.images || []).map(stamp) })),
      }
    },
    getAllImages() {
      const all = []
      ;(this.stills.images || []).forEach((img) => all.push({ ...img, source: 'stills' }))
      ;(this.stills.folders || []).forEach((f) => {
        f.images.forEach((img) => all.push({ ...img, source: `stills/${f.folder}`, folder: f.folder }))
      })
      ;(this.edited.images || []).forEach((img) => all.push({ ...img, source: 'edited' }))
      ;(this.edited.folders || []).forEach((f) => {
        f.images.forEach((img) => all.push({ ...img, source: `edited/${f.folder}`, folder: f.folder }))
      })
      return all
    },
    toggleEditSelect(path) {
      if (this.editSelected.has(path)) {
        this.editSelected.delete(path)
      } else {
        this.editSelected.add(path)
      }
    },
    clearEditSelect() {
      this.editSelected.clear()
    },
    // 批量选中一个文件夹/分组的所有图片
    selectFolderImages(urls) {
      this.editSelected = new Set([...this.editSelected, ...urls])
    },
    // 批量取消选中
    deselectFolderImages(urls) {
      const newSet = new Set(this.editSelected)
      urls.forEach((u) => newSet.delete(u))
      this.editSelected = newSet
    },
    // 判断是否全部已选
    isFolderAllSelected(urls) {
      return urls.length > 0 && urls.every((u) => this.editSelected.has(u))
    },
    // 判断是否部分已选（但非全部）
    isFolderAnySelected(urls) {
      return urls.some((u) => this.editSelected.has(u)) && !this.isFolderAllSelected(urls)
    },
    toggleExportSelect(path) {
      if (this.exportSelected.has(path)) {
        this.exportSelected.delete(path)
      } else {
        this.exportSelected.add(path)
      }
    },
    clearExportSelect() {
      this.exportSelected.clear()
    },
    // 导出选择：批量选中一个文件夹/分组的所有图片
    selectExportFolderImages(urls) {
      this.exportSelected = new Set([...this.exportSelected, ...urls])
    },
    // 导出选择：批量取消选中
    deselectExportFolderImages(urls) {
      const newSet = new Set(this.exportSelected)
      urls.forEach((u) => newSet.delete(u))
      this.exportSelected = newSet
    },
    // 导出选择：判断是否全部已选
    isExportFolderAllSelected(urls) {
      return urls.length > 0 && urls.every((u) => this.exportSelected.has(u))
    },
    // 导出选择：判断是否部分已选（但非全部）
    isExportFolderAnySelected(urls) {
      return urls.some((u) => this.exportSelected.has(u)) && !this.isExportFolderAllSelected(urls)
    },
    // 打开预览：可传 url（在当前列表中查找）或 { url, list }
    openPreview(url, list = null, selectMode = false) {
      const targetList = list || this.getAllImages()
      this.previewList = targetList
      this.previewSelectMode = selectMode
      const idx = targetList.findIndex((i) => i.url === url)
      this.previewIndex = idx >= 0 ? idx : 0
    },
    closePreview() {
      this.previewIndex = -1
      this.previewList = []
      this.previewSelectMode = false
    },
    async deleteFolder(section, folder) {
      await imagesApi.delete({ section, folder })
      await this.fetchImages()
    },
    async deleteImage(section, filename, folder = null) {
      await imagesApi.delete({ section, filename, folder })
      await this.fetchImages()
    },
  },
})
