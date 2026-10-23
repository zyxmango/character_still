<template>
  <div>
    <PageHeader icon="Lightning" title="任务队列" desc="所有任务自动排队串行执行，进度通过 WebSocket 实时推送">
      <template #actions>
        <el-tag v-if="tasksStore.wsConnected" type="success" size="small" effect="plain">
          <span class="dot-live"></span>实时
        </el-tag>
        <el-tag v-else type="warning" size="small" effect="plain">轮询中</el-tag>
        <el-button type="primary" size="small" @click="loadTasks">刷新</el-button>
      </template>
    </PageHeader>

    <div v-if="tasksStore.tasks.length === 0" class="empty-state">
      <div class="icon">📋</div>
      <div class="text">暂无任务，去生成一些吧</div>
    </div>

    <div v-else class="task-list">
      <div
        v-for="t in tasksStore.tasks"
        :key="t.task_id"
        class="task-card"
        :class="`card-${t.status}`"
      >
        <!-- 卡片头部：类型 / 状态 / 时间 / ID / 取消 -->
        <div class="tc-header">
          <div class="tc-title">
            <span class="tc-type-icon" :class="`ti-${t.task_type}`">{{ typeIcon(t.task_type) }}</span>
            <span class="tc-type">{{ typeLabel(t.task_type) }}</span>
            <span class="tc-status" :class="`status-${t.status}`">{{ statusLabel(t.status) }}</span>
          </div>
          <div class="tc-meta">
            <span class="tc-time" :title="t.created_at">{{ formatTime(t.created_at) }}</span>
            <span class="tc-id">{{ t.task_id }}</span>
            <el-button
              v-if="t.status === 'pending' || t.status === 'running'"
              text
              size="small"
              type="danger"
              @click="handleCancel(t.task_id)"
            >取消</el-button>
          </div>
        </div>

        <!-- 参数摘要 -->
        <div v-if="argsSummary(t)" class="tc-args">
          <el-icon><InfoFilled /></el-icon>
          <span>{{ argsSummary(t) }}</span>
        </div>

        <!-- 进度条 -->
        <div class="tc-bar-track">
          <div class="tc-bar-fill" :class="`fill-${t.status}`" :style="{ width: getPercent(t) + '%' }"></div>
        </div>

        <!-- 错误信息 -->
        <div v-if="t.error" class="tc-error">
          <el-icon><WarningFilled /></el-icon>
          <span>{{ t.error }}</span>
        </div>

        <!-- 结果摘要 -->
        <div v-if="t.result && !t.result.error" class="tc-summary">
          {{ resultSummary(t) }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import { InfoFilled, WarningFilled } from '@element-plus/icons-vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { useTasksStore } from '@/stores/tasks'

const tasksStore = useTasksStore()

let fallbackTimer = null

onMounted(() => {
  // WS 已连接时无需轮询；未连接时启动兜底轮询
  loadTasks()
  if (!tasksStore.wsConnected) {
    fallbackTimer = setInterval(() => loadTasks(), 5000)
  }
})

onUnmounted(() => {
  if (fallbackTimer) clearInterval(fallbackTimer)
})

const loadTasks = () => tasksStore.fetchTasks()

const typeLabel = (type) => {
  const map = { generate_prompt: '生成提示词', generate_stills: '生成剧照', edit_image: '修图', full_pipeline: '全流程' }
  return map[type] || type
}

const typeIcon = (type) => {
  const map = { generate_prompt: '✎', generate_stills: '🖼', edit_image: '✦', full_pipeline: '⚡' }
  return map[type] || '•'
}

const statusLabel = (status) => {
  const map = { pending: '排队中', running: '执行中', success: '完成', failed: '失败', cancelled: '已取消' }
  return map[status] || status
}

const getPercent = (t) => {
  if (t.status === 'success') return 100
  if (t.status === 'running') return Math.min(95, 20 + (t.progress?.length || 0) * 5)
  if (t.status === 'pending') return 10
  return 100
}

// 参数摘要：从 args 提取关键信息
const argsSummary = (t) => {
  if (!t.args) return ''
  const a = t.args
  const parts = []
  if (a.style) parts.push(`风格: ${a.style}`)
  if (a.counts && Object.keys(a.counts).length > 0) {
    const c = Object.entries(a.counts).map(([k, v]) => `${k}×${v}`).join(' ')
    parts.push(`身份: ${c}`)
  }
  if (a.specials && Object.keys(a.specials).length > 0) {
    const s = Object.entries(a.specials).map(([k, v]) => `${k}×${v}`).join(' ')
    parts.push(`特征: ${s}`)
  }
  if (a.prompts_file) {
    const fname = String(a.prompts_file).split(/[\\/]/).pop()
    parts.push(`文件: ${fname}`)
  }
  if (a.ids && a.ids.length > 0) parts.push(`序号: ${a.ids.join(',')}`)
  if (a.edit_instruction) parts.push(`修图: ${a.edit_instruction.slice(0, 20)}${a.edit_instruction.length > 20 ? '...' : ''}`)
  if (a.instruction) parts.push(`指令: ${a.instruction.slice(0, 20)}${a.instruction.length > 20 ? '...' : ''}`)
  return parts.join('  ·  ')
}

// 结果摘要：给用户看的一句话，替代原始 JSON
const resultSummary = (t) => {
  const r = t.result || {}
  switch (t.task_type) {
    case 'generate_prompt':
      return `已生成 ${r.count || 0} 位角色${r.style ? `（${r.style}）` : ''}`
    case 'generate_stills':
      return `已生成 ${r.count || 0} 张剧照` +
        (r.skipped ? `，跳过 ${r.skipped} 张已存在` : '') +
        (r.failed_count ? `，失败 ${r.failed_count} 张` : '')
    case 'edit_image':
      return `成功 ${r.success || 0} 张，失败 ${r.failed || 0} 张`
    case 'full_pipeline':
      return `${r.characters_count || 0} 位角色 · ${r.stills_count || 0} 张剧照` +
        (r.edited_count ? ` · ${r.edited_count} 张修图` : '')
    default:
      return r.count !== undefined ? `已处理 ${r.count} 项` : '已完成'
  }
}

const formatTime = (iso) => {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const now = new Date()
    const diff = (now - d) / 1000
    if (diff < 60) return `${Math.floor(diff)}秒前`
    if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
    if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch (e) {
    return iso
  }
}

const handleCancel = async (taskId) => {
  try {
    await ElMessageBox.confirm('确定取消该任务？', '提示', { type: 'warning' })
    await tasksStore.cancelTask(taskId)
  } catch {
    // 用户取消
  }
}
</script>

<style scoped>
.task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--border);
  border-radius: var(--radius-card);
  padding: 14px 18px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}
