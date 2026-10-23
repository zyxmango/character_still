<template>
  <div>
    <PageHeader icon="Connection" title="一键全流程" desc="从提示词生成到剧照出图的全自动化流程，可选填修图指令实现端到端产出" />

    <!-- 流程步骤条 -->
    <div class="stepper-card app-card">
      <el-steps :active="currentStep" align-center finish-status="success">
        <el-step title="生成提示词" description="Qwen 双语提示词" :icon="EditPen" />
        <el-step title="生成剧照" description="FLUX 出图" :icon="Picture" />
        <el-step title="修图（可选）" description="留空则跳过" :icon="MagicStick" />
      </el-steps>
    </div>

    <div class="workbench">
      <!-- 左：参数面板 -->
      <div class="param-panel">
        <!-- 模板工具栏 -->
        <div class="app-card template-bar">
          <div class="template-bar-left">
            <el-icon class="template-icon"><Files /></el-icon>
            <span class="template-label">任务模板</span>
            <el-select
              v-model="selectedTemplateId"
              placeholder="选择模板加载配置"
              size="small"
              clearable
              style="width: 220px"
              @change="loadTemplate"
            >
              <el-option
                v-for="t in templates"
                :key="t.id"
                :label="`${t.name}（${t.task_type}）`"
                :value="t.id"
              />
            </el-select>
            <el-button
              v-if="selectedTemplateId"
              text
              size="small"
              type="danger"
              @click="removeTemplate"
            >删除</el-button>
          </div>
          <el-button size="small" @click="showSaveDialog = true">
            <el-icon><FolderAdd /></el-icon> 存为模板
          </el-button>
        </div>

        <div class="app-card">
          <div class="app-card-title">基础配置</div>
          <el-form label-position="top">
            <el-form-item label="生成风格">
              <div class="style-row">
                <el-select v-model="form.style" placeholder="选择风格" style="flex: 1">
                  <el-option-group label="内置风格">
                    <el-option v-for="s in optionsStore.builtinStyles" :key="s" :label="s" :value="s" />
                  </el-option-group>
                  <el-option-group v-if="optionsStore.customStyles.length" label="自定义风格">
                    <el-option
                      v-for="s in optionsStore.customStyles"
                      :key="s.id"
                      :label="s.style_name"
                      :value="s.style_name"
                    />
                  </el-option-group>
                </el-select>
                <el-button text size="small" @click="showStyleDialog = true">
                  <el-icon><MagicStick /></el-icon> 自定义
                </el-button>
              </div>
            </el-form-item>
            <el-form-item label="修图指令（可选，留空则跳过修图步骤）">
              <el-input v-model="form.edit_instruction" type="textarea" :rows="2" placeholder="如：修复手部变形，让手指自然伸展" />
            </el-form-item>
          </el-form>
        </div>

        <div class="app-card">
          <div class="app-card-title">身份与特征</div>
          <IdentityConfig
            ref="identityConfig"
            :statuses="optionsStore.statuses"
            :specials="optionsStore.specials"
          />
        </div>

        <div class="btn-row">
          <el-button type="primary" :loading="submitting" @click="submit">
            {{ submitting ? '执行中...' : '开始全流程' }}
          </el-button>
        </div>

        <TaskProgress :task="tasksStore.currentTask" @go-gallery="goGallery" />
      </div>
    </div>

    <!-- 保存模板对话框 -->
    <el-dialog v-model="showSaveDialog" title="保存为任务模板" width="420px">
      <el-form label-position="top">
        <el-form-item label="模板名称">
          <el-input v-model="newTemplateName" placeholder="如：日常批量-贵族侠客各3" />
        </el-form-item>
        <div class="dialog-hint">将保存当前风格、身份数量、特殊特征、修图指令。同名模板会被覆盖更新。</div>
      </el-form>
      <template #footer>
        <el-button @click="showSaveDialog = false">取消</el-button>
        <el-button type="primary" @click="saveTemplate">保存</el-button>
      </template>
    </el-dialog>

    <!-- 自定义风格管理对话框 -->
    <el-dialog v-model="showStyleDialog" title="自定义风格" width="560px">
      <div class="style-dialog-body">
        <!-- 已有自定义风格列表 -->
        <div v-if="optionsStore.customStyles.length" class="custom-style-list">
          <div class="dialog-section-title">已有风格</div>
          <div v-for="s in optionsStore.customStyles" :key="s.id" class="custom-style-item">
            <div class="csi-info">
              <span class="csi-name">{{ s.style_name }}</span>
              <span class="csi-desc">{{ s.description }}</span>
              <div class="csi-meta">
                <el-tag v-for="c in (s.color_preference || []).slice(0, 4)" :key="c" size="small" effect="plain">{{ c }}</el-tag>
              </div>
            </div>
            <el-button text size="small" type="danger" @click="deleteStyle(s)">删除</el-button>
          </div>
        </div>
        <div v-else class="empty-hint">暂无自定义风格，在下方描述你想要的风格</div>

        <el-divider />

        <!-- 新建风格 -->
        <div class="dialog-section-title">新建风格</div>
        <el-form label-position="top">
          <el-form-item label="风格名称（可选，留空由 AI 生成）">
            <el-input v-model="newStyleName" placeholder="如：仙侠清冷风" />
          </el-form-item>
          <el-form-item label="风格描述（用自然语言描述你想要的视觉风格）">
            <el-input
              v-model="newStyleDesc"
              type="textarea"
              :rows="3"
              placeholder="如：清冷孤傲的仙侠风格，素雅飘逸的白色长袍，冷峻眉眼，月光下的竹林氛围，水墨写意感"
            />
          </el-form-item>
        </el-form>
        <div class="dialog-hint">AI 会根据描述生成气质关键词、偏好颜色、姿势、光影等配置，保存后可在风格下拉框选用。</div>
      </div>
      <template #footer>
        <el-button @click="showStyleDialog = false">关闭</el-button>
        <el-button type="primary" :loading="creatingStyle" @click="createStyle">生成并保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { EditPen, Picture, MagicStick, Files, FolderAdd } from '@element-plus/icons-vue'
