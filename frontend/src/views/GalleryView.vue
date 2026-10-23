<template>
  <div>
    <PageHeader icon="Files" title="图片画廊" desc="按文件夹浏览剧照与修图结果，勾选所需图片后一键导出打标文件">
      <template #actions>
        <el-button text size="small" @click="loadImages">刷新</el-button>
      </template>
    </PageHeader>

    <!-- 选中操作栏 -->
    <div class="select-bar" v-if="galleryStore.exportSelected.size > 0">
      <div class="select-info">
        <span class="select-count">已选 {{ galleryStore.exportSelected.size }} 张</span>
        <el-button text size="small" @click="galleryStore.clearExportSelect">清空选择</el-button>
      </div>
      <div class="select-actions">
        <el-button
          size="small"
          :loading="evaluating"
          @click="doEvaluateSelected"
        >
          <el-icon><DataAnalysis /></el-icon>
          质量评估（{{ galleryStore.exportSelected.size }} 张）
        </el-button>
        <el-button
          type="primary"
          size="small"
          :loading="exporting"
          @click="doExportSelected"
        >
          导出选中（{{ galleryStore.exportSelected.size }} 张）
        </el-button>
      </div>
    </div>

    <!-- 评估结果对话框 -->
    <el-dialog
      v-model="evalDialogVisible"
      title="出图质量评估结果"
      width="780px"
      :close-on-click-modal="false"
    >
      <div v-if="evalResult" class="eval-summary">
        <div class="eval-summary-row">
          <span class="eval-stat">共 <b>{{ evalResult.total }}</b> 张</span>
          <span class="eval-stat">平均分 <b :class="scoreClass(evalResult.average_score)">{{ evalResult.average_score }}</b></span>
          <span class="eval-stat">及格线 <b>{{ evalResult.threshold }}</b></span>
          <span class="eval-stat warn" v-if="evalResult.needs_regen_count > 0">
            需重出 <b>{{ evalResult.needs_regen_count }}</b> 张
          </span>
        </div>
        <div class="eval-table">
          <div class="eval-row eval-head">
            <span class="col-file">文件名</span>
            <span class="col-score">总分</span>
            <span class="col-dim">人物</span>
            <span class="col-dim">服饰</span>
            <span class="col-dim">颜色</span>
            <span class="col-dim">构图</span>
            <span class="col-dim">风格</span>
            <span class="col-status">状态</span>
          </div>
          <div v-for="e in evalResult.evaluations" :key="e.filename" class="eval-row" :class="{ bad: e.needs_regen }">
            <span class="col-file" :title="e.filename">{{ truncateName(e.filename, 24) }}</span>
            <span class="col-score" :class="scoreClass(e.score)">{{ e.score }}</span>
            <span class="col-dim">{{ e.dimensions?.['人物完整性'] ?? '-' }}</span>
            <span class="col-dim">{{ e.dimensions?.['服饰准确性'] ?? '-' }}</span>
            <span class="col-dim">{{ e.dimensions?.['颜色匹配度'] ?? '-' }}</span>
            <span class="col-dim">{{ e.dimensions?.['画面构图'] ?? '-' }}</span>
            <span class="col-dim">{{ e.dimensions?.['风格一致性'] ?? '-' }}</span>
            <span class="col-status">
              <el-tag v-if="e.needs_regen" type="danger" size="small">需重出</el-tag>
              <el-tag v-else type="success" size="small">合格</el-tag>
            </span>
          </div>
        </div>
        <div v-if="lowScoreList.length" class="eval-suggestions">
          <div class="sug-title">⚠️ 低分图片改进建议：</div>
          <div v-for="e in lowScoreList" :key="'sug-'+e.filename" class="sug-item">
            <div class="sug-file">{{ truncateName(e.filename, 28) }}（{{ e.score }} 分）</div>
            <div class="sug-text">{{ e.suggestion || '无建议' }}</div>
            <div v-if="e.issues && e.issues.length" class="sug-issues">
              问题：{{ e.issues.join('；') }}
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="evalDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 搜索筛选栏 -->
    <div class="filter-bar">
      <el-input
        v-model="searchFilterStore.keyword"
        placeholder="按文件名搜索..."
        :prefix-icon="Search"
        clearable
        size="default"
        class="kw-input"
      />
      <el-select v-model="searchFilterStore.section" placeholder="分区" size="default" class="sec-select">
        <el-option label="全部" value="all" />
        <el-option label="剧照" value="stills" />
        <el-option label="修图结果" value="edited" />
      </el-select>
      <span class="result-count">共 {{ totalImageCount }} 张</span>
    </div>

    <!-- 导出管理（自定义折叠面板，深色主题适配） -->
    <div v-if="exports.length > 0" class="export-panel">
      <div class="export-header" @click="exportOpen = !exportOpen">
        <div class="export-title">
          <span class="export-icon">📦</span>
          <span>导出管理</span>
          <span class="export-sub">打标 Excel · 入库 SQL</span>
        </div>
        <span class="export-toggle">{{ exportOpen ? '收起' : '展开' }}</span>
      </div>
      <div v-if="exportOpen" class="export-body">
        <div v-for="f in exports" :key="f.filename" class="export-item">
          <span class="export-file-icon">{{ f.filename.endsWith('.sql') ? '🗄' : '📊' }}</span>
          <a :href="f.url" :download="f.filename" class="export-link">{{ f.filename }}</a>
          <span class="export-size">{{ formatSize(f.size) }}</span>
          <a :href="f.url" :download="f.filename" class="export-download" title="下载">↓</a>
        </div>
      </div>
    </div>

    <div v-if="loading" class="empty-state"><div class="text">加载中...</div></div>

    <!-- 按分区 + 文件夹分组展示 -->
    <template v-else>
      <template v-for="sec in sections" :key="sec.key">
        <template v-if="shouldShowSection(sec.key)">
          <h4 class="section-title">
            {{ sec.label }}
            <span class="section-count">({{ getSectionTotal(sec.key) }})</span>
          </h4>

          <!-- 文件夹列表 -->
          <div
            v-for="folder in getFilteredFolders(sec.key)"
            :key="sec.key + '/' + folder.folder"
            class="folder-card"
          >
            <div class="folder-header" @click="toggleFolder(sec.key + '/' + folder.folder)">
              <span class="folder-icon">📁</span>
              <div class="folder-info">
                <div class="folder-name">{{ folder.folder }}</div>
                <div class="folder-meta">{{ folder.count }} 张 · {{ formatTime(folder.mtime) }}</div>
              </div>
              <el-checkbox
                class="folder-select-all"
                :model-value="galleryStore.isExportFolderAllSelected(folderImagesUrls(folder.images))"
                :indeterminate="galleryStore.isExportFolderAnySelected(folderImagesUrls(folder.images))"
                @change="toggleExportFolderSelectAll(folder.images, $event)"
                @click.stop
                title="全选/取消全选该文件夹"
              >全选</el-checkbox>
              <el-button
                class="folder-del-btn"
                link
                size="small"
                type="danger"
                @click.stop="confirmDeleteFolder(sec.key, folder.folder)"
                title="删除整个文件夹"
              >
                <el-icon><Delete /></el-icon>
              </el-button>
              <span class="folder-toggle">{{ openFolders.has(sec.key + '/' + folder.folder) ? '▾' : '▸' }}</span>
            </div>
            <div v-if="openFolders.has(sec.key + '/' + folder.folder)" class="folder-body">
              <div class="gallery-grid">
                <div
                  v-for="img in folder.images"
                  :key="img.url"
                  class="gallery-item"
                  :class="{ selected: galleryStore.exportSelected.has(img.url) }"
                >
                  <div class="img-wrap" @click="openPreview(img, sec.key, folder.folder)">
                    <img :src="img.url" :alt="img.filename" loading="lazy" />
                    <div class="hover-mask">
                      <span class="zoom-icon">🔍</span>
                      <span>点击放大预览</span>
                    </div>
                  </div>
                  <div
                    class="img-check"
                    :class="{ checked: galleryStore.exportSelected.has(img.url) }"
                    @click.stop="galleryStore.toggleExportSelect(img.url)"
                  >
                    <svg v-if="galleryStore.exportSelected.has(img.url)" viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 8 7 12 13 4"/></svg>
                  </div>
                  <div class="gallery-meta">
                    <div class="meta-name" :title="img.filename">{{ truncateName(img.filename) }}</div>
                    <div class="meta-sub">
                      <span class="meta-time">{{ formatTime(img.mtime) }}</span>
                    </div>
                  </div>
                  <!-- hover 操作栏 -->
                  <div class="hover-actions">
                    <a class="hover-btn" title="下载" :href="img.url" :download="img.filename" @click.stop><el-icon><Download /></el-icon></a>
                    <span class="hover-btn danger" title="删除" @click.stop="confirmDeleteImage(img, sec.key, folder.folder)"><el-icon><Delete /></el-icon></span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 未归档散图 -->
          <div v-if="getFilteredScattered(sec.key).length > 0">
            <div
              class="folder-header unarchived-header"
              @click="toggleFolder(sec.key + '/__unarchived__')"
            >
              <span class="folder-icon">📄</span>
              <div class="folder-info">
                <div class="folder-name">未归档图片</div>
                <div class="folder-meta">{{ getFilteredScattered(sec.key).length }} 张</div>
              </div>
              <el-checkbox
                class="folder-select-all"
                :model-value="galleryStore.isExportFolderAllSelected(folderImagesUrls(getFilteredScattered(sec.key)))"
                :indeterminate="galleryStore.isExportFolderAnySelected(folderImagesUrls(getFilteredScattered(sec.key)))"
                @change="toggleExportFolderSelectAll(getFilteredScattered(sec.key), $event)"
                @click.stop
                title="全选/取消全选未归档图片"
              >全选</el-checkbox>
              <span class="folder-toggle">{{ openFolders.has(sec.key + '/__unarchived__') ? '▾' : '▸' }}</span>
            </div>
            <div v-if="openFolders.has(sec.key + '/__unarchived__')" class="folder-body">
              <div class="gallery-grid">
                <div
                  v-for="img in getFilteredScattered(sec.key)"
                  :key="img.url"
                  class="gallery-item"
                  :class="{ selected: galleryStore.exportSelected.has(img.url) }"
                >
                  <div class="img-wrap" @click="openPreview(img, sec.key, null)">
                    <img :src="img.url" :alt="img.filename" loading="lazy" />
                    <div class="hover-mask">
                      <span class="zoom-icon">🔍</span>
                      <span>点击放大预览</span>
                    </div>
                  </div>
                  <div
                    class="img-check"
                    :class="{ checked: galleryStore.exportSelected.has(img.url) }"
                    @click.stop="galleryStore.toggleExportSelect(img.url)"
                  >
                    <svg v-if="galleryStore.exportSelected.has(img.url)" viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 8 7 12 13 4"/></svg>
                  </div>
                  <div class="gallery-meta">
                    <div class="meta-name" :title="img.filename">{{ truncateName(img.filename) }}</div>
                    <div class="meta-sub">
                      <span class="meta-time">{{ formatTime(img.mtime) }}</span>
                    </div>
                  </div>
                  <div class="hover-actions">
                    <a class="hover-btn" title="下载" :href="img.url" :download="img.filename" @click.stop><el-icon><Download /></el-icon></a>
                    <span class="hover-btn danger" title="删除" @click.stop="confirmDeleteImage(img, sec.key, null)"><el-icon><Delete /></el-icon></span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>
      </template>

      <!-- 空状态 -->
      <div v-if="totalImageCount === 0" class="empty-state">
        <div class="icon">📭</div>
        <div class="text">{{ searchFilterStore.keyword ? '未匹配到图片' : '暂无图片' }}</div>
      </div>
    </template>

    <div class="hint-text">
      💡 操作提示：点击<strong class="hl">文件夹标题</strong>展开/折叠 · 点击<strong class="hl">全选复选框</strong>一次性选中整个文件夹 · 点击<strong class="hl">🗑</strong>删除整个文件夹 · 点击<strong class="hl">图片</strong>放大预览 · 点击<strong class="hl">右上角复选框</strong>勾选 · 勾选后点<strong class="hl">导出选中</strong>生成打标文件
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Download, Delete, DataAnalysis } from '@element-plus/icons-vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { useGalleryStore } from '@/stores/gallery'
import { useSearchFilterStore } from '@/stores/searchFilter'
import { exportApi, evaluateApi } from '@/api'

