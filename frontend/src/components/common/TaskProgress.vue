<template>
  <div v-if="task" class="task-progress">
    <div class="tp-header">
      <span class="tp-type">{{ typeLabel }}</span>
      <span class="tp-status" :class="`status-${task.status}`">{{ statusLabel }}</span>
    </div>
    <div class="tp-bar-track">
      <div class="tp-bar-fill" :class="`fill-${task.status}`" :style="{ width: percent + '%' }"></div>
    </div>

    <!-- 进度日志（仅执行中显示最近 5 条） -->
    <div v-if="!isDone && recentProgress.length" class="tp-progress-list">
      <div v-for="(p, i) in recentProgress" :key="i" class="tp-progress-item">
        {{ msgText(p) }}
      </div>
      <div v-if="(task.progress?.length || 0) > 5" class="tp-progress-more">
        共 {{ task.progress.length }} 条记录
      </div>
    </div>

    <div v-if="task.error" class="tp-error">{{ task.error }}</div>

    <!-- ===== 结果区：按任务类型给出人话，不展示原始 JSON ===== -->
    <div v-if="result && !result.error" class="tp-result-block">

      <!-- 生成提示词 -->
      <template v-if="task.task_type === 'generate_prompt'">
        <div class="result-head">
          <span class="result-title">已生成 {{ result.count }} 位角色</span>
          <el-tag v-if="result.style" size="small" effect="plain">{{ result.style }}</el-tag>
        </div>
        <div class="char-list">
          <div v-for="(c, i) in result.items" :key="i" class="char-item">
            <div class="char-head">
              <span class="char-name">{{ characterDisplayName(c, i) }}</span>
              <span class="char-meta">{{ characterMeta(c) }}</span>
            </div>
            <div class="char-desc" :class="{ expanded: expandedSet.has(i) }" @click="toggleExpand(i)">
              {{ c.zh }}
            </div>
          </div>
        </div>
        <div class="result-actions">
          <el-button size="small" type="primary" plain @click="$emit('go-stills', result)">
            用这批提示词生成剧照
          </el-button>
        </div>
      </template>

      <!-- 生成剧照 / 修图 -->
      <template v-else-if="task.task_type === 'generate_stills' || task.task_type === 'edit_image'">
        <div class="result-head">
          <span class="result-title">
            <template v-if="task.task_type === 'generate_stills'">
              已生成 {{ result.count }} 张剧照
            </template>
            <template v-else>
              已处理 {{ result.success ?? result.count }} 张
            </template>
          </span>
          <span v-if="skippedText" class="result-sub">{{ skippedText }}</span>
        </div>
        <div v-if="(result.items || []).length" class="thumb-grid">
          <div v-for="(img, i) in (result.items || []).slice(0, 24)" :key="i" class="thumb" :title="img.name">
            <img v-if="img.url" :src="img.url" :alt="img.name" loading="lazy" />
            <span v-else class="thumb-ph">{{ img.name }}</span>
          </div>
        </div>
        <div v-if="(result.items || []).length > 24" class="result-sub">
          仅预览前 24 张，全部 {{ result.items.length }} 张请到「画廊」查看
        </div>
        <div v-if="result.failed_count || result.failed" class="result-warn">
          {{ result.failed_count || result.failed }} 张失败
        </div>
        <div class="result-actions">
          <el-button size="small" plain @click="$emit('go-gallery')">去画廊查看全部</el-button>
        </div>
      </template>

      <!-- 全流程 -->
      <template v-else-if="task.task_type === 'full_pipeline'">
        <div class="result-head">
          <span class="result-title">全流程完成</span>
        </div>
        <div class="pipeline-summary">
          <div class="ps-row">
            <span class="ps-label">提示词</span>
            <span class="ps-value">{{ result.characters_count || 0 }} 位角色</span>
          </div>
          <div class="ps-row">
            <span class="ps-label">剧照</span>
            <span class="ps-value">{{ result.stills_count || 0 }} 张</span>
          </div>
          <div class="ps-row">
            <span class="ps-label">修图</span>
            <span class="ps-value">
              {{ result.edited_count ? `${result.edited_count} 张` : (result.edit_instruction ? '0 张（失败）' : '已跳过') }}
            </span>
          </div>
        </div>
        <div v-if="(result.stills_items || []).length" class="thumb-grid">
          <div v-for="(img, i) in result.stills_items.slice(0, 12)" :key="i" class="thumb" :title="img.name">
            <img v-if="img.url" :src="img.url" :alt="img.name" loading="lazy" />
            <span v-else class="thumb-ph">{{ img.name }}</span>
          </div>
        </div>
        <div class="result-actions">
          <el-button size="small" plain @click="$emit('go-gallery')">去画廊查看全部</el-button>
        </div>
      </template>

      <!-- 其他类型兜底：给个精简摘要，不铺 JSON -->
      <template v-else>
        <div class="result-head">
          <span class="result-title">{{ fallbackSummary }}</span>
        </div>
      </template>
    </div>

    <div v-if="isDone" class="tp-done">
      {{ task.status === 'success' ? '已完成' : statusLabel }}
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { characterDisplayName, characterMeta } from '@/utils/character'

