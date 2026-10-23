<template>
  <Teleport to="body">
    <div v-if="galleryStore.previewIndex >= 0" ref="rootRef" class="pswp" tabindex="-1" role="dialog" aria-modal="true" aria-label="图片预览">
      <div class="pswp__bg" @click="close"></div>
      <div class="pswp__scroll-wrap">
        <div class="pswp__container">
          <div class="pswp__item">
            <div class="pswp__zoom-wrap">
              <img
                v-if="currentImg"
                :src="currentImg.url"
                :alt="currentImg.filename"
                class="pswp__img"
                :style="imgStyle"
                @load="onImgLoad"
                @error="onImgError"
                @wheel.prevent="onWheel"
                @mousedown="startDrag"
              />
            </div>
          </div>
        </div>
      </div>
      <!-- 顶栏 -->
      <div class="pswp__top-bar">
        <div class="pswp__counter">
          {{ previewIndex + 1 }} / {{ previewList.length }}
          <span v-if="editSelectedCount > 0" class="pswp__selected-count">修图已选 {{ editSelectedCount }} 张</span>
          <span v-if="exportSelectedCount > 0" class="pswp__selected-count pswp__selected-count--export">导出已选 {{ exportSelectedCount }} 张</span>
        </div>
        <div class="pswp__actions">
          <!-- 修图选择按钮（selectMode 下显示）-->
          <button
            v-if="selectMode && currentImg"
            class="pswp__btn ps__select-btn"
            :class="{ 'is-selected': isEditSelected }"
            :title="isEditSelected ? '取消修图选择' : '选择修图'"
            @click="toggleEditSelect"
          >
            <el-icon><component :is="isEditSelected ? Check : CircleCheck" /></el-icon>
          </button>
          <!-- 导出勾选按钮（非 selectMode 时显示，画廊预览场景）-->
          <button
            v-if="!selectMode && currentImg"
            class="pswp__btn ps__select-btn ps__select-btn--export"
            :class="{ 'is-selected': isExportSelected }"
            :title="isExportSelected ? '取消导出勾选' : '勾选导出'"
            @click="toggleExportSelect"
          >
            <el-icon><component :is="isExportSelected ? Check : CircleCheck" /></el-icon>
          </button>
          <button class="pswp__btn" title="缩小" @click="zoom(-0.2)"><el-icon><ZoomOut /></el-icon></button>
          <button class="pswp__btn" title="放大" @click="zoom(0.2)"><el-icon><ZoomIn /></el-icon></button>
          <button class="pswp__btn" title="重置视图" @click="reset"><el-icon><Refresh /></el-icon></button>
          <button class="pswp__btn" title="左旋 90°" @click="rotate(-90)"><el-icon><RefreshLeft /></el-icon></button>
          <button class="pswp__btn" title="右旋 90°" @click="rotate(90)"><el-icon><RefreshRight /></el-icon></button>
          <a v-if="currentImg" class="pswp__btn" title="下载" :href="currentImg.url" :download="currentImg.filename"><el-icon><Download /></el-icon></a>
          <button class="pswp__btn pswp__close" title="关闭 (Esc)" @click="close"><el-icon><Close /></el-icon></button>
        </div>
      </div>
      <!-- 翻页箭头 -->
      <button v-if="previewIndex > 0" class="pswp__arrow pswp__arrow--left" @click="prev"><el-icon><ArrowLeftBold /></el-icon></button>
      <button v-if="previewIndex < previewList.length - 1" class="pswp__arrow pswp__arrow--right" @click="next"><el-icon><ArrowRightBold /></el-icon></button>
      <!-- 底部文件名 -->
      <div v-if="currentImg" class="pswp__caption">
        <span class="pswp__caption-name">{{ currentImg.filename }}</span>
        <span class="pswp__caption-meta">{{ zoomPct }}%{{ rotation ? ` · ${rotation}°` : '' }}</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import {
  ZoomIn, ZoomOut, Refresh, RefreshLeft, RefreshRight, Download, Close,
  ArrowLeftBold, ArrowRightBold, Check, CircleCheck,
} from '@element-plus/icons-vue'
import { useGalleryStore } from '@/stores/gallery'