const galleryStore = useGalleryStore()
const searchFilterStore = useSearchFilterStore()

const exports = ref([])
const exportOpen = ref(false)
const loading = ref(false)
const exporting = ref(false)
// 质量评估
const evaluating = ref(false)
const evalDialogVisible = ref(false)
const evalResult = ref(null)

const lowScoreList = computed(() => {
  if (!evalResult.value?.evaluations) return []
  return evalResult.value.evaluations.filter((e) => e.needs_regen)
})

const scoreClass = (score) => {
  if (!score && score !== 0) return ''
  if (score >= 85) return 'score-excellent'
  if (score >= 70) return 'score-good'
  if (score >= 50) return 'score-fair'
  return 'score-bad'
}

// 文件夹展开/折叠状态
const openFolders = reactive(new Set())

const sections = [
  { key: 'stills', label: '🖼️ 剧照' },
  { key: 'edited', label: '✨ 修图结果' },
]

onMounted(async () => {
  loading.value = true
  await galleryStore.fetchImages()
  loading.value = false
  await refreshExports()
})

const loadImages = async () => {
  loading.value = true
  await galleryStore.fetchImages()
  loading.value = false
}

const refreshExports = async () => {
  try {
    const list = await exportApi.list()
    exports.value = [...(list.excel || []), ...(list.sql || [])]
  } catch (e) {
    console.error('获取导出列表失败:', e)
  }
}

