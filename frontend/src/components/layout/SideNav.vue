<template>
  <nav class="side-nav" :class="{ collapsed: uiStore.sidebarCollapsed }">
    <el-tooltip
      v-for="item in navItems"
      :key="item.name"
      :content="item.label"
      placement="right"
      :disabled="!uiStore.sidebarCollapsed"
    >
      <router-link
        custom
        :to="item.path"
        v-slot="{ navigate, isActive }"
      >
        <div
          class="nav-item"
          :class="{ active: isActive }"
          @click="navigate"
        >
          <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
          <span class="nav-label">{{ item.label }}</span>
          <span v-if="item.name === 'tasks' && tasksStore.activeTaskCount > 0" class="nav-badge">
            {{ tasksStore.activeTaskCount }}
          </span>
        </div>
      </router-link>
    </el-tooltip>
  </nav>
</template>

<script setup>
import { useTasksStore } from '@/stores/tasks'
import { useUiStore } from '@/stores/ui'

const tasksStore = useTasksStore()
const uiStore = useUiStore()

const navItems = [
  { name: 'prompts', path: '/prompts', icon: 'EditPen', label: '提示词' },
  { name: 'stills', path: '/stills', icon: 'Picture', label: '剧照' },
  { name: 'edit', path: '/edit', icon: 'MagicStick', label: '修图' },
  { name: 'pipeline', path: '/pipeline', icon: 'Connection', label: '全流程' },
  { name: 'tasks', path: '/tasks', icon: 'Lightning', label: '任务' },
  { name: 'gallery', path: '/gallery', icon: 'Files', label: '画廊' },
  { name: 'guide', path: '/guide', icon: 'Document', label: '工程' },
  { name: 'metrics', path: '/metrics', icon: 'Monitor', label: '监控' },
]
</script>

<style scoped>
.side-nav {
  width: var(--nav-w);
  background: var(--bg-2);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 12px 0;
  flex-shrink: 0;
  transition: width var(--transition-slow);
}

.side-nav.collapsed {
  width: 56px;
}

.side-nav.collapsed .nav-label {
  display: none;
}

.side-nav.collapsed .nav-item {
  padding: 12px 0;
  margin: 2px 8px;
}

.side-nav.collapsed .nav-badge {
  right: 4px;
}

.nav-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 12px 8px;
  cursor: pointer;
  color: var(--text-muted);
  transition: all var(--transition);
  border-radius: var(--radius);
  margin: 2px 8px;
}

.nav-item:hover {
  color: var(--text);
  background: var(--surface);
}

.nav-item.active {
  color: var(--primary-light);
  background: var(--primary-soft);
}

.nav-item.active::before {
  content: '';
  position: absolute;
  left: -8px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 28px;
  border-radius: 0 2px 2px 0;
  background: linear-gradient(180deg, var(--primary), var(--accent));
}

.nav-icon {
  font-size: 20px;
}

.nav-label {
  font-size: 11px;
  letter-spacing: 0.5px;
}

.nav-badge {
  position: absolute;
  top: 6px;
  right: 12px;
  min-width: 16px;
  height: 16px;
  border-radius: var(--radius-full);
  background: var(--primary);
  color: #fff;
  font-size: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 4px;
}
</style>
