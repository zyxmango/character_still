<template>
  <div>
    <PageHeader icon="Picture" title="生成剧照" desc="直接浏览提示词并勾选，调用 ComfyUI FLUX 生成人物剧照" />

    <div class="workbench">
      <!-- 左：参数面板 -->
      <div class="param-panel">
        <div class="app-card">
          <div class="card-head">
            <div class="app-card-title">选择提示词</div>
            <div class="source-picker">
              <span class="source-label">数据来源</span>
              <el-select
                v-model="form.promptsFile"
                size="small"
                placeholder="暂无提示词文件"
                style="width: 240px"
                :loading="loadingBatches"
                no-data-text="还没有生成过提示词，请先到「生成提示词」页"
                @change="onBatchChange"
              >
                <el-option
                  v-for="b in batches"
                  :key="b.path"
                  :label="batchLabel(b)"
                  :value="b.path"
                />
              </el-select>
              <el-button text size="small" @click="refreshBatches">刷新</el-button>
            </div>
          </div>

          <!-- 工具条：搜索 + 计数 + 全选 -->
          <div class="list-toolbar">
            <el-input
              v-model="keyword"
              size="small"
              placeholder="搜索角色名或提示词内容"
              clearable
              style="width: 240px"
            />
            <div class="toolbar-right">
              <span class="count-hint">
                已选 <b>{{ form.selectedNames.length }}</b> / {{ characters.length }}
              </span>
              <el-button text size="small" :disabled="!characters.length" @click="selectAllVisible">
                全选{{ keyword ? '（当前结果）' : '' }}
              </el-button>
              <el-button text size="small" :disabled="!form.selectedNames.length" @click="clearSelection">
                清空
              </el-button>
            </div>
          </div>

          <!-- 提示词列表 -->
          <div v-loading="loadingChars" class="prompt-list">
            <div
              v-for="c in filteredCharacters"
              :key="c.名字"
              class="prompt-item"
              :class="{ active: isSelected(c.名字) }"
              @click="toggle(c.名字)"
            >
              <el-checkbox
                :model-value="isSelected(c.名字)"
                class="item-check"
                @click.stop
                @change="(v) => setSelected(c.名字, v)"
              />
              <div class="prompt-main">
                <div class="prompt-head">
                  <span class="char-name">{{ characterDisplayName(c, c.idx) }}</span>
                  <span v-if="characterMeta(c)" class="char-meta">{{ characterMeta(c) }}</span>
                </div>
                <div class="prompt-text" :class="{ expanded: isExpanded(c.名字) }">
                  {{ showEn(c.名字) ? (c.prompt_en || '（无英文提示词）') : (c.prompt_cn || '（无中文提示词）') }}
                </div>
                <div class="prompt-actions">
                  <el-button text size="small" @click.stop="toggleExpand(c.名字)">
                    {{ isExpanded(c.名字) ? '收起' : '展开全文' }}
                  </el-button>
                  <el-button text size="small" @click.stop="toggleLang(c.名字)">
                    {{ showEn(c.名字) ? '看中文' : '看英文' }}
                  </el-button>
                </div>
              </div>
            </div>

            <el-empty
              v-if="!loadingChars && !filteredCharacters.length"
              :image-size="60"
              :description="characters.length ? '没有匹配的提示词，换个关键词试试' : '暂无提示词，请先到「生成提示词」页'"
            />
          </div>

          <div class="select-hint">
            不勾选任何项时，默认生成全部 {{ characters.length }} 位角色
          </div>

          <el-checkbox v-model="form.force" class="force-check">
            重新生成已存在的图片（默认跳过，支持断点续传）
          </el-checkbox>
        </div>

        <div class="btn-row">
          <el-button
            type="primary"
            :loading="submitting"
            :disabled="!form.promptsFile || !characters.length"
            @click="submit"
          >
            {{ submitting ? '执行中...' : btnLabel }}
          </el-button>
        </div>

        <TaskProgress :task="tasksStore.currentTask" @go-gallery="goGallery" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/common/PageHeader.vue'
import TaskProgress from '@/components/common/TaskProgress.vue'
import { promptsApi } from '@/api'
import { useTasksStore } from '@/stores/tasks'
import { characterDisplayName, characterMeta } from '@/utils/character'

const tasksStore = useTasksStore()
const route = useRoute()
const router = useRouter()

const form = reactive({ promptsFile: '', selectedNames: [], force: false })
const batches = ref([])
const characters = ref([])
const loadingBatches = ref(false)
const loadingChars = ref(false)
const submitting = ref(false)

const keyword = ref('')
const expandedKeys = ref(new Set())
const enKeys = ref(new Set())

const willGenerateCount = computed(() =>
  form.selectedNames.length > 0 ? form.selectedNames.length : characters.value.length
)

const btnLabel = computed(() =>
  characters.value.length === 0
    ? '生成剧照'
    : `生成 ${willGenerateCount.value} 张剧照`
)

// 搜索：角色名 + 中英文提示词内容
const filteredCharacters = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return characters.value
  return characters.value.filter((c) => {
    const hay = [
      characterDisplayName(c, c.idx),
      characterMeta(c),
      c.名字,
      c.prompt_cn,
      c.prompt_en,
    ].filter(Boolean).join(' ').toLowerCase()
    return hay.includes(kw)
  })
})