// 搜索关键词
const kw = computed(() => searchFilterStore.keyword.trim().toLowerCase())

// 是否显示该分区
const shouldShowSection = (key) => {
  if (searchFilterStore.section !== 'all' && searchFilterStore.section !== key) return false
  return getSectionTotal(key) > 0
}

// 过滤文件夹
const getFilteredFolders = (key) => {
  const folders = galleryStore[key].folders || []
  if (!kw.value) return folders
  return folders
    .map((f) => ({
      ...f,
      images: f.images.filter((img) => (img.filename || '').toLowerCase().includes(kw.value)),
    }))
    .filter((f) => f.images.length > 0)
}

// 过滤散图
const getFilteredScattered = (key) => {
  const images = galleryStore[key].images || []
  if (!kw.value) return images
  return images.filter((img) => (img.filename || '').toLowerCase().includes(kw.value))
}

const getSectionTotal = (key) => {
  return getFilteredScattered(key).length + getFilteredFolders(key).reduce((s, f) => s + f.images.length, 0)
}

const totalImageCount = computed(() => {
  if (searchFilterStore.section === 'all') {
    return getSectionTotal('stills') + getSectionTotal('edited')
  }
  return getSectionTotal(searchFilterStore.section)
})

const toggleFolder = (id) => {
  if (openFolders.has(id)) {
    openFolders.delete(id)
  } else {
    openFolders.add(id)
  }
}

