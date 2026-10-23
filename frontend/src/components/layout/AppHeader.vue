<template>
  <header class="app-header">
    <div class="header-left">
      <el-button class="collapse-btn" text @click="uiStore.toggleSidebar()">
        <el-icon><Fold v-if="!uiStore.sidebarCollapsed" /><Expand v-else /></el-icon>
      </el-button>
      <div class="logo">🎭</div>
      <div class="title-group">
        <h1>古装剧照批量生成</h1>
        <div class="subtitle">墨韵丹青 · AI古风人物工坊</div>
      </div>
    </div>
    <div class="header-right">
      <div class="status-indicator" :title="`ComfyUI: ${optionsStore.comfyuiUrl}\nOllama: ${optionsStore.ollamaUrl}\n模型: ${optionsStore.model}`">
        <span class="dot" :class="{ online: tasksStore.wsConnected }"></span>
        <span>{{ tasksStore.wsConnected ? '任务通道已连接' : '任务通道连接中...' }}</span>
      </div>
    </div>
  </header>
</template>

<script setup>
import { Fold, Expand } from '@element-plus/icons-vue'
import { useUiStore } from '@/stores/ui'
import { useOptionsStore } from '@/stores/options'
import { useTasksStore } from '@/stores/tasks'

const tasksStore = useTasksStore()
const uiStore = useUiStore()
const optionsStore = useOptionsStore()
</script>

<style scoped>
.app-header {
  height: var(--header-h);
  background: var(--bg-2);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  gap: 24px;
  flex-shrink: 0;
  position: relative;
}

.app-header::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: 0.4;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.collapse-btn {
  color: var(--text-muted);
  padding: 6px;
}

.logo {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--primary), var(--primary-dark));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  box-shadow: var(--shadow-primary);
}

.title-group h1 {
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 1px;
  color: var(--text);
  white-space: nowrap;
}

.subtitle {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 1px;
  white-space: nowrap;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: var(--radius-full);
  background: var(--surface);
  font-size: 12px;
  color: var(--text-muted);
  cursor: help;
}

.status-indicator .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-dim);
  transition: background var(--transition);
}

.status-indicator .dot.online {
  background: var(--success);
  box-shadow: 0 0 6px var(--success);
}

.user-badge {
  padding: 4px 14px;
  border-radius: var(--radius-full);
  background: var(--surface);
  color: var(--accent);
  font-size: 12px;
  cursor: pointer;
  transition: background var(--transition);
}

.user-badge:hover {
  background: var(--surface-hover);
}

@media (max-width: 1024px) {
  .subtitle { display: none; }
}
</style>
