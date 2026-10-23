<template>
  <div>
    <PageHeader
      icon="Document"
      title="提示词工程"
      desc="所有提示词约束集中在这份文档里：改风格、加身份、放宽规则，保存后下一次生成即生效"
    />

    <div class="app-card">
      <div class="status-row">
        <span class="status-label">配置来源</span>
        <el-tag size="small" :type="sourceType" effect="plain">{{ sourceText }}</el-tag>
        <span v-if="info.blocks !== undefined" class="status-meta">
          解析到 {{ info.blocks }} 个配置块
        </span>
        <span v-if="info.mtime" class="status-meta">{{ fmtTime(info.mtime) }}</span>
      </div>
      <div class="status-path">{{ path || '—' }}</div>

      <el-alert
        v-if="errors.length"
        type="error"
        :closable="false"
        class="status-alert"
        title="配置解析失败，当前正在使用内置默认配置"
      >
        <ul class="alert-list">
          <li v-for="(e, i) in errors" :key="i">{{ e }}</li>
        </ul>
      </el-alert>
      <el-alert
        v-else-if="problems.length"
        type="warning"
        :closable="false"
        class="status-alert"
        title="配置结构不完整，当前正在使用内置默认配置"
      >
        <ul class="alert-list">
          <li v-for="(p, i) in problems" :key="i">{{ p }}</li>
        </ul>
      </el-alert>

      <div class="effect-grid">
        <div class="effect-item">
          <span class="effect-label">风格（{{ styles.length }}）</span>
          <div class="effect-tags">
            <el-tag v-for="s in styles" :key="s" size="small" effect="plain" type="warning">{{ s }}</el-tag>
          </div>
        </div>
        <div class="effect-item">
          <span class="effect-label">身份（{{ statuses.length }}）</span>
          <div class="effect-tags">
            <el-tag v-for="s in statuses" :key="s" size="small" effect="plain">{{ s }}</el-tag>
          </div>
        </div>
        <div class="effect-item">
          <span class="effect-label">服装颜色（{{ colors.length }}）</span>
          <div class="effect-tags">
            <el-tag v-for="c in colors" :key="c" size="small" effect="plain" type="success">{{ c }}</el-tag>
          </div>
        </div>
        <div class="effect-item">
          <span class="effect-label">特殊特征（{{ specials.length }}）</span>
          <div class="effect-tags">
            <el-tag v-for="s in specials" :key="s" size="small" effect="plain" type="info">{{ s }}</el-tag>
          </div>
        </div>
      </div>
    </div>

    <div class="app-card">
      <div class="editor-head">
        <div class="app-card-title">配置文档</div>
        <div class="editor-actions">
          <el-button size="small" :loading="checking" @click="validateOnly">校验</el-button>
          <el-button size="small" @click="reload">重新加载</el-button>
          <el-button size="small" type="danger" plain @click="restore">恢复默认</el-button>
          <el-button size="small" type="primary" :loading="saving" @click="save">保存</el-button>
        </div>
      </div>

      <el-input
        v-model="content"
        v-loading="loading"
        type="textarea"
        :rows="30"
        spellcheck="false"
        class="guide-editor"
        placeholder="提示词工程配置（Markdown + YAML）"
      />

      <div class="editor-hint">
        只编辑 <code>```yaml</code> 块里的内容，不要改动缩进结构。保存前会自动校验；校验不通过不会写入。
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/common/PageHeader.vue'
import { promptGuideApi } from '@/api'

const content = ref('')
const path = ref('')
const info = ref({})
const statuses = ref([])
const specials = ref([])
const colors = ref([])
const styles = ref([])

const loading = ref(false)
const saving = ref(false)
const checking = ref(false)

const errors = computed(() => info.value.errors || [])
const problems = computed(() => info.value.problems || [])

const sourceType = computed(() => (info.value.source === 'file' ? 'success' : 'warning'))
const sourceText = computed(() => ({
  file: '配置文件',
  default: '内置默认（配置文件不存在）',
  fallback: '内置默认（配置文件解析失败）',
}[info.value.source] || '未知'))

const fmtTime = (ts) => {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const applyPayload = (d) => {
  if (d.content !== undefined) content.value = d.content || ''
  info.value = d.info || {}
  path.value = d.path || ''
  statuses.value = d.statuses || []
  specials.value = d.specials || []
  colors.value = d.colors || []
  styles.value = d.styles || []
}

const load = async () => {
  loading.value = true
  try {
    applyPayload(await promptGuideApi.get())
  } catch (e) {
    ElMessage.error('读取配置失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

// 统一的校验失败提示（后端 400 时 detail 是对象）
const showValidationError = (e, fallbackMsg) => {
  const detail = e.response?.data?.detail
  if (detail && typeof detail === 'object') {
    const lines = [...(detail.errors || []), ...(detail.problems || [])]
    ElMessage.error(`${detail.message || fallbackMsg}${lines.length ? '：' + lines[0] : ''}`)
  } else {
    ElMessage.error(typeof detail === 'string' ? detail : (e.message || fallbackMsg))
  }
}

const validateOnly = async () => {
  checking.value = true
  try {
    const r = await promptGuideApi.validate(content.value)
    if (r.ok) {
      ElMessage.success(`校验通过：${r.blocks} 个配置块，${r.styles.length} 种风格，${r.statuses.length} 种身份`)
    } else {
      const lines = [...(r.errors || []), ...(r.problems || [])]
      ElMessage.error(lines[0] || '校验未通过')
    }
  } catch (e) {
    showValidationError(e, '校验失败')
  } finally {
    checking.value = false
  }
}

const save = async () => {
  saving.value = true
  try {
    const d = await promptGuideApi.save(content.value)
    applyPayload(d)
    const backup = d.backup ? d.backup.split(/[\\/]/).pop() : ''
    ElMessage.success(backup ? `已保存（旧配置已备份为 ${backup}）` : '已保存')
  } catch (e) {
    showValidationError(e, '保存失败')
  } finally {
    saving.value = false
  }
}

const reload = async () => {
  try {
    applyPayload(await promptGuideApi.reload())
    ElMessage.success('已重新加载')
  } catch (e) {
    ElMessage.error('重新加载失败：' + (e.response?.data?.detail || e.message))
  }
}

const restore = async () => {
  try {
    await ElMessageBox.confirm(
      '将用内置默认配置覆盖当前文档，当前文件会自动备份一份。确认继续？',
      '恢复默认配置',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    const d = await promptGuideApi.restore()
    applyPayload(d)
    ElMessage.success('已恢复默认配置')
  } catch (e) {
    ElMessage.error('恢复失败：' + (e.response?.data?.detail || e.message))
  }
}

onMounted(load)
</script>

<style scoped>
.status-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.status-label {
  font-size: 12px;
  color: var(--text-muted);
}

.status-meta {
  font-size: 12px;
  color: var(--text-dim);
}

.status-path {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-dim);
  word-break: break-all;
  font-family: var(--font-mono);
}

.status-alert {
  margin-top: 12px;
}

.alert-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.8;
}

.effect-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
  margin-top: 16px;
}

.effect-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.effect-label {
  font-size: 12px;
  color: var(--text-muted);
}

.effect-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.editor-head .app-card-title {
  margin-bottom: 0;
}

.editor-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.guide-editor :deep(.el-textarea__inner) {
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.75;
  color: var(--text);
}

.editor-hint {
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.7;
}

.editor-hint code {
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--surface-hover);
  font-family: var(--font-mono);
  font-size: 11px;
}
</style>