import PageHeader from '@/components/common/PageHeader.vue'
import IdentityConfig from '@/components/common/IdentityConfig.vue'
import TaskProgress from '@/components/common/TaskProgress.vue'
import { useOptionsStore } from '@/stores/options'
import { useTasksStore } from '@/stores/tasks'
import { templateApi, styleApi } from '@/api'

const router = useRouter()
const goGallery = () => router.push('/gallery')

const optionsStore = useOptionsStore()
const tasksStore = useTasksStore()

const form = reactive({ style: optionsStore.styles[0] || '', edit_instruction: '' })
const submitting = ref(false)
const identityConfig = ref(null)

// ============ 任务模板 ============
const templates = ref([])
const selectedTemplateId = ref('')
const showSaveDialog = ref(false)
const newTemplateName = ref('')

const loadTemplates = async () => {
  try {
    const data = await templateApi.list()
    templates.value = data.items || []
  } catch (e) {
    console.error('加载模板失败:', e)
  }
}

const loadTemplate = (templateId) => {
  if (!templateId) return
  const t = templates.value.find(x => x.id === templateId)
  if (!t) return
  const cfg = t.config || {}
  if (cfg.style) form.style = cfg.style
  if (cfg.edit_instruction !== undefined) form.edit_instruction = cfg.edit_instruction
  // 通过 IdentityConfig 暴露的方法回填身份/特征数量
  if (identityConfig.value) {
    // 直接操作 IdentityConfig 内部状态：通过 modelValue 回写
    // IdentityConfig 监听 modelValue，但只在首次初始化时同步，所以需用 reset 方法或重新触发
    // 简化方案：调用 emit('update:modelValue') 的反向——通过 props 传入新值并触发 watch
    identityConfig.value.applyTemplate?.(cfg.counts || {}, cfg.specials || {})
  }
  ElMessage.success(`已加载模板「${t.name}」`)
}