const props = defineProps({
  task: { type: Object, default: null },
})
defineEmits(['go-stills', 'go-gallery'])

const expandedSet = ref(new Set())
const toggleExpand = (i) => {
  const s = new Set(expandedSet.value)
  s.has(i) ? s.delete(i) : s.add(i)
  expandedSet.value = s
}

const typeLabel = computed(() => {
  const map = {
    generate_prompt: '生成提示词',
    generate_stills: '生成剧照',
    edit_image: '修图',
    full_pipeline: '全流程',
  }
  return map[props.task?.task_type] || props.task?.task_type || ''
})

const statusLabel = computed(() => {
  const map = {
    pending: '排队中',
    running: '执行中',
    success: '完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[props.task?.status] || ''
})

const percent = computed(() => {
  if (!props.task) return 0
  const status = props.task.status
  if (status === 'success') return 100
  if (status === 'running') return Math.min(95, 20 + (props.task.progress?.length || 0) * 5)
  if (status === 'pending') return 10
  return 100
})

const recentProgress = computed(() => {
  if (!props.task?.progress) return []
  return props.task.progress.slice(-5)
})

const isDone = computed(() => ['success', 'failed', 'cancelled'].includes(props.task?.status))

const result = computed(() => {
  const r = props.task?.result
  if (!r || typeof r !== 'object') return null
  return r
})

const skippedText = computed(() => {
  const s = result.value?.skipped
  return s ? `（${s} 张已存在，跳过）` : ''
})

const fallbackSummary = computed(() => {
  const r = result.value || {}
  if (r.count !== undefined) return `已处理 ${r.count} 项`
  if (r.total !== undefined) return `共 ${r.total} 项`
  return '已完成'
})

// 兼容 string / object 两种进度项格式
const msgText = (p) => {
  if (typeof p === 'string') return p
  return p.message || p.error || p.type || JSON.stringify(p)
}

// 切换任务时清空展开状态
watch(() => props.task?.id, () => { expandedSet.value = new Set() })
</script>

<style scoped>
.task-progress {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  padding: 16px 20px;
  margin-top: 16px;
}

.tp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.tp-type {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
}

.tp-status {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: var(--radius-full);
}

.status-pending { background: var(--surface-hover); color: var(--text-muted); }
.status-running { background: var(--primary-soft); color: var(--primary-light); }
.status-success { background: var(--success-soft); color: var(--success); }
.status-failed { background: var(--error-soft); color: var(--error); }
.status-cancelled { background: var(--surface-hover); color: var(--text-dim); }

.tp-bar-track {
  height: 6px;
  background: var(--surface-hover);
  border-radius: var(--radius-full);
  overflow: hidden;
  margin-bottom: 12px;
}

.tp-bar-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 0.5s ease;
}

.fill-pending { background: var(--text-muted); animation: pulse 1.5s infinite; }
.fill-running { background: linear-gradient(90deg, var(--primary), var(--primary-light)); }
.fill-success { background: var(--success); }
.fill-failed { background: var(--error); }
.fill-cancelled { background: var(--text-dim); }

.tp-progress-list { margin-top: 8px; }

.tp-progress-item {
  font-size: 12px;
  color: var(--text-muted);
  padding: 2px 0;
  line-height: 1.5;
}

.tp-progress-more {
  font-size: 12px;
  color: var(--text-dim);
  margin-top: 4px;
}

.tp-error {
  color: var(--error);
  font-size: 13px;
  margin-top: 8px;
}

/* ===== 结果区 ===== */
.tp-result-block {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

.result-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.result-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--success);
}

.result-sub {
  font-size: 12px;
  color: var(--text-muted);
}

.result-warn {
  font-size: 12px;
  color: var(--warning, #e6a23c);
  margin-top: 6px;
}

.result-actions {
  margin-top: 12px;
  display: flex;
  gap: 8px;
}

/* 角色列表 */
.char-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 340px;
  overflow-y: auto;
}

.char-item {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 12px;
}

.char-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.char-name {
  font-family: var(--font-serif);
  font-size: 14px;
  font-weight: 600;
  color: var(--accent);
}

.char-meta {
  font-size: 11px;
  color: var(--text-muted);
}

.char-desc {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-muted);
  cursor: pointer;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.char-desc.expanded {
  -webkit-line-clamp: unset;
  display: block;
}

/* 缩略图 */
.thumb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(64px, 1fr));
  gap: 6px;
  margin-top: 8px;
}

.thumb {
  aspect-ratio: 1;
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--bg-2);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.thumb-ph {
  font-size: 9px;
  color: var(--text-dim);
  padding: 2px;
  text-align: center;
  word-break: break-all;
}

/* 全流程摘要 */
.pipeline-summary {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.ps-row {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 12px;
}

.ps-label {
  font-size: 11px;
  color: var(--text-dim);
}

.ps-value {
  font-size: 13px;
  font-weight: 500;
  color: var(--accent);
}

.tp-done {
  margin-top: 10px;
  color: var(--text-muted);
  font-size: 12px;
}
</style>