// 提取图片 url 列表
const folderImagesUrls = (images) => (images || []).map((i) => i.url)

// 导出选择：全选/取消全选一个文件夹（或未归档分组）
const toggleExportFolderSelectAll = (images, checked) => {
  const urls = folderImagesUrls(images)
  if (checked) {
    galleryStore.selectExportFolderImages(urls)
  } else {
    galleryStore.deselectExportFolderImages(urls)
  }
}

const formatTime = (ts) => (ts ? dayjs(ts * 1000).format('MM-DD HH:mm') : '')

const formatSize = (bytes) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

const truncateName = (name, len = 18) => {
  if (!name) return ''
  if (name.length <= len) return name
  const dot = name.lastIndexOf('.')
  const ext = dot >= 0 ? name.slice(dot) : ''
  const base = dot >= 0 ? name.slice(0, dot) : name
  return base.slice(0, len - ext.length - 1) + '…' + ext
}

const openPreview = (img, section, folder) => {
  // 构建当前可见图片列表用于翻页
  const list = []
  if (folder) {
    const f = (galleryStore[section].folders || []).find((x) => x.folder === folder)
    if (f) f.images.forEach((i) => list.push({ ...i, source: `${section}/${folder}` }))
  } else {
    ;(galleryStore[section].images || []).forEach((i) => list.push({ ...i, source: section }))
  }
  galleryStore.openPreview(img.url, list)
}