const saveTemplate = async () => {
  const name = newTemplateName.value.trim()
  if (!name) {
    ElMessage.warning('请输入模板名称')
    return
  }
  const { counts, specials } = identityConfig.value.getSelected()
  const cfg = {
    style: form.style,
    counts,
    edit_instruction: form.edit_instruction,
  }
  if (Object.keys(specials).length > 0) cfg.specials = specials

  try {
    const data = await templateApi.create({ name, task_type: 'full_pipeline', config: cfg })
    templates.value = data.items || []
    showSaveDialog.value = false
    newTemplateName.value = ''
    ElMessage.success(data.message || '模板已保存')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  }
}

const removeTemplate = async () => {
  if (!selectedTemplateId.value) return
  try {
    await ElMessageBox.confirm('确认删除该模板？', '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    const data = await templateApi.delete(selectedTemplateId.value)
    templates.value = data.items || []
    selectedTemplateId.value = ''
    ElMessage.success('模板已删除')
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

onMounted(() => {
  loadTemplates()
  // 刷新自定义风格（确保最新）
  optionsStore.refreshCustomStyles()
})

// ============ 自定义风格 ============
const showStyleDialog = ref(false)
const newStyleName = ref('')
const newStyleDesc = ref('')
const creatingStyle = ref(false)

const createStyle = async () => {
  if (!newStyleDesc.value.trim()) {
    ElMessage.warning('请输入风格描述')
    return
  }
  creatingStyle.value = true
  try {
    const data = await styleApi.create({
      description: newStyleDesc.value.trim(),
      name: newStyleName.value.trim() || null,
    })
    await optionsStore.refreshCustomStyles()
    ElMessage.success(data.message || '风格已保存')
    newStyleName.value = ''
    newStyleDesc.value = ''
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '生成失败，请检查 Ollama 是否运行')
  } finally {
    creatingStyle.value = false
  }
}

const deleteStyle = async (s) => {
  try {
    await ElMessageBox.confirm(`确认删除风格「${s.style_name}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await styleApi.delete(s.id)
    await optionsStore.refreshCustomStyles()
    ElMessage.success('风格已删除')
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

// 流程当前步骤：未提交=0，执行中按进度消息推断
const currentStep = computed(() => {
  const task = tasksStore.currentTask
  if (!task || task.status === 'pending') return 0
  const hasEdit = String(form.edit_instruction || '').trim().length > 0
  if (task.status === 'success') return hasEdit ? 3 : 2
  // 执行中：progress 项可能是字符串，也可能是 {type, message} 对象
  const msgs = Array.isArray(task.progress) ? task.progress : []
  const last = msgs[msgs.length - 1]
  const text = typeof last === 'string' ? last : (last?.message || last?.error || '')
  if (text.includes('修图') || text.includes('edit')) return 2
  if (text.includes('剧照') || text.includes('stills') || text.includes('出图')) return 1
  return 0
})

const submit = async () => {
  const { counts, specials } = identityConfig.value.getSelected()
  if (Object.keys(counts).length === 0 && Object.keys(specials).length === 0) {
    ElMessage.warning('请至少选择一个身份或特殊特征')
    return
  }
  const args = { style: form.style, counts, edit_instruction: form.edit_instruction }
  if (Object.keys(specials).length > 0) args.specials = specials

  submitting.value = true
  tasksStore.clearCurrentTask()
  try {
    await tasksStore.submitTask('full_pipeline', args)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.stepper-card {
  margin-bottom: 20px;
}

/* 模板工具栏 */
.template-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px !important;
}

.template-bar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}

.template-icon {
  color: var(--accent);
  font-size: 16px;
}

.template-label {
  font-size: 13px;
  color: var(--text-muted);
  white-space: nowrap;
}

.dialog-hint {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.6;
  margin-top: 4px;
}

/* 风格选择行 */
.style-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

/* 自定义风格对话框 */
.style-dialog-body {
  max-height: 60vh;
  overflow-y: auto;
}

.dialog-section-title {
  font-size: 13px;
  color: var(--accent);
  font-family: var(--font-serif);
  margin-bottom: 10px;
  letter-spacing: 1px;
}

.custom-style-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.custom-style-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.csi-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.csi-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
}

.csi-desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

.csi-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.empty-hint {
  text-align: center;
  color: var(--text-dim);
  font-size: 13px;
  padding: 16px 0;
}

</style>
