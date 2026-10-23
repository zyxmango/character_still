<template>
  <div class="page-header">
    <div class="page-icon">
      <el-icon><component :is="icon" /></el-icon>
    </div>
    <div class="page-text">
      <div class="page-title">{{ title }}</div>
      <div class="page-desc" v-if="desc">{{ desc }}</div>
    </div>
    <div class="page-actions" v-if="$slots.actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  desc: { type: String, default: '' },
  icon: { type: String, default: 'Document' },
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.page-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--primary-soft);
  border: 1px solid rgba(200, 65, 44, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: var(--primary-light);
  flex-shrink: 0;
}

.page-text {
  flex: 1;
  min-width: 0;
}

.page-title {
  font-family: var(--font-serif);
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 1px;
  color: var(--text);
}

.page-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin-top: 2px;
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
</style>