// 导出选中的图片
const doExportSelected = async () => {
  if (galleryStore.exportSelected.size === 0) {
    ElMessage.warning('请先勾选图片')
    return
  }
  exporting.value = true
  try {
    // 从 URL 提取文件名
    const filenames = Array.from(galleryStore.exportSelected).map((url) => {
      // url 形如 /files/stills/120/abc.png?v=123 或 /files/stills/abc.png?v=123
      const cleanUrl = url.split('?')[0]
      const parts = cleanUrl.split('/')
      return parts[parts.length - 1]
    })
    const data = await exportApi.exportByImages(filenames)
    let msg = `导出成功：匹配 ${data.count}/${data.total_selected} 个角色`
    if (data.not_found && data.not_found.length > 0) {
      msg += `，${data.not_found.length} 个未在 prompts 中找到`
    }
    ElMessage.success(msg)
    await refreshExports()
    galleryStore.clearExportSelect()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    exporting.value = false
  }
}

// 质量评估选中的图片
const doEvaluateSelected = async () => {
  if (galleryStore.exportSelected.size === 0) {
    ElMessage.warning('请先勾选图片')
    return
  }
  evaluating.value = true
  try {
    const filenames = Array.from(galleryStore.exportSelected).map((url) => {
      const cleanUrl = url.split('?')[0]
      const parts = cleanUrl.split('/')
      return parts[parts.length - 1]
    })
    ElMessage.info(`正在评估 ${filenames.length} 张图片，请稍候...`)
    const data = await evaluateApi.evaluate(filenames, 70)
    if (data.result?.error) {
      ElMessage.error(data.result.error)
      return
    }
    evalResult.value = data.result
    evalDialogVisible.value = true
    if (data.result?.needs_regen_count > 0) {
      ElMessage.warning(`评估完成：${data.result.needs_regen_count} 张需重出`)
    } else {
      ElMessage.success(`评估完成：平均 ${data.result.average_score} 分`)
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    evaluating.value = false
  }
}

// 删除单张图片
const confirmDeleteImage = async (img, section, folder) => {
  try {
    await ElMessageBox.confirm(
      `确定删除「${img.filename}」？此操作不可恢复。`,
      '删除图片',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await galleryStore.deleteImage(section, img.filename, folder)
    // 同步移除选中状态
    galleryStore.exportSelected.delete(img.url)
    galleryStore.editSelected.delete(img.url)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

// 删除整个文件夹
const confirmDeleteFolder = async (section, folder) => {
  try {
    await ElMessageBox.confirm(
      `确定删除整个文件夹「${folder}」？该文件夹下的所有图片将被永久删除，不可恢复。`,
      '删除文件夹',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    // 先从已选中集合中移除该文件夹下所有图片 url
    const folderData = (galleryStore[section].folders || []).find((f) => f.folder === folder)
    if (folderData) {
      folderData.images.forEach((img) => {
        galleryStore.exportSelected.delete(img.url)
        galleryStore.editSelected.delete(img.url)
      })
    }
    await galleryStore.deleteFolder(section, folder)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}
</script>

<style scoped>
/* 选中操作栏 */
.select-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  margin-bottom: 16px;
  background: var(--surface);
  border: 1px solid var(--accent);
  border-radius: var(--radius-card);
  box-shadow: 0 0 0 1px rgba(var(--accent-rgb, 200, 168, 130), 0.15);
}

.select-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.select-count {
  font-size: 14px;
  color: var(--accent);
  font-weight: 500;
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.kw-input {
  flex: 1;
  min-width: 200px;
  max-width: 320px;
}

.sec-select {
  width: 120px;
}

.result-count {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-muted);
}

/* 分区标题 */
.section-title {
  font-family: var(--font-serif);
  margin: 18px 0 10px;
  color: var(--accent);
  font-weight: 500;
  letter-spacing: 1px;
  font-size: 14px;
}
.section-count {
  color: var(--text-muted);
  font-size: 12px;
}

/* 文件夹卡片 */
.folder-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  margin-bottom: 12px;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.folder-header {
  padding: 12px 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 10px;
  transition: background var(--transition);
}
.folder-header:hover {
  background: var(--surface-hover);
}
.unarchived-header {
  margin-top: 8px;
  border-radius: var(--radius-card);
  background: var(--surface);
  border: 1px dashed var(--border);
}
.folder-icon {
  font-size: 20px;
}
.folder-info {
  flex: 1;
}
.folder-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
}
.folder-meta {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}
.folder-toggle {
  color: var(--text-muted);
  font-size: 12px;
}
.folder-select-all {
  margin-right: 8px;
  cursor: pointer;
  user-select: none;
}
.folder-select-all :deep(.el-checkbox__label) {
  font-size: 12px;
  padding-left: 6px;
}
.folder-del-btn {
  margin-right: 4px;
  padding: 4px;
  opacity: 0;
  transition: opacity var(--transition);
}
.folder-header:hover .folder-del-btn {
  opacity: 1;
}
.folder-body {
  padding: 10px 16px;
  border-top: 1px solid var(--border);
}

/* 导出管理面板 */
.export-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  margin-bottom: 16px;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.export-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  cursor: pointer;
  transition: background var(--transition);
  user-select: none;
}
.export-header:hover {
  background: var(--surface-hover);
}
.export-title {
  display: flex;
  align-items: center;
  gap: 10px;
}
.export-icon {
  font-size: 18px;
}
.export-title > span:nth-child(2) {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
}
.export-sub {
  font-size: 12px;
  color: var(--text-dim);
  padding: 2px 8px;
  background: var(--surface-active);
  border-radius: var(--radius);
  letter-spacing: 0.5px;
}
.export-toggle {
  font-size: 12px;
  color: var(--accent);
}
.export-body {
  border-top: 1px solid var(--border);
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.export-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--bg-2);
  border-radius: var(--radius);
  border: 1px solid var(--border);
  transition: border-color var(--transition), background var(--transition);
}
.export-item:hover {
  border-color: var(--border-light);
  background: var(--surface-hover);
}
.export-file-icon {
  font-size: 16px;
  flex-shrink: 0;
}
.export-link {
  flex: 1;
  color: var(--text);
  text-decoration: none;
  font-size: 13px;
  transition: color var(--transition);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.export-link:hover {
  color: var(--accent);
}
.export-size {
  font-size: 11px;
  color: var(--text-dim);
  flex-shrink: 0;
}
.export-download {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--surface-active);
  color: var(--text-muted);
  text-decoration: none;
  font-size: 14px;
  transition: all var(--transition);
  flex-shrink: 0;
}
.export-download:hover {
  background: var(--accent);
  color: var(--bg);
}

/* 图片网格 */
.gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 14px;
  padding: 6px 0;
}

.gallery-item {
  position: relative;
  border: 1.5px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  background: var(--surface-2);
  transition: all 0.2s ease;
}
.gallery-item:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0,0,0,0.35);
}
.gallery-item.selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(200,65,44,0.25), 0 8px 20px rgba(200,65,44,0.15);
}

