<template>
  <div>
    <PageHeader icon="Monitor" title="系统监控" desc="GPU 状态、任务队列、服务健康、API 调用量一览">
      <template #actions>
        <el-button text size="small" @click="autoRefresh = !autoRefresh">
          <span class="dot-live" v-if="autoRefresh"></span>{{ autoRefresh ? '自动刷新中' : '已暂停' }}
        </el-button>
        <el-button type="primary" size="small" @click="loadMetrics">刷新</el-button>
      </template>
    </PageHeader>

    <div v-if="loading && !metrics" class="empty-state"><div class="text">加载中...</div></div>

    <div v-if="metrics" class="metrics-wrap">
      <!-- 任务队列概览 -->
      <div class="app-card metric-card">
        <div class="card-title">
          <el-icon><Lightning /></el-icon>
          <span>任务队列</span>
        </div>
        <div class="metric-grid">
          <div class="metric-item">
            <div class="metric-num">{{ metrics.task_summary.total }}</div>
            <div class="metric-label">总任务</div>
          </div>
          <div class="metric-item">
            <div class="metric-num c-pending">{{ metrics.task_summary.queued }}</div>
            <div class="metric-label">排队中</div>
          </div>
          <div class="metric-item">
            <div class="metric-num c-running">{{ metrics.task_summary.running }}</div>
            <div class="metric-label">执行中</div>
          </div>
          <div class="metric-item">
            <div class="metric-num c-success">{{ metrics.task_summary.success }}</div>
            <div class="metric-label">已完成</div>
          </div>
          <div class="metric-item">
            <div class="metric-num c-failed">{{ metrics.task_summary.failed }}</div>
            <div class="metric-label">失败</div>
          </div>
          <div class="metric-item">
            <div class="metric-num c-cancelled">{{ metrics.task_summary.cancelled }}</div>
            <div class="metric-label">已取消</div>
          </div>
        </div>
      </div>

      <!-- GPU 状态（仅 admin）-->
      <div v-if="metrics.gpu" class="app-card metric-card">
        <div class="card-title">
          <el-icon><Cpu /></el-icon>
          <span>GPU 状态</span>
        </div>
        <div v-for="(g, i) in metrics.gpu" :key="i" class="gpu-row">
          <div class="gpu-name">{{ g.name }}</div>
          <div class="gpu-bars">
            <div class="bar-item">
              <span class="bar-label">显存</span>
              <div class="bar-track">
                <div class="bar-fill c-mem" :style="{ width: memPct(g) + '%' }"></div>
              </div>
              <span class="bar-text">{{ g.memory_used_mb }} / {{ g.memory_total_mb }} MB</span>
            </div>
            <div class="bar-item">
              <span class="bar-label">利用率</span>
              <div class="bar-track">
                <div class="bar-fill c-util" :style="{ width: g.utilization_pct + '%' }"></div>
              </div>
              <span class="bar-text">{{ g.utilization_pct }}%</span>
            </div>
            <div class="bar-item">
              <span class="bar-label">温度</span>
              <div class="bar-track">
                <div class="bar-fill c-temp" :style="{ width: tempPct(g.temperature_c) + '%' }"></div>
              </div>
              <span class="bar-text">{{ g.temperature_c }}°C</span>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="app-card metric-card">
        <div class="card-title">
          <el-icon><Cpu /></el-icon>
          <span>GPU 状态</span>
        </div>
        <div class="empty-hint">未检测到 NVIDIA GPU 或 nvidia-smi 不可用</div>
      </div>

      <!-- 服务健康 -->
      <div class="app-card metric-card">
        <div class="card-title">
          <el-icon><Connection /></el-icon>
          <span>服务健康</span>
        </div>
        <div class="service-list">
          <div class="service-row">
            <span class="svc-name">Ollama（提示词模型）</span>
            <span class="svc-status" :class="svcClass(metrics.services.ollama?.status)">
              {{ metrics.services.ollama?.status === 'ok' ? '✅ 正常' : '❌ ' + metrics.services.ollama?.status }}
            </span>
            <span class="svc-detail" v-if="metrics.services.ollama?.models?.length">
              {{ metrics.services.ollama.models.join(', ') }}
            </span>
          </div>
          <div class="service-row">
            <span class="svc-name">ComfyUI（出图）</span>
            <span class="svc-status" :class="svcClass(metrics.services.comfyui?.status)">
              {{ metrics.services.comfyui?.status === 'ok' ? '✅ 正常' : '❌ ' + metrics.services.comfyui?.status }}
            </span>
            <span class="svc-detail" v-if="metrics.services.comfyui?.device">
              {{ metrics.services.comfyui.device }}
            </span>
          </div>
          <div class="service-row">
            <span class="svc-name">DashScope（云端API）</span>
            <span class="svc-status" :class="metrics.services.dashscope?.configured ? 'ok' : 'warn'">
              {{ metrics.services.dashscope?.configured ? '✅ 已配置' : '⚠️ 未配置' }}
            </span>
            <span class="svc-detail">
              对话: {{ metrics.services.dashscope?.chat_model }} · 视觉: {{ metrics.services.dashscope?.vl_model }}
            </span>
          </div>
        </div>
      </div>

      <!-- 磁盘输出统计 -->
      <div class="app-card metric-card">
        <div class="card-title">
          <el-icon><Files /></el-icon>
          <span>磁盘输出</span>
        </div>
        <div class="metric-grid grid-3">
          <div class="metric-item">
            <div class="metric-num">{{ metrics.disk.prompts_files }}</div>
            <div class="metric-label">Prompts 文件</div>
          </div>
          <div class="metric-item">
            <div class="metric-num c-success">{{ metrics.disk.stills_images }}</div>
            <div class="metric-label">剧照图片</div>
          </div>
          <div class="metric-item">
            <div class="metric-num c-running">{{ metrics.disk.edited_images }}</div>
            <div class="metric-label">修图结果</div>
          </div>
        </div>
      </div>

      <!-- API 调用量（仅 admin）-->
      <div v-if="metrics.api_calls" class="app-card metric-card">
        <div class="card-title">
          <el-icon><DataLine /></el-icon>
          <span>API 调用量（进程内）</span>
        </div>
        <div class="api-bars">
          <div v-for="(v, k) in metrics.api_calls" :key="k" class="api-bar-row">
            <span class="api-name">{{ apiLabel(k) }}</span>
            <div class="bar-track">
              <div class="bar-fill c-api" :style="{ width: apiPct(v) + '%' }"></div>
            </div>
            <span class="bar-text">{{ v }}</span>
          </div>
        </div>
      </div>

      <!-- 系统配置 -->
      <div class="app-card metric-card">
        <div class="card-title">
          <el-icon><Setting /></el-icon>
          <span>系统配置</span>
        </div>
        <div class="config-list">
          <div class="config-row">
            <span class="cfg-key">最大并发任务</span>
            <span class="cfg-val">{{ metrics.config.max_concurrent_tasks }}</span>
          </div>
          <div class="config-row">
            <span class="cfg-key">使用云端API对话</span>
            <span class="cfg-val">{{ metrics.config.use_api_for_chat ? '是' : '否' }}</span>
          </div>
          <div class="config-row">
            <span class="cfg-key">提示词模型</span>
            <span class="cfg-val">{{ metrics.config.ollama_model }}</span>
          </div>
          <div class="config-row">
            <span class="cfg-key">评估及格线</span>
            <span class="cfg-val">{{ metrics.config.evaluate_threshold }} 分</span>
          </div>
        </div>
      </div>
    </div>

    <div class="hint-text">
      💡 自动刷新间隔 10 秒 · GPU/API 调用量仅管理员可见 · 任务队列统计来自数据库（最近 200 条）
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Lightning, Cpu, Connection, Files, DataLine, Setting, Monitor } from '@element-plus/icons-vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { metricsApi } from '@/api'