const fmtTime = (ts) => {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const batchLabel = (b) => `${b.style} · ${b.count} 位 · ${fmtTime(b.mtime)}`

const isSelected = (uuid) => form.selectedNames.includes(uuid)

const setSelected = (uuid, on) => {
  const set = new Set(form.selectedNames)
  if (on) set.add(uuid)
  else set.delete(uuid)
  form.selectedNames = Array.from(set)
}

const toggle = (uuid) => setSelected(uuid, !isSelected(uuid))

const selectAllVisible = () => {
  const set = new Set(form.selectedNames)
  filteredCharacters.value.forEach((c) => set.add(c.名字))
  form.selectedNames = Array.from(set)
}

const clearSelection = () => {
  form.selectedNames = []
}

const isExpanded = (uuid) => expandedKeys.value.has(uuid)
const toggleExpand = (uuid) => {
  const s = new Set(expandedKeys.value)
  s.has(uuid) ? s.delete(uuid) : s.add(uuid)
  expandedKeys.value = s
}

const showEn = (uuid) => enKeys.value.has(uuid)
const toggleLang = (uuid) => {
  const s = new Set(enKeys.value)
  s.has(uuid) ? s.delete(uuid) : s.add(uuid)
  enKeys.value = s
}

const refreshBatches = async () => {
  loadingBatches.value = true
  try {
    const data = await promptsApi.list()
    batches.value = data.items || []
    // 优先用路由带过来的文件；否则默认选最新一批
    const fromQuery = route.query.prompts_file
    if (fromQuery) {
      // 路径分隔符/大小写可能不一致，用文件名兜底匹配
      const base = String(fromQuery).split(/[\\/]/).pop()
      const hit = batches.value.find(
        (b) => b.path === fromQuery || b.filename === base
      )
      if (hit) form.promptsFile = hit.path
    }
    if (!form.promptsFile && batches.value.length) {
      form.promptsFile = batches.value[0].path
    }
    if (form.promptsFile) await loadCharacters()
  } catch (e) {
    ElMessage.error('获取提示词列表失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loadingBatches.value = false
  }
}

const loadCharacters = async () => {
  if (!form.promptsFile) return
  loadingChars.value = true
  try {
    const data = await promptsApi.characters(form.promptsFile)
    characters.value = data.items || []
    // 换了批次，清掉旧的勾选与展开态
    form.selectedNames = []
    expandedKeys.value = new Set()
    enKeys.value = new Set()
    keyword.value = ''
  } catch (e) {
    characters.value = []
    ElMessage.error('读取人物列表失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loadingChars.value = false
  }
}

const onBatchChange = () => loadCharacters()

const submit = async () => {
  const args = { prompts_file: form.promptsFile }
  // 后端按角色名匹配（名字即文件名 stem），传名字比传序号更稳
  if (form.selectedNames.length > 0) args.ids = form.selectedNames
  if (form.force) args.force = true

  submitting.value = true
  tasksStore.clearCurrentTask()
  try {
    await tasksStore.submitTask('generate_stills', args)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    submitting.value = false
  }
}

const goGallery = () => router.push('/gallery')

onMounted(refreshBatches)
</script>

<style scoped>
/* ===== 卡片头部：标题 + 数据来源 ===== */
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.card-head .app-card-title {
  margin-bottom: 0;
}

.source-picker {
  display: flex;
  align-items: center;
  gap: 6px;
}

.source-label {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

/* ===== 工具条 ===== */
.list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.count-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-right: 4px;
}

.count-hint b {
  color: var(--accent);
  font-weight: 600;
}

/* ===== 提示词列表 ===== */
.prompt-list {
  max-height: 460px;
  min-height: 120px;
  overflow-y: auto;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
}

.prompt-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 6px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.prompt-item + .prompt-item {
  margin-top: 2px;
}

.prompt-item:hover {
  background: var(--surface-hover);
}

.prompt-item.active {
  background: var(--accent-soft);
  border-color: rgba(201, 169, 97, 0.5);
}

.item-check {
  margin-top: 1px;
  flex-shrink: 0;
}

.prompt-main {
  min-width: 0;
  flex: 1;
}

.prompt-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.char-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
  font-family: var(--font-serif);
  letter-spacing: 0.5px;
}

.char-meta {
  font-size: 11px;
  color: var(--text-muted);
}

.prompt-text {
  font-size: 12px;
  line-height: 1.75;
  color: var(--text);
  opacity: 0.88;
  white-space: pre-wrap;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.prompt-text.expanded {
  display: block;
  overflow: visible;
  -webkit-line-clamp: unset;
}

.prompt-actions {
  display: flex;
  gap: 2px;
  margin-top: 2px;
}

.prompt-actions :deep(.el-button) {
  padding: 0 4px;
  height: 20px;
  font-size: 11px;
  color: var(--accent);
  opacity: 0.75;
}

.prompt-actions :deep(.el-button:hover) {
  opacity: 1;
}

.select-hint {
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-muted);
  opacity: 0.9;
}

.force-check {
  margin-top: 10px;
  font-size: 12px;
}

</style>