.img-wrap {
  position: relative;
  cursor: zoom-in;
  overflow: hidden;
}
.img-wrap img {
  width: 100%;
  height: 200px;
  object-fit: cover;
  display: block;
  transition: transform 0.3s ease;
}
.gallery-item:hover .img-wrap img {
  transform: scale(1.04);
}
.hover-mask {
  position: absolute;
  inset: 0;
  background: linear-gradient(to top, rgba(0,0,0,0.6) 0%, transparent 60%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  padding-bottom: 16px;
  gap: 6px;
  color: white;
  font-size: 12px;
  opacity: 0;
  transition: opacity 0.2s;
}
.gallery-item:hover .hover-mask {
  opacity: 1;
}
.zoom-icon { font-size: 20px; }

/* 勾选框 */
.img-check {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: rgba(20,15,13,0.85);
  color: white;
  border: 1.5px solid rgba(255,255,255,0.5);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
  backdrop-filter: blur(4px);
  z-index: 2;
}
.img-check:hover {
  transform: scale(1.1);
  border-color: var(--accent);
}
.img-check.checked {
  background: var(--primary);
  border-color: var(--primary);
  box-shadow: 0 2px 8px rgba(200,65,44,0.5);
}

.gallery-meta {
  padding: 6px 10px;
  font-size: 11px;
  color: var(--text-muted);
  background: var(--surface);
  border-top: 1px solid var(--border);
  line-height: 1.4;
}
.meta-name {
  color: var(--text);
  font-size: 12px;
  margin-bottom: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.meta-sub {
  display: flex;
  align-items: center;
  gap: 6px;
}
.meta-time {
  color: var(--text-dim);
  font-size: 10px;
}

/* hover 操作栏 */
.hover-actions {
  position: absolute;
  top: 8px;
  left: 8px;
  display: flex;
  gap: 6px;
  opacity: 0;
  transition: opacity var(--transition);
  z-index: 2;
}
.gallery-item:hover .hover-actions {
  opacity: 1;
}
.hover-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: rgba(20, 15, 13, 0.85);
  color: white;
  font-size: 14px;
  cursor: pointer;
  transition: all var(--transition);
  backdrop-filter: blur(4px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  text-decoration: none;
}
.hover-btn:hover {
  background: var(--accent);
  transform: scale(1.1);
}
.hover-btn.danger:hover {
  background: var(--error);
}

/* 空状态 */
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-muted);
}
.empty-state .icon {
  font-size: 48px;
  margin-bottom: 12px;
}
.empty-state .text {
  font-size: 14px;
}

