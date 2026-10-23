<template>
  <div class="identity-config">
    <div class="config-section">
      <div class="section-label">
        <span class="label-main">
          <el-icon><User /></el-icon>
          <span>身份数量</span>
        </span>
        <span v-if="statusTotal > 0" class="section-total">共 {{ statusTotal }} 人</span>
      </div>
      <div class="counts-grid">
        <div v-for="s in statuses" :key="s" class="count-item" :class="{ active: counts[s] > 0 }">
          <span class="count-label">{{ s }}</span>
          <div class="stepper">
            <button
              type="button"
              class="step-btn"
              :disabled="!counts[s]"
              @click="step(counts, s, -1)"
            >−</button>
            <input
              v-model.number="counts[s]"
              class="step-input"
              type="number"
              min="0"
              @blur="normalize(counts, s)"
            />
            <button type="button" class="step-btn" @click="step(counts, s, 1)">+</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="specials.length > 0" class="config-section">
      <div class="section-label">
        <span class="label-main">
          <el-icon><Star /></el-icon>
          <span>特殊特征（可选）</span>
        </span>
        <span v-if="specialTotal > 0" class="section-total">共 {{ specialTotal }} 个</span>
      </div>
      <div class="counts-grid">
        <div v-for="s in specials" :key="s" class="count-item" :class="{ active: specialsMap[s] > 0 }">
          <span class="count-label">{{ s }}</span>
          <div class="stepper">
            <button
              type="button"
              class="step-btn"
              :disabled="!specialsMap[s]"
              @click="step(specialsMap, s, -1)"
            >−</button>
            <input
              v-model.number="specialsMap[s]"
              class="step-input"
              type="number"
              min="0"
              @blur="normalize(specialsMap, s)"
            />
            <button type="button" class="step-btn" @click="step(specialsMap, s, 1)">+</button>
          </div>
        </div>
      </div>
      <div class="hint-text">特殊特征会自动搭配随机身份生成，可与普通身份共存</div>
    </div>
  </div>
</template>

<script setup>
import { reactive, computed, watch } from 'vue'
import { User, Star } from '@element-plus/icons-vue'

const props = defineProps({
  statuses: { type: Array, default: () => [] },
  specials: { type: Array, default: () => [] },
  modelValue: { type: Object, default: () => ({ counts: {}, specials: {} }) },
})

const emit = defineEmits(['update:modelValue'])

const counts = reactive({})
const specialsMap = reactive({})

const sumOf = (obj) =>
  Object.values(obj).reduce((s, v) => s + (Number(v) > 0 ? Number(v) : 0), 0)

const statusTotal = computed(() => sumOf(counts))
const specialTotal = computed(() => sumOf(specialsMap))

// 初始化 + 同步 props 变化
const initFromProps = () => {
  props.statuses.forEach((s) => {
    if (!(s in counts)) counts[s] = props.modelValue.counts?.[s] || 0
  })
  props.specials.forEach((s) => {
    if (!(s in specialsMap)) specialsMap[s] = props.modelValue.specials?.[s] || 0
  })
}
initFromProps()
watch(() => [props.statuses, props.specials], initFromProps, { deep: true })

// 加减一步
const step = (target, key, delta) => {
  const next = (Number(target[key]) || 0) + delta
  target[key] = next < 0 ? 0 : next
}

// 失焦时把空值/负数/小数规整为非负整数
const normalize = (target, key) => {
  const v = Math.floor(Number(target[key]))
  target[key] = Number.isFinite(v) && v > 0 ? v : 0
}

// 上报变更
watch([counts, specialsMap], () => {
  const selectedCounts = {}
  Object.entries(counts).forEach(([k, v]) => { if (v > 0) selectedCounts[k] = v })
  const selectedSpecials = {}
  Object.entries(specialsMap).forEach(([k, v]) => { if (v > 0) selectedSpecials[k] = v })
  emit('update:modelValue', { counts: selectedCounts, specials: selectedSpecials })
}, { deep: true })

// 暴露获取选中结果的方法
defineExpose({
  getSelected: () => {
    const selectedCounts = {}
    Object.entries(counts).forEach(([k, v]) => { if (v > 0) selectedCounts[k] = v })
    const selectedSpecials = {}
    Object.entries(specialsMap).forEach(([k, v]) => { if (v > 0) selectedSpecials[k] = v })
    return { counts: selectedCounts, specials: selectedSpecials }
  },
  totalCount: () => {
    const c = Object.values(counts).reduce((s, v) => s + (v || 0), 0)
    const s = Object.values(specialsMap).reduce((s, v) => s + (v || 0), 0)
    return c + s
  },
  // 应用模板：先清零，再写入指定值
  applyTemplate: (tplCounts = {}, tplSpecials = {}) => {
    Object.keys(counts).forEach((k) => { counts[k] = tplCounts[k] || 0 })
    Object.keys(specialsMap).forEach((k) => { specialsMap[k] = tplSpecials[k] || 0 })
  },
})
</script>

<style scoped>
.config-section {
  margin-bottom: 18px;
}

.config-section:last-child {
  margin-bottom: 0;
}

.section-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 10px;
  letter-spacing: 0.5px;
}

.label-main {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.section-label .el-icon {
  color: var(--accent);
  font-size: 14px;
}

.section-total {
  font-size: 11px;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid rgba(201, 169, 97, 0.3);
  border-radius: 999px;
  padding: 1px 8px;
  font-variant-numeric: tabular-nums;
}

.counts-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

@media (min-width: 900px) {
  .counts-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.count-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 6px 6px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  transition: border-color 0.18s ease, background 0.18s ease;
}

.count-item:hover {
  border-color: rgba(201, 169, 97, 0.28);
}

.count-item.active {
  background: var(--accent-soft);
  border-color: rgba(201, 169, 97, 0.5);
}

.count-label {
  font-size: 13px;
  color: var(--text-muted);
  transition: color 0.18s ease;
}

.count-item.active .count-label {
  color: var(--text);
}

/* ===== 步进器 ===== */
.stepper {
  display: flex;
  align-items: center;
  gap: 1px;
  padding: 2px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid var(--border-light);
  border-radius: 7px;
  flex-shrink: 0;
}

.count-item.active .stepper {
  background: rgba(201, 169, 97, 0.12);
  border-color: rgba(201, 169, 97, 0.32);
}

.step-btn {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  border-radius: 4px;
  color: var(--text);
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;
}

.step-btn:hover:not(:disabled) {
  color: var(--accent);
  background: rgba(201, 169, 97, 0.14);
}

.step-btn:disabled {
  opacity: 0.26;
  cursor: not-allowed;
}

.step-input {
  width: 34px;
  height: 22px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  text-align: center;
  outline: none;
  border-radius: 4px;
  transition: background 0.15s ease, color 0.15s ease;
  -moz-appearance: textfield;
  appearance: textfield;
}

.step-input::-webkit-outer-spin-button,
.step-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.step-input:focus {
  background: rgba(255, 255, 255, 0.07);
}

.count-item.active .step-input {
  color: var(--accent);
  font-weight: 600;
}

.hint-text {
  font-size: 12px;
  color: var(--text-dim);
  margin-top: 8px;
  line-height: 1.5;
}
</style>