const props = defineProps({
  selectMode: { type: Boolean, default: false },
})

const galleryStore = useGalleryStore()
const previewIndex = computed(() => galleryStore.previewIndex)
const previewList = computed(() => galleryStore.previewList)
const currentImg = computed(() => previewList.value[previewIndex.value] || null)

// selectMode 优先用 prop，否则用 store 中的值
const selectMode = computed(() => props.selectMode || galleryStore.previewSelectMode)

// ===== 修图选择（selectMode 模式）=====
const isEditSelected = computed(() => {
  if (!currentImg.value) return false
  return galleryStore.editSelected.has(currentImg.value.url)
})
const editSelectedCount = computed(() => galleryStore.editSelected.size)
const toggleEditSelect = () => {
  if (!currentImg.value) return
  galleryStore.toggleEditSelect(currentImg.value.url)
}

// ===== 导出勾选（非 selectMode 模式，画廊预览场景）=====
const isExportSelected = computed(() => {
  if (!currentImg.value) return false
  return galleryStore.exportSelected.has(currentImg.value.url)
})
const exportSelectedCount = computed(() => galleryStore.exportSelected.size)
const toggleExportSelect = () => {
  if (!currentImg.value) return
  galleryStore.toggleExportSelect(currentImg.value.url)
}

const scale = ref(0.7)
const rotation = ref(0)
const x = ref(0)
const y = ref(0)
const loaded = ref(false)

const zoomPct = computed(() => Math.round(scale.value * 100))

const imgStyle = computed(() => ({
  transform: `translate(${x.value}px, ${y.value}px) scale(${scale.value}) rotate(${rotation.value}deg)`,
  transition: dragging.value ? 'none' : 'transform 0.2s ease',
  opacity: loaded.value ? 1 : 0.3,
}))

const close = () => galleryStore.closePreview()
const reset = () => { scale.value = 0.7; rotation.value = 0; x.value = 0; y.value = 0 }
const zoom = (delta) => { scale.value = Math.min(5, Math.max(0.2, scale.value + delta)) }
const rotate = (deg) => { rotation.value += deg }
const prev = () => { if (galleryStore.previewIndex > 0) { galleryStore.previewIndex--; reset() } }
const next = () => { if (galleryStore.previewIndex < previewList.value.length - 1) { galleryStore.previewIndex++; reset() } }

const onWheel = (e) => { zoom(e.deltaY < 0 ? 0.15 : -0.15) }
const onImgLoad = () => { loaded.value = true }
const onImgError = () => { loaded.value = true }

// 拖拽平移
const dragging = ref(false)
const dragStart = ref({ x: 0, y: 0, ox: 0, oy: 0 })
const startDrag = (e) => {
  dragging.value = true
  dragStart.value = { x: e.clientX, y: e.clientY, ox: x.value, oy: y.value }
  e.preventDefault()
}
const onDragMove = (e) => {
  if (!dragging.value) return
  x.value = dragStart.value.ox + (e.clientX - dragStart.value.x)
  y.value = dragStart.value.oy + (e.clientY - dragStart.value.y)
}
const endDrag = () => { dragging.value = false }

const onKey = (e) => {
  if (galleryStore.previewIndex < 0) return
  switch (e.key) {
    case 'Escape': close(); break
    case 'ArrowLeft': prev(); break
    case 'ArrowRight': next(); break
    case '+': case '=': zoom(0.2); break
    case '-': zoom(-0.2); break
    case '0': reset(); break
    case ' ': // 空格=选择当前图
      if (selectMode.value) { e.preventDefault(); toggleEditSelect() }
      else { e.preventDefault(); toggleExportSelect() }
      break
  }
}

