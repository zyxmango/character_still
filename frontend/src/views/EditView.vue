<template>
  <div>
    <PageHeader icon="MagicStick" title="修图" desc="点击文件夹展开图片，再点击缩略图放大预览或勾选" />

    <div class="app-card">
      <div class="app-card-title">
        图片选择（先展开文件夹，再勾选图片）
        <div style="margin-left: auto; display: flex; gap: 8px; align-items: center">
          <el-tag type="info" size="small" effect="plain" v-if="galleryStore.editSelected.size > 0">
            已选 {{ galleryStore.editSelected.size }} 张
          </el-tag>
          <el-button text size="small" @click="galleryStore.clearEditSelect" v-if="galleryStore.editSelected.size > 0">
            清空选择
          </el-button>
          <el-button text size="small" @click="loadImages">刷新图片</el-button>
        </div>
      </div>

      <div v-if="loading" class="edit-empty">加载中...</div>
      <div v-else-if="allImages.length === 0" class="edit-empty">暂无图片，请先去生成剧照</div>

      <template v-else>
        <!-- 按分区（剧照/修图结果）展示文件夹 -->
        <template v-for="sec in sections" :key="sec.key">
          <h4 v-if="getSectionTotal(sec.key) > 0" class="section-title">
            {{ sec.label }}
            <span class="section-count">({{ getSectionTotal(sec.key) }})</span>
          </h4>

          <!-- 文件夹列表 -->
          <div
            v-for="folder in (galleryStore[sec.key].folders || [])"
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
                :model-value="galleryStore.isFolderAllSelected(folderImagesUrls(folder.images))"
                :indeterminate="galleryStore.isFolderAnySelected(folderImagesUrls(folder.images))"
                @change="toggleFolderSelectAll(folder.images, $event)"
                @click.stop
                title="全选/取消全选该文件夹"
              >全选</el-checkbox>
              <span class="folder-toggle">{{ openFolders.has(sec.key + '/' + folder.folder) ? '▾' : '▸' }}</span>
            </div>
            <div v-if="openFolders.has(sec.key + '/' + folder.folder)" class="folder-body">
              <div class="edit-grid">
                <div
                  v-for="img in folder.images"
                  :key="img.url"
                  class="edit-img-item"
                  :class="{ selected: galleryStore.editSelected.has(img.url) }"
                >
                  <div class="img-wrap" @click="openPreviewByUrl(img.url)">
                    <img :src="img.url" :alt="img.filename" />
                    <div class="hover-mask">
                      <span class="zoom-icon">🔍</span>
                      <span>点击放大预览</span>
                    </div>
                  </div>
                  <div
                    class="edit-check"
                    :class="{ checked: galleryStore.editSelected.has(img.url) }"
                    @click.stop="galleryStore.toggleEditSelect(img.url)"
                  >
                    <svg v-if="galleryStore.editSelected.has(img.url)" viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 8 7 12 13 4"/></svg>
                  </div>
                  <div class="edit-name" :title="img.filename">{{ truncateName(img.filename) }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 未归档散图 -->
          <div v-if="(galleryStore[sec.key].images || []).length > 0">
            <div
              class="folder-header unarchived-header"
              @click="toggleFolder(sec.key + '/__unarchived__')"
            >
              <span class="folder-icon">📄</span>
              <div class="folder-info">
                <div class="folder-name">未归档图片</div>
                <div class="folder-meta">{{ galleryStore[sec.key].images.length }} 张</div>
              </div>
              <el-checkbox
                class="folder-select-all"
                :model-value="galleryStore.isFolderAllSelected(folderImagesUrls(galleryStore[sec.key].images))"
                :indeterminate="galleryStore.isFolderAnySelected(folderImagesUrls(galleryStore[sec.key].images))"
                @change="toggleFolderSelectAll(galleryStore[sec.key].images, $event)"
                @click.stop
                title="全选/取消全选未归档图片"
              >全选</el-checkbox>
              <span class="folder-toggle">{{ openFolders.has(sec.key + '/__unarchived__') ? '▾' : '▸' }}</span>
            </div>
            <div v-if="openFolders.has(sec.key + '/__unarchived__')" class="folder-body">
              <div class="edit-grid">
                <div
                  v-for="img in (galleryStore[sec.key].images || [])"
                  :key="img.url"
                  class="edit-img-item"
                  :class="{ selected: galleryStore.editSelected.has(img.url) }"
                >
                  <div class="img-wrap" @click="openPreviewByUrl(img.url)">
                    <img :src="img.url" :alt="img.filename" />
                    <div class="hover-mask">
                      <span class="zoom-icon">🔍</span>
                      <span>点击放大预览</span>
                    </div>
                  </div>
                  <div
                    class="edit-check"
                    :class="{ checked: galleryStore.editSelected.has(img.url) }"
                    @click.stop="galleryStore.toggleEditSelect(img.url)"
                  >
                    <svg v-if="galleryStore.editSelected.has(img.url)" viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 8 7 12 13 4"/></svg>
                  </div>
                  <div class="edit-name" :title="img.filename">{{ truncateName(img.filename) }}</div>
                </div>
              </div>
            </div>
          </div>
        </template>
      </template>

      <div class="hint-text">
        💡 操作提示：<br/>
        · 点击<strong class="hl">文件夹标题</strong> → 展开/折叠该任务下的图片<br/>
        · 点击文件夹标题右侧<strong class="hl">全选复选框</strong> → 一次性选中/取消整个文件夹的所有图片<br/>
        · 点击<strong class="hl">图片主体</strong> → 打开大图预览，判断是否需要修图<br/>
        · 点击<strong class="hl">右上角复选框</strong> → 直接勾选/取消单张（无需打开预览）
      </div>
    </div>

    <div class="app-card">
      <div class="app-card-title">指令配置</div>
      <el-form label-position="top">
        <el-form-item label="统一指令（未单独填指令的图片用此条）">
          <el-input v-model="unifiedInstruction" type="textarea" :rows="2" placeholder="如：修复手部变形，让手指自然伸展，保持白背景" />
        </el-form-item>
      </el-form>

      <div v-if="selectedImages.length > 0" class="per-image-list">
        <div class="per-image-hint">为每张图片单独指定指令（留空则使用统一指令）</div>
        <div v-for="path in selectedImages" :key="path" class="per-image-row">
          <img :src="path" class="per-image-thumb" @click="previewByUrl(path)" title="点击预览大图" />
          <span class="per-image-name" :title="path.split('/').pop()">{{ truncateName(path.split('/').pop(), 24) }}</span>
          <el-input v-model="perImageInstructions[path]" placeholder="留空用统一指令" size="default" style="flex:1" />
          <el-button size="default" text @click="previewByUrl(path)" title="预览大图">
            <span style="font-size:16px">🔍</span>
          </el-button>
          <el-button size="default" text type="danger" @click="galleryStore.toggleEditSelect(path)" title="移除">
            <span style="font-size:16px">✕</span>
          </el-button>
        </div>
      </div>

      <el-checkbox v-model="overwrite" style="margin-top: 4px">覆盖原图（不勾选则按任务文件夹归档，保持原文件名）</el-checkbox>
      <div class="hint-text">勾选覆盖：原图被直接替换；不勾选：结果存到 output/edited/&lt;任务ID&gt;/ 目录下</div>
    </div>

    <div class="btn-row">
      <el-button type="primary" :loading="submitting" :disabled="galleryStore.editSelected.size === 0" @click="submit">
        {{ submitting ? '执行中...' : `执行修图（${galleryStore.editSelected.size} 张）` }}
      </el-button>
    </div>

    <TaskProgress :task="tasksStore.currentTask" @go-gallery="goGallery" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import { useGalleryStore } from '@/stores/gallery'
import { useTasksStore } from '@/stores/tasks'
import TaskProgress from '@/components/common/TaskProgress.vue'

const router = useRouter()
const goGallery = () => router.push('/gallery')

const galleryStore = useGalleryStore()
const tasksStore = useTasksStore()

const loading = ref(false)
const unifiedInstruction = ref('')
const overwrite = ref(false)
const perImageInstructions = reactive({})
const submitting = ref(false)

// 文件夹展开/折叠状态
const openFolders = reactive(new Set())

const sections = [
  { key: 'stills', label: '🖼️ 剧照' },
  { key: 'edited', label: '✨ 修图结果' },
]

// 拍平所有图片（用于预览切换）
const allImages = computed(() => galleryStore.getAllImages())
const selectedImages = computed(() => Array.from(galleryStore.editSelected))

const getSectionTotal = (key) => {
  const sec = galleryStore[key]
  return (sec.images?.length || 0) + (sec.folders || []).reduce((s, f) => s + f.count, 0)
}

const toggleFolder = (id) => {
  if (openFolders.has(id)) {
    openFolders.delete(id)
  } else {
    openFolders.add(id)
  }
}

// 提取一个图片数组的所有 url
const folderImagesUrls = (images) => (images || []).map((i) => i.url)

// 全选/取消全选一个文件夹（或未归档分组）
const toggleFolderSelectAll = (images, checked) => {
  const urls = folderImagesUrls(images)
  if (checked) {
    galleryStore.selectFolderImages(urls)
  } else {
    galleryStore.deselectFolderImages(urls)
  }
}

const loadImages = async () => {
  loading.value = true
  await galleryStore.fetchImages()
  loading.value = false
}

const truncateName = (name, len = 16) => {
  if (!name) return ''
  if (name.length <= len) return name
  const dot = name.lastIndexOf('.')
  const ext = dot >= 0 ? name.slice(dot) : ''
  const base = dot >= 0 ? name.slice(0, dot) : name
  return base.slice(0, len - ext.length - 1) + '…' + ext
}

const formatTime = (ts) => dayjs(ts * 1000).format('MM-DD HH:mm')

// 打开预览（统一走 galleryStore → ImageModal，启用选择修图模式）
const openPreviewByUrl = (url) => galleryStore.openPreview(url, allImages.value, true)
const previewByUrl = (url) => galleryStore.openPreview(url, allImages.value, true)

onMounted(() => {
  loadImages()
})

// 监听选中变化，初始化独立指令
watch(selectedImages, (paths) => {
  paths.forEach((p) => {
    if (!(p in perImageInstructions)) {
      perImageInstructions[p] = ''
    }
  })
}, { deep: true })

const submit = async () => {
  if (galleryStore.editSelected.size === 0) {
    ElMessage.warning('请至少选择一张图片')
    return
  }

  const imagePaths = Array.from(galleryStore.editSelected)
  const instructions = {}
  let hasAnyInstruction = false

  Object.entries(perImageInstructions).forEach(([path, val]) => {
    if (val.trim()) {
      instructions[path] = val.trim()
      hasAnyInstruction = true
    }
  })

  if (!unifiedInstruction.value.trim() && !hasAnyInstruction) {
    ElMessage.warning('请填写统一指令或至少为一张图片单独指定指令')
    return
  }

  const args = { image_paths: imagePaths, overwrite: overwrite.value }
  if (unifiedInstruction.value.trim()) args.instruction = unifiedInstruction.value.trim()
  if (hasAnyInstruction) args.instructions = instructions

  const summary = `选中 ${imagePaths.length} 张图，${overwrite.value ? '覆盖原图' : '按任务归档'}${unifiedInstruction.value ? '，统一指令：' + unifiedInstruction.value : ''}`

  submitting.value = true
  tasksStore.clearCurrentTask()
  try {
    await tasksStore.submitTask('edit_image', args)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
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
.folder-body {
  padding: 10px 16px;
  border-top: 1px solid var(--border);
}

.edit-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 14px;
  padding: 6px 0;
}

.edit-empty {
  text-align: center;
  color: var(--text-muted);
  padding: 40px 20px;
  font-size: 13px;
}

.edit-img-item {
  position: relative;
  border: 1.5px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  background: var(--surface-2);
  transition: all 0.2s ease;
}
.edit-img-item:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0,0,0,0.35);
}
.edit-img-item.selected {
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
  height: 180px;
  object-fit: cover;
  display: block;
  transition: transform 0.3s ease;
}
.edit-img-item:hover .img-wrap img {
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
.edit-img-item:hover .hover-mask {
  opacity: 1;
}
.zoom-icon { font-size: 20px; }

.edit-check {
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
.edit-check:hover {
  transform: scale(1.1);
  border-color: var(--accent);
}
.edit-check.checked {
  background: var(--primary);
  border-color: var(--primary);
  box-shadow: 0 2px 8px rgba(200,65,44,0.5);
}

.edit-name {
  padding: 6px 10px;
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--surface);
  border-top: 1px solid var(--border);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
}

.hint-text {
  font-size: 12px;
  line-height: 1.8;
  color: var(--text-muted);
  padding: 12px 16px;
  margin-top: 12px;
  background: var(--surface);
  border-radius: 8px;
  border-left: 3px solid var(--accent);
}
.hint-text .hl {
  color: var(--accent);
  font-weight: 600;
}

.per-image-list {
  margin: 16px 0 8px;
}
.per-image-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 10px;
  padding: 6px 10px;
  background: var(--surface);
  border-radius: 6px;
}
.per-image-row {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--surface);
  border-radius: 8px;
  border: 1px solid var(--border);
  transition: border-color 0.2s;
}
.per-image-row:hover {
  border-color: var(--border-hover);
}
.per-image-thumb {
  width: 52px;
  height: 52px;
  object-fit: cover;
  border-radius: 6px;
  cursor: zoom-in;
  border: 1px solid var(--border);
  transition: transform 0.2s;
  flex-shrink: 0;
}
.per-image-thumb:hover {
  transform: scale(1.05);
}
.per-image-name {
  font-size: 12px;
  color: var(--text-secondary);
  min-width: 160px;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
