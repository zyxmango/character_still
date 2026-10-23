import { defineStore } from 'pinia'
import { tasksApi } from '@/api'

// 后端 progress_item 是 {type, message} 对象，统一归一化为文本，避免消费方按字符串处理时崩溃
const normalizeProgress = (p) => {
  if (typeof p === 'string') return p
  if (!p || typeof p !== 'object') return String(p ?? '')
  return p.message || p.error || p.type || ''
}

/**
 * 任务 Store：基于 WebSocket 实时推送（/ws/tasks），HTTP 轮询作为降级保底。
 *
 * 事件协议（后端 -> 前端）：
 *   snapshot        初始任务列表快照
 *   task_submitted  新任务已提交（pending）
 *   task_running    任务开始执行
 *   task_progress   进度增量（progress_item + progress_count）
 *   task_success    任务成功（含 result）
 *   task_failed     任务失败（含 error）
 *   task_cancelled  任务已取消
 *   ping            心跳保活（忽略）
 */
export const useTasksStore = defineStore('tasks', {
  state: () => ({
    tasks: [],
    activeTaskCount: 0,
    // 当前正在跟踪的任务（从页面提交的）
    currentTask: null,
    // WebSocket 连接
    ws: null,
    wsConnected: false,
    // 降级轮询定时器（仅在 WS 断开时启用）
    pollingTimer: null,
    // 重连控制
    reconnectTimer: null,
    reconnectAttempts: 0,
  }),
  getters: {
    hasActive: (state) => state.activeTaskCount > 0,
  },
  actions: {
    // ============ 任务提交 ============
    async submitTask(taskType, args) {
      const data = await tasksApi.submit(taskType, args)
      // task_type 必须带上，TaskProgress 靠它决定结果区怎么渲染
      this.currentTask = {
        id: data.task_id,
        task_type: taskType,
        status: 'pending',
        progress: [],
        result: null,
      }
      // WS 已连接时无需轮询；未连接时降级轮询
      if (!this.wsConnected) {
        this.startPollingCurrent()
      }
      await this.fetchTasks()
      return data
    },

    async fetchTasks() {
      try {
        const data = await tasksApi.list(30)
        this.tasks = (data || []).map((t) => this._normalizeTask(t))
        this._recountActive()
        // 同步更新 currentTask（如果存在）
        if (this.currentTask) {
          const found = this.tasks.find((t) => t.task_id === this.currentTask.id)
          if (found) {
            this.currentTask = { ...this.currentTask, ...found }
          }
        }
      } catch (e) {
        console.error('获取任务列表失败:', e)
      }
    },

    async cancelTask(taskId) {
      await tasksApi.cancel(taskId)
      // WS 会推送 task_cancelled；保险起见立即刷新一次
      if (!this.wsConnected) await this.fetchTasks()
    },

    // ============ WebSocket 连接 ============
    connectWS() {
      if (this.ws) return
      // v2.2 起免登录，WS 无需 token
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const url = `${protocol}//${window.location.host}/ws/tasks`
      let ws
      try {
        ws = new WebSocket(url)
      } catch (e) {
        console.warn('任务 WS 创建失败，降级轮询:', e)
        this._startFallbackPolling()
        return
      }
      this.ws = ws

      ws.onopen = () => {
        this.wsConnected = true
        this.reconnectAttempts = 0
        // WS 连上后停掉降级轮询
        this._stopFallbackPolling()
        if (this.pollingTimer) {
          clearInterval(this.pollingTimer)
          this.pollingTimer = null
        }
      }

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data)
          this._handleEvent(data)
        } catch (e) {
          // 忽略解析失败
        }
      }

      ws.onerror = () => {
        // 不主动关闭，交给 onclose 处理重连
      }

      ws.onclose = () => {
        this.ws = null
        this.wsConnected = false
        // 如果 currentTask 还在执行中，立即启动降级轮询
        if (this.currentTask && ['pending', 'running'].includes(this.currentTask.status)) {
          this.startPollingCurrent()
        }
        // 指数退避重连（最多 30 秒）
        this.reconnectAttempts++
        const delay = Math.min(30000, 1000 * Math.pow(1.6, this.reconnectAttempts))
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
        this.reconnectTimer = setTimeout(() => this.connectWS(), delay)
      }
    },

    disconnectWS() {
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
      }
      if (this.ws) {
        try {
          this.ws.onclose = null
          this.ws.close()
        } catch (e) {}
        this.ws = null
      }
      this.wsConnected = false
      this._stopFallbackPolling()
    },

    // ============ 事件处理 ============
    _handleEvent(event) {
      if (!event || !event.type) return
      switch (event.type) {
        case 'ping':
          return
        case 'snapshot':
          this.tasks = (event.tasks || []).map((t) => this._normalizeTask(t))
          this._recountActive()
          // 若 currentTask 在快照中，同步状态
          if (this.currentTask) {
            const found = this.tasks.find((t) => t.task_id === this.currentTask.id)
            if (found) this.currentTask = { ...this.currentTask, ...found }
          }
          return
        case 'task_submitted': {
          // 新任务入列
          const tid = event.task_id
          if (!this.tasks.find((t) => t.task_id === tid)) {
            this.tasks.unshift({
              task_id: tid,
              task_type: event.task_type,
              args: {},
              status: event.status,
              progress: [],
              created_at: event.created_at,
              user_id: event.user_id,
            })
            this._recountActive()
          }
          this._syncCurrent(event)
          return
        }
        case 'task_running':
        case 'task_success':
        case 'task_failed':
        case 'task_cancelled': {
          this._patchTask(event.task_id, {
            status: event.status,
            result: event.result,
            error: event.error,
            started_at: event.started_at,
            finished_at: event.finished_at,
          })
          this._syncCurrent(event)
          return
        }
        case 'task_progress': {
          // 进度增量：把 progress_item 追加到对应任务的 progress 列表
          const t = this.tasks.find((x) => x.task_id === event.task_id)
          if (t) {
            if (!t.progress) t.progress = []
            // 用 progress_count 校准长度，避免重复
            if (event.progress_count && event.progress_count > t.progress.length) {
              t.progress.push(normalizeProgress(event.progress_item))
            } else if (!event.progress_count) {
              t.progress.push(normalizeProgress(event.progress_item))
            }
          }
          this._syncCurrent(event)
          return
        }
        default:
          return
      }
    },

    // 把任务对象里的 progress 统一为字符串数组
    _normalizeTask(t) {
      if (!t) return t
      t.progress = Array.isArray(t.progress) ? t.progress.map(normalizeProgress) : []
      return t
    },

    _patchTask(taskId, patch) {
      const t = this.tasks.find((x) => x.task_id === taskId)
      if (!t) return
      Object.assign(t, patch)
      this._recountActive()
    },

    _syncCurrent(event) {
      if (!this.currentTask || this.currentTask.id !== event.task_id) return
      // 合并事件到 currentTask
      const patch = { status: event.status }
      if (event.result !== undefined) patch.result = event.result
      if (event.error !== undefined) patch.error = event.error
      if (event.started_at) patch.started_at = event.started_at
      if (event.finished_at) patch.finished_at = event.finished_at
      if (event.type === 'task_progress' && event.progress_item) {
        if (!this.currentTask.progress) this.currentTask.progress = []
        if (event.progress_count && event.progress_count > this.currentTask.progress.length) {
          this.currentTask.progress.push(normalizeProgress(event.progress_item))
        } else if (!event.progress_count) {
          this.currentTask.progress.push(normalizeProgress(event.progress_item))
        }
        patch.progress = this.currentTask.progress
      }
      this.currentTask = { ...this.currentTask, ...patch }
      // 任务结束清理
      if (['success', 'failed', 'cancelled'].includes(event.status)) {
        this.stopPollingCurrent()
      }
    },

    _recountActive() {
      this.activeTaskCount = this.tasks.filter(
        (t) => t.status === 'pending' || t.status === 'running'
      ).length
    },

    // ============ 降级轮询（WS 不可用时）============
    startPollingCurrent() {
      if (this.pollingTimer) clearInterval(this.pollingTimer)
      this.pollingTimer = setInterval(async () => {
        if (!this.currentTask) return
        try {
          const data = await tasksApi.get(this.currentTask.id)
          this.currentTask = { ...this.currentTask, ...this._normalizeTask(data) }
          if (['success', 'failed', 'cancelled'].includes(data.status)) {
            this.stopPollingCurrent()
            await this.fetchTasks()
          }
        } catch (e) {
          console.error('轮询任务失败:', e)
        }
      }, 1500)
    },

    stopPollingCurrent() {
      if (this.pollingTimer) {
        clearInterval(this.pollingTimer)
        this.pollingTimer = null
      }
    },

    _startFallbackPolling() {
      // WS 不可用时的整体列表轮询
      if (this._fallbackTimer) return
      this._fallbackTimer = setInterval(() => this.fetchTasks(), 5000)
    },

    _stopFallbackPolling() {
      if (this._fallbackTimer) {
        clearInterval(this._fallbackTimer)
        this._fallbackTimer = null
      }
    },

    clearCurrentTask() {
      this.stopPollingCurrent()
      this.currentTask = null
    },
  },
})
