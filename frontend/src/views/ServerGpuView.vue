<template>
  <div>
    <el-alert
      v-if="!agentOnline"
      data-testid="agent-offline-banner"
      type="error"
      :closable="false"
      show-icon
      class="block"
      title="Agent 离线"
      :description="agentMessage || '无法连接宿主机 poem-video-agent,GPU 状态不可用(不会显示为 0 张卡)'"
    />

    <el-card shadow="never" class="block" data-testid="gpu-summary">
      <template #header>
        <div class="card-header-row">
          <span class="block-title">GPU 摘要</span>
          <el-button data-testid="gpu-refresh-btn" size="small" @click="refresh(true)">手动刷新</el-button>
        </div>
      </template>
      <div v-if="agentOnline" class="summary-grid">
        <div class="summary-item"><span class="s-name">GPU 数量</span><span class="s-val">{{ gpus.length }} 张</span></div>
        <div class="summary-item"><span class="s-name">总显存</span><span class="s-val">{{ fmtMiB(totalMem) }}</span></div>
        <div class="summary-item"><span class="s-name">已用显存</span><span class="s-val">{{ fmtMiB(usedMem) }}</span></div>
        <div class="summary-item"><span class="s-name">最高温度</span><span class="s-val">{{ maxTemp == null ? '-' : maxTemp + '℃' }}</span></div>
        <div class="summary-item"><span class="s-name">当前总功耗</span><span class="s-val">{{ totalDraw == null ? '-' : Math.round(totalDraw) + 'W' }}</span></div>
      </div>
      <div v-else>Agent 不可达,无法读取 GPU 状态。</div>
    </el-card>

    <el-card shadow="never" class="block" data-testid="gpu-power-card">
      <template #header><span class="block-title">Power Limit 控制</span></template>
      <el-form label-width="130px" class="power-form">
        <el-form-item label="全部设置为">
          <div class="inline-controls">
            <el-input-number
              v-model="bulkWatts"
              data-testid="bulk-watts-input"
              :min="50"
              :max="1000"
              :step="10"
            />
            <el-button type="primary" data-testid="bulk-apply-btn" :disabled="!agentOnline" @click="applyAll">全部应用</el-button>
          </div>
        </el-form-item>
        <el-form-item label="默认功耗值">
          <div class="inline-controls">
            <el-input-number
              v-model="defaultWatts"
              data-testid="default-watts-input"
              :min="50"
              :max="1000"
              :step="10"
            />
            <el-button data-testid="default-save-btn" :disabled="!agentOnline" @click="saveDefault">保存并立即应用</el-button>
          </div>
        </el-form-item>
        <el-form-item label="开机自动应用">
          <div class="inline-controls">
            <el-switch v-model="autoApply" data-testid="auto-apply-switch" :disabled="!agentOnline" @change="toggleAutoApply" />
            <span class="hint">服务器重启后自动恢复配置的 Power Limit(Agent 侧 systemd oneshot)</span>
          </div>
        </el-form-item>
      </el-form>
    </el-card>

    <div v-if="agentOnline" class="gpu-grid">
      <el-card
        v-for="gpu in gpus"
        :key="gpu.index"
        shadow="never"
        class="gpu-card"
        :data-testid="`gpu-card-${gpu.index}`"
      >
        <template #header>
          <div class="card-header-row">
            <span class="block-title">GPU {{ gpu.index }} · {{ gpu.name || '未知型号' }}</span>
            <div class="inline-controls">
              <el-input-number
                v-model="cardWatts[gpu.index]"
                :data-testid="`card-watts-${gpu.index}`"
                size="small"
                :min="gpu.min_power_limit_w ?? 50"
                :max="gpu.max_power_limit_w ?? 1000"
                :step="10"
                @focus="editingIndex = gpu.index"
                @change="editingIndex = gpu.index"
              />
              <el-button
                size="small"
                type="primary"
                plain
                :data-testid="`card-apply-${gpu.index}`"
                @click="applyOne(gpu.index)"
              >设为</el-button>
            </div>
          </div>
        </template>
        <div class="gpu-fields">
          <div class="f"><span>温度</span><b>{{ gpu.temperature_c == null ? '-' : gpu.temperature_c + '℃' }}</b></div>
          <div class="f"><span>GPU利用率</span><b>{{ gpu.utilization_gpu_percent == null ? '-' : gpu.utilization_gpu_percent + '%' }}</b></div>
          <div class="f">
            <span>显存</span>
            <b>{{ fmtMiB(gpu.memory_used_mib) }} / {{ fmtMiB(gpu.memory_total_mib) }}</b>
          </div>
          <div class="f"><span>当前功耗</span><b>{{ gpu.power_draw_w == null ? '-' : Math.round(gpu.power_draw_w) + 'W' }}</b></div>
          <div class="f"><span>功耗上限</span><b>{{ gpu.power_limit_w == null ? '-' : Math.round(gpu.power_limit_w) + 'W' }}</b></div>
          <div class="f" v-if="gpu.min_power_limit_w != null && gpu.max_power_limit_w != null">
            <span>允许区间</span><b>{{ gpu.min_power_limit_w }}~{{ gpu.max_power_limit_w }}W</b>
          </div>
          <div class="f"><span>P-State</span><b>{{ gpu.pstate || '-' }}</b></div>
        </div>
        <div class="proc-title">进程({{ (gpu.processes || []).length }})<el-tag size="small" type="info">非受管进程 · 只读</el-tag></div>
        <div v-if="(gpu.processes || []).length" class="proc-list">
          <div v-for="(p, pi) in gpu.processes" :key="`${gpu.index}-${p.pid ?? pi}`" class="proc-item">
            PID {{ p.pid }} · {{ p.process_name || '?' }} · {{ p.used_gpu_memory_mib == null ? '?' : p.used_gpu_memory_mib + ' MiB' }}
          </div>
        </div>
        <div v-else class="proc-empty">无 GPU 计算进程</div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getGpuPowerSettings,
  getServerGpus,
  putGpuPowerSettings,
  setAllGpuPowerLimit,
  setGpuPowerLimit,
} from '@/api'
import type { GpuInfo } from '@/types'

