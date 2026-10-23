<template>
  <!-- v2.2 起免登录，直接显示主界面 -->
  <div class="app-layout">
    <AppHeader />
    <div class="app-body">
      <SideNav />
      <main class="workspace">
        <div class="ws-container">
          <router-view />
        </div>
      </main>
    </div>
    <ImageModal />
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useOptionsStore } from '@/stores/options'
import { useTasksStore } from '@/stores/tasks'
import AppHeader from '@/components/layout/AppHeader.vue'
import SideNav from '@/components/layout/SideNav.vue'
import ImageModal from '@/components/common/ImageModal.vue'

const optionsStore = useOptionsStore()
const tasksStore = useTasksStore()

onMounted(async () => {
  // 直接建立任务通道 + 拉取全局选项
  tasksStore.connectWS()
  await optionsStore.fetchOptions()
})

onUnmounted(() => {
  tasksStore.disconnectWS()
})
</script>

<style scoped>
.app-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.app-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}
</style>