// 切换图片时重置状态
watch(previewIndex, () => { loaded.value = false; reset() })

onMounted(() => {
  window.addEventListener('keydown', onKey)
  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup', endDrag)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', endDrag)
})
</script>

<style scoped>
.pswp {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
}

.pswp__bg {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.92);
  backdrop-filter: blur(8px);
}

.pswp__scroll-wrap {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.pswp__zoom-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
}

.pswp__img {
  max-width: 92%;
  max-height: 86%;
  border-radius: var(--radius-md);
  cursor: grab;
  user-select: none;
  -webkit-user-drag: none;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6);
}

.pswp__img:active {
  cursor: grabbing;
}

.pswp__top-bar {
  position: absolute;
  top: 16px;
  left: 0;
  right: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;
  z-index: 10;
}

.pswp__counter {
  color: rgba(255, 255, 255, 0.85);
  font-size: 13px;
  font-family: var(--font-mono);
  background: rgba(0, 0, 0, 0.4);
  padding: 4px 12px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  gap: 10px;
}

.pswp__selected-count {
  font-size: 11px;
  color: #a8c8f0;
  background: rgba(80, 120, 180, 0.45);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  font-family: inherit;
  border: 1px solid rgba(168, 200, 240, 0.3);
}

.pswp__actions {
  display: flex;
  gap: 6px;
}

.pswp__btn {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.5);
  color: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(255, 255, 255, 0.15);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  transition: all var(--transition);
  backdrop-filter: blur(6px);
  text-decoration: none;
}

.pswp__btn:hover {
  background: var(--accent);
  color: #fff;
  transform: scale(1.05);
}

.pswp__close:hover {
  background: var(--error);
}

/* 选择修图按钮 */
.ps__select-btn {
  background: rgba(0, 0, 0, 0.5);
  color: rgba(255, 255, 255, 0.9);
}
.ps__select-btn.is-selected {
  background: var(--primary, #c8412c);
  color: #fff;
  border-color: var(--primary, #c8412c);
  box-shadow: 0 0 12px rgba(200, 65, 44, 0.6);
}
.ps__select-btn.is-selected:hover {
  background: var(--primary-light, #e8553c);
  transform: scale(1.1);
}

/* 导出勾选按钮（金色/墨韵色）*/
.ps__select-btn--export {
  background: rgba(0, 0, 0, 0.5);
  color: rgba(255, 255, 255, 0.9);
}
.ps__select-btn--export.is-selected {
  background: var(--accent, #c8a882);
  color: var(--bg, #2a2421);
  border-color: var(--accent, #c8a882);
  box-shadow: 0 0 12px rgba(200, 168, 130, 0.6);
}
.ps__select-btn--export.is-selected:hover {
  transform: scale(1.1);
}

/* 已选计数 - 导出版本 */
.pswp__selected-count--export {
  color: var(--accent, #c8a882);
  background: rgba(200, 168, 130, 0.22);
  border-color: rgba(200, 168, 130, 0.35);
}

.pswp__arrow {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.5);
  color: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(255, 255, 255, 0.15);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  z-index: 10;
  transition: all var(--transition);
  backdrop-filter: blur(6px);
}

.pswp__arrow:hover {
  background: var(--primary);
  color: #fff;
  transform: translateY(-50%) scale(1.1);
}

.pswp__arrow--left { left: 24px; }
.pswp__arrow--right { right: 24px; }

.pswp__caption {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  z-index: 10;
}

.pswp__caption-name {
  color: rgba(255, 255, 255, 0.9);
  font-size: 13px;
  background: rgba(0, 0, 0, 0.5);
  padding: 6px 16px;
  border-radius: var(--radius-full);
  backdrop-filter: blur(6px);
}

.pswp__caption-meta {
  color: rgba(255, 255, 255, 0.5);
  font-size: 11px;
  font-family: var(--font-mono);
}
</style>