.task-card:hover {
  box-shadow: var(--shadow-md);
}
.card-running { border-left-color: var(--primary); }
.card-success { border-left-color: var(--success); }
.card-failed { border-left-color: var(--error); }
.card-cancelled { border-left-color: var(--text-dim); }
.card-pending { border-left-color: var(--text-muted); }

.tc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.tc-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tc-type-icon {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  font-size: 12px;
  background: var(--surface-hover);
  color: var(--accent);
}
.ti-generate_prompt { color: var(--primary); }
.ti-generate_stills { color: var(--success); }
.ti-edit_image { color: var(--accent); }
.ti-full_pipeline { color: var(--warning, #e6a23c); }

.tc-type {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
}

.tc-status {
  font-size: 11px;
  padding: 2px 10px;
  border-radius: var(--radius-full);
}
.status-pending { background: var(--surface-hover); color: var(--text-muted); }
.status-running { background: var(--primary-soft); color: var(--primary-light); }
.status-success { background: var(--success-soft); color: var(--success); }
.status-failed { background: var(--error-soft); color: var(--error); }
.status-cancelled { background: var(--surface-hover); color: var(--text-dim); }

.tc-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}
.tc-time {
  font-size: 12px;
  color: var(--text-muted);
}
.tc-id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
}

.tc-args {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
  background: var(--surface-hover);
  padding: 6px 10px;
  border-radius: var(--radius);
  margin-bottom: 10px;
}
.tc-args .el-icon {
  color: var(--accent);
  flex-shrink: 0;
}

.tc-bar-track {
  height: 6px;
  background: var(--surface-hover);
  border-radius: var(--radius-full);
  overflow: hidden;
  margin-bottom: 10px;
}
.tc-bar-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 0.5s ease;
}
.fill-pending { background: var(--text-muted); animation: pulse 1.5s infinite; }
.fill-running { background: linear-gradient(90deg, var(--primary), var(--primary-light)); }
.fill-success { background: var(--success); }
.fill-failed { background: var(--error); }
.fill-cancelled { background: var(--text-dim); }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.tc-error {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--error);
  font-size: 12px;
  margin-top: 10px;
  padding: 6px 10px;
  background: var(--error-soft);
  border-radius: var(--radius);
}

.tc-summary {
  margin-top: 10px;
  font-size: 12px;
  color: var(--success);
  padding: 6px 10px;
  background: var(--success-soft);
  border-radius: var(--radius);
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-muted);
}
.empty-state .icon {
  font-size: 48px;
  margin-bottom: 12px;
  opacity: 0.5;
}
.empty-state .text {
  font-size: 14px;
}

/* 实时标签小圆点 */
.dot-live {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
  margin-right: 4px;
  animation: pulse 1.5s infinite;
}
</style>