const metrics = ref(null)
const loading = ref(false)
const autoRefresh = ref(true)
let timer = null

onMounted(() => {
  loadMetrics()
  timer = setInterval(() => {
    if (autoRefresh.value) loadMetrics(true)
  }, 10000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

const loadMetrics = async (silent = false) => {
  if (!silent) loading.value = true
  try {
    metrics.value = await metricsApi.get()
  } catch (e) {
    if (!silent) ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    loading.value = false
  }
}

const svcClass = (status) => {
  if (!status) return ''
  return status === 'ok' ? 'ok' : 'down'
}

const memPct = (g) => {
  if (!g.memory_total_mb) return 0
  return Math.round((g.memory_used_mb / g.memory_total_mb) * 100)
}

const tempPct = (t) => {
  // 0-100°C 映射
  return Math.min(100, Math.max(0, t))
}

const apiMax = computed(() => {
  if (!metrics.value?.api_calls) return 1
  return Math.max(1, ...Object.values(metrics.value.api_calls))
})

const apiPct = (v) => {
  return Math.round((v / apiMax.value) * 100)
}

const apiLabel = (k) => {
  const map = {
    chat: '对话',
    generate_prompt: '生成提示词',
    generate_stills: '生成剧照',
    edit_image: '修图',
    full_pipeline: '全流程',
    evaluate: '质量评估',
    export: '导出',
    other: '其他',
  }
  return map[k] || k
}
</script>

<style scoped>
.metrics-wrap {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.metric-card {
  padding: 16px 18px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border, rgba(255,255,255,0.06));
}
.card-title .el-icon {
  color: var(--accent);
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 10px;
}
.metric-grid.grid-3 {
  grid-template-columns: repeat(3, 1fr);
}
.metric-item {
  text-align: center;
  padding: 10px 4px;
  background: var(--surface);
  border-radius: 8px;
}
.metric-num {
  font-size: 24px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
}
.metric-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
}

.c-pending { color: #909399; }
.c-running { color: #409eff; }
.c-success { color: #67c23a; }
.c-failed { color: #f56c6c; }
.c-cancelled { color: #e6a23c; }

/* GPU */
.gpu-row {
  padding: 10px 0;
  border-bottom: 1px solid var(--border, rgba(255,255,255,0.05));
}
.gpu-row:last-child { border-bottom: none; }
.gpu-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 8px;
}
.gpu-bars {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bar-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.bar-label {
  width: 48px;
  color: var(--text-muted);
}
.bar-track {
  flex: 1;
  height: 8px;
  background: var(--surface);
  border-radius: 4px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.5s ease;
}
.c-mem { background: linear-gradient(90deg, #409eff, #67c23a); }
.c-util { background: linear-gradient(90deg, #e6a23c, #f56c6c); }
.c-temp { background: linear-gradient(90deg, #67c23a, #f56c6c); }
.c-api { background: linear-gradient(90deg, #9c6ade, #409eff); }
.bar-text {
  min-width: 110px;
  text-align: right;
  color: var(--text-muted);
  font-size: 11px;
}

/* 服务健康 */
.service-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.service-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--surface);
  border-radius: 8px;
  font-size: 13px;
}
.svc-name {
  flex: 1;
  font-weight: 500;
  color: var(--text);
}
.svc-status {
  font-weight: 600;
}
.svc-status.ok { color: #67c23a; }
.svc-status.down { color: #f56c6c; }
.svc-status.warn { color: #e6a23c; }
.svc-detail {
  font-size: 11px;
  color: var(--text-muted);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* API bars */
.api-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.api-bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.api-name {
  width: 90px;
  color: var(--text-muted);
}

/* 配置列表 */
.config-list {
  display: flex;
  flex-direction: column;
}
.config-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid var(--border, rgba(255,255,255,0.04));
  font-size: 13px;
}
.config-row:last-child { border-bottom: none; }
.cfg-key { color: var(--text-muted); }
.cfg-val { color: var(--text); font-weight: 500; }

.empty-hint {
  padding: 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
}

.empty-state {
  padding: 40px;
  text-align: center;
  color: var(--text-muted);
}

.dot-live {
  display: inline-block;
  width: 6px;
  height: 6px;
  background: #67c23a;
  border-radius: 50%;
  margin-right: 4px;
  animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.hint-text {
  font-size: 12px;
  color: var(--text-muted);
  padding: 10px 16px;
  background: var(--surface);
  border-radius: 8px;
  border-left: 3px solid var(--accent);
}
</style>
