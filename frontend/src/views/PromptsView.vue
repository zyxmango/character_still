<template>
  <div>
    <PageHeader icon="EditPen" title="生成人物提示词" desc="选择风格与身份配比，由 Qwen 大模型生成符合古装剧照要求的双语提示词" />

    <div class="workbench">
      <!-- 左：参数面板 -->
      <div class="param-panel">
        <div class="app-card">
          <div class="app-card-title">风格选择</div>
          <el-select v-model="form.style" placeholder="选择风格" style="width: 100%">
            <el-option v-for="s in optionsStore.styles" :key="s" :label="s" :value="s" />
          </el-select>
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
            {{ submitting ? '执行中...' : '生成提示词' }}
          </el-button>
        </div>

        <TaskProgress :task="tasksStore.currentTask" @go-stills="goStills" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/common/PageHeader.vue'
import IdentityConfig from '@/components/common/IdentityConfig.vue'
import TaskProgress from '@/components/common/TaskProgress.vue'
import { useOptionsStore } from '@/stores/options'
import { useTasksStore } from '@/stores/tasks'

const optionsStore = useOptionsStore()
const tasksStore = useTasksStore()
const router = useRouter()

// 生成提示词完成后，一键带着这批提示词跳去出图
const goStills = (result) => {
  router.push({ path: '/stills', query: { prompts_file: result.prompts_file } })
}

const form = reactive({ style: optionsStore.styles[0] || '' })
const submitting = ref(false)
const identityConfig = ref(null)

const submit = async () => {
  const { counts, specials } = identityConfig.value.getSelected()
  if (Object.keys(counts).length === 0 && Object.keys(specials).length === 0) {
    ElMessage.warning('请至少选择一个身份或特殊特征')
    return
  }
  const args = { style: form.style, counts }
  if (Object.keys(specials).length > 0) args.specials = specials

  submitting.value = true
  tasksStore.clearCurrentTask()
  try {
    await tasksStore.submitTask('generate_prompt', args)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
</style>