const gpus = ref<GpuInfo[]>([])
const agentOnline = ref(true)
const agentMessage = ref('')
const editingIndex = ref<number | null>(null)
const bulkWatts = ref(280)
const defaultWatts = ref<number | null>(280)
const autoApply = ref(false)
const cardWatts = reactive<Record<number, number | null>>({})

const totalMem = computed(() => gpus.value.reduce((s, g) => s + (g.memory_total_mib || 0), 0))
const usedMem = computed(() => gpus.value.reduce((s, g) => s + (g.memory_used_mib || 0), 0))
const maxTemp = computed(() => {
  const temps = gpus.value.map((g) => g.temperature_c).filter((t): t is number => t != null)
  return temps.length ? Math.max(...temps) : null
})
const totalDraw = computed(() => gpus.value.reduce((s, g) => s + (g.power_draw_w || 0), 0))

function fmtMiB(mib: number | null | undefined): string {
  if (mib == null) return '-'
  return (mib / 1024).toFixed(1) + ' GB'
}

let timer: ReturnType<typeof setInterval> | null = null

async function refresh(showError = false) {
  try {
    const data = await getServerGpus()
    agentOnline.value = data.agent_online
    gpus.value = data.gpus
    for (const gpu of data.gpus) {
      // 正在编辑的卡片不覆盖输入值,防止 UI 抢状态
      if (!(gpu.index in cardWatts) || editingIndex.value !== gpu.index) {
        cardWatts[gpu.index] = gpu.power_limit_w ?? null
      }
    }
  } catch (e) {
    agentOnline.value = false
    agentMessage.value = e instanceof Error ? e.message : String(e)
    if (showError) ElMessage.error(agentMessage.value)
  }
}

async function loadSettings() {
  try {
    const s = await getGpuPowerSettings()
    autoApply.value = s.enabled
    defaultWatts.value = s.default_power_limit
    if (s.default_power_limit != null) {
      bulkWatts.value = s.default_power_limit
    }
  } catch {
    /* 设置读取失败不阻塞页面 */
  }
}