/* 提示文本 */
.hint-text {
  font-size: 12px;
  line-height: 1.8;
  color: var(--text-muted);
  padding: 12px 16px;
  margin-top: 16px;
  background: var(--surface);
  border-radius: 8px;
  border-left: 3px solid var(--accent);
}
.hint-text .hl {
  color: var(--accent);
  font-weight: 600;
}

/* 选中操作栏右侧按钮组 */
.select-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* 评估结果样式 */
.eval-summary {
  margin: -10px 0;
}
.eval-summary-row {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  padding: 10px 14px;
  background: var(--surface);
  border-radius: 8px;
  margin-bottom: 14px;
  font-size: 14px;
}
.eval-stat {
  color: var(--text-muted);
}
.eval-stat b {
  color: var(--text);
  margin-left: 4px;
  font-size: 16px;
}
.eval-stat.warn b {
  color: var(--el-color-danger, #f56c6c);
}
.score-excellent { color: #67c23a; font-weight: 700; }
.score-good { color: #409eff; font-weight: 600; }
.score-fair { color: #e6a23c; font-weight: 600; }
.score-bad { color: #f56c6c; font-weight: 700; }

.eval-table {
  border: 1px solid var(--border, rgba(255,255,255,0.08));
  border-radius: 8px;
  overflow: hidden;
  font-size: 13px;
  max-height: 320px;
  overflow-y: auto;
}
.eval-row {
  display: grid;
  grid-template-columns: 1.6fr 0.6fr 0.5fr 0.5fr 0.5fr 0.5fr 0.5fr 0.8fr;
  gap: 6px;
  padding: 8px 12px;
  align-items: center;
  border-bottom: 1px solid var(--border, rgba(255,255,255,0.05));
}
.eval-row:last-child { border-bottom: none; }
.eval-head {
  background: var(--surface);
  font-weight: 600;
  color: var(--text-muted);
  position: sticky;
  top: 0;
  z-index: 1;
}
.eval-row.bad {
  background: rgba(245, 108, 108, 0.06);
}
.col-file {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.col-score, .col-dim {
  text-align: center;
}
.col-status {
  text-align: center;
}

.eval-suggestions {
  margin-top: 16px;
  padding: 12px 14px;
  background: rgba(230, 162, 60, 0.06);
  border: 1px solid rgba(230, 162, 60, 0.25);
  border-radius: 8px;
}
.sug-title {
  font-weight: 600;
  color: #e6a23c;
  margin-bottom: 8px;
  font-size: 13px;
}
.sug-item {
  padding: 6px 0;
  border-top: 1px dashed rgba(230, 162, 60, 0.2);
  font-size: 12px;
}
.sug-item:first-of-type { border-top: none; }
.sug-file {
  font-weight: 600;
  color: var(--text);
}
.sug-text {
  color: var(--text-muted);
  margin-top: 2px;
}
.sug-issues {
  color: var(--el-color-danger, #f56c6c);
  margin-top: 2px;
}
</style>