async function applyOne(index: number) {
  const watts = cardWatts[index]
  if (watts == null) {
    ElMessage.warning('请输入功耗值')
    return
  }
  try {
    await ElMessageBox.confirm(`将 GPU${index} Power Limit 设置为 ${watts}W?`, '修改 GPU 功耗', {
      confirmButtonText: '确认修改',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    const r = await setGpuPowerLimit(index, watts)
    ElMessage.success(`GPU${index} 已设置,实测值 ${r.after_watts}W(修改前 ${r.before_watts}W)`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '设置失败')
  } finally {
    editingIndex.value = null
    refresh()
  }
}

async function applyAll() {
  const watts = bulkWatts.value
  try {
    await ElMessageBox.confirm(`将 GPU0-${Math.max(0, gpus.value.length - 1)} Power Limit 设置为 ${watts}W?`, '全部修改 GPU 功耗', {
      confirmButtonText: '确认修改',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    const r = await setAllGpuPowerLimit(watts)
    if (r.all_ok) {
      ElMessage.success(`全部 ${r.results.length} 张 GPU 已设置为 ${watts}W`)
    } else {
      const failed = r.results.filter((x) => !x.ok)
      ElMessage.error(`${failed.length} 张 GPU 设置失败:` + failed.map((f) => `GPU${f.index} ${f.error}`).join(';'))
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '设置失败')
  } finally {
    refresh()
  }
}

async function saveDefault() {
  const watts = defaultWatts.value
  try {
    await ElMessageBox.confirm(
      `保存默认功耗 ${watts}W 并立即应用到全部 GPU?`,
      '默认功耗设置',
      { confirmButtonText: '确认', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const r = await putGpuPowerSettings({ enabled: autoApply.value, default_power_limit: watts, apply_now: true })
    if (r.agent_synced === false) {
      ElMessage.warning(`本地已保存,但 Agent 同步失败:${r.agent_message}`)
    } else {
      ElMessage.success(`默认功耗已保存${autoApply.value ? '(开机自动应用已开启)' : ''}`)
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    refresh()
    loadSettings()
  }
}

async function toggleAutoApply() {
  try {
    const r = await putGpuPowerSettings({ enabled: autoApply.value, default_power_limit: defaultWatts.value })
    if (r.agent_synced === false) {
      ElMessage.warning(`本地已保存,但 Agent 同步失败:${r.agent_message}`)
    } else {
      ElMessage.success(autoApply.value ? '开机自动应用已开启' : '开机自动应用已关闭')
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
    autoApply.value = !autoApply.value
  }
}

function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function startTimer() {
  stopTimer()
  // 页面可见 4s 刷新,隐藏时降频到 15s
  const interval = document.visibilityState === 'visible' ? 4000 : 15000
  timer = setInterval(() => {
    if (document.visibilityState === 'visible') refresh()
  }, interval)
}

function onVisibility() {
  startTimer()
}

onMounted(() => {
  refresh()
  loadSettings()
  document.addEventListener('visibilitychange', onVisibility)
  startTimer()
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>

<style scoped>
.block {
  margin-bottom: 16px;
}
.block-title {
  font-weight: 600;
}
.card-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
}
.summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.s-name {
  color: #909399;
  font-size: 12px;
}
.s-val {
  font-size: 18px;
  font-weight: 600;
}
.gpu-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 16px;
}
.gpu-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 16px;
  margin-bottom: 10px;
}
.gpu-fields .f {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.gpu-fields .f span {
  color: #909399;
}
.proc-title {
  font-size: 12px;
  color: #606266;
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
}
.proc-list {
  max-height: 120px;
  overflow: auto;
}
.proc-item {
  font-size: 12px;
  color: #606266;
  padding: 2px 0;
  font-family: Consolas, monospace;
}
.proc-empty {
  font-size: 12px;
  color: #c0c4cc;
}
.inline-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}
.hint {
  font-size: 12px;
  color: #909399;
}
.power-form {
  max-width: 640px;
}
</style>
