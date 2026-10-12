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
      description="无法连接宿主机 poem-video-agent,服务状态不可用"
    />

    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-header-row">
          <span class="block-title">已登记模型服务</span>
          <el-button data-testid="services-refresh-btn" size="small" @click="refresh(true)">刷新</el-button>
        </div>
      </template>
      <div v-if="services.length" class="service-grid">
        <el-card
          v-for="s in services"
          :key="s.name"
          shadow="never"
          class="service-card"
          :data-testid="`service-card-${s.name}`"
        >
          <template #header>
            <div class="card-header-row">
              <span class="svc-title">{{ s.display_name }}</span>
              <el-tag :type="processTagType(s.process_state)" size="small">{{ processText(s.process_state) }}</el-tag>
            </div>
          </template>
          <div class="svc-fields">
            <div class="f"><span>健康状态</span><el-tag :type="healthTagType(s.health_state)" size="small">{{ healthText(s.health_state) }}</el-tag></div>
            <div class="f"><span>PID</span><b>{{ s.pid ?? '-' }}</b></div>
            <div class="f"><span>Uptime</span><b>{{ formatDuration(s.uptime_seconds) }}</b></div>
            <div class="f"><span>systemd unit</span><b class="mono">{{ s.unit }}</b></div>
            <div class="f" v-if="s.gpu_profile"><span>GPU Profile</span><b>{{ s.gpu_profile }}</b></div>
          </div>
          <div class="svc-desc" v-if="s.description">{{ s.description }}</div>
          <div class="svc-actions">
            <el-button size="small" type="primary" data-testid="svc-start" :disabled="busy[s.name] || s.process_state === 'running'" @click="act(s, 'start')">启动</el-button>
            <el-button size="small" type="danger" data-testid="svc-stop" :disabled="busy[s.name] || s.process_state !== 'running'" @click="act(s, 'stop')">停止</el-button>
            <el-button size="small" type="warning" data-testid="svc-restart" :disabled="busy[s.name]" @click="act(s, 'restart')">重启</el-button>
            <el-button size="small" data-testid="svc-logs" @click="openLogs(s)">日志</el-button>
            <el-button v-if="s.name === 'comfyui'" size="small" type="primary" plain @click="openComfyui">打开</el-button>
          </div>
        </el-card>
      </div>
      <el-empty v-else description="注册表为空:请在 Agent 侧 /etc/poem-video-agent/services.yaml 登记服务" />
    </el-card>

    <el-drawer v-model="logsVisible" :title="`服务日志 · ${logsService?.display_name || ''}`" size="55%" data-testid="logs-drawer">
      <div class="logs-toolbar">
        <span>最近行数:</span>
        <el-select :model-value="logsLines" style="width: 110px" data-testid="logs-lines-select" @change="reloadLogs">
          <el-option v-for="n in [100, 300, 500, 1000]" :key="n" :label="`${n} 行`" :value="n" />
        </el-select>
        <el-button size="small" @click="reloadLogs(logsLines)">刷新</el-button>
      </div>
      <pre v-if="logsData?.logs.length" class="logs-pre" data-testid="logs-content">{{ logsData.logs.join('\n') }}</pre>
      <el-empty v-else description="暂无日志" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError, formatDuration, getServiceLogs, getServerServices, serviceAction } from '@/api'
import type { ServiceLogs, ServiceStatus } from '@/types'

const services = ref<ServiceStatus[]>([])
const agentOnline = ref(true)
const busy = reactive<Record<string, boolean>>({})
const logsVisible = ref(false)
const logsService = ref<ServiceStatus | null>(null)
const logsLines = ref(100)
const logsData = ref<ServiceLogs | null>(null)

const PROCESS_TEXT: Record<string, string> = {
  running: 'Running', stopped: 'Stopped', failed: 'Failed',
  activating: 'Activating', deactivating: 'Deactivating', unknown: 'Unknown',
}
const HEALTH_TEXT: Record<string, string> = {
  healthy: 'Healthy', unhealthy: 'Unhealthy', starting: 'Starting', unknown: 'Unknown',
}

function processText(s: string) {
  return PROCESS_TEXT[s] ?? s
}
function healthText(s: string) {
  return HEALTH_TEXT[s] ?? s
}
function processTagType(s: string): 'success' | 'danger' | 'warning' | 'info' {
  return s === 'running' ? 'success' : s === 'failed' ? 'danger' : s === 'stopped' ? 'info' : 'warning'
}
function healthTagType(s: string): 'success' | 'danger' | 'warning' | 'info' {
  return s === 'healthy' ? 'success' : s === 'unhealthy' ? 'danger' : s === 'starting' ? 'warning' : 'info'
}

async function refresh(showError = false) {
  try {
    const data = await getServerServices()
    agentOnline.value = data.agent_online
    services.value = data.services
  } catch (e) {
    agentOnline.value = false
    if (showError) ElMessage.error(e instanceof Error ? e.message : '读取服务状态失败')
  }
}

/** 停止/重启确认;后端 409(有任务在跑/队列非空)时展示原因并二次确认 force。 */
async function act(s: ServiceStatus, verb: 'start' | 'stop' | 'restart') {
  if (verb !== 'start') {
    try {
      await ElMessageBox.confirm(
        `确认${verb === 'stop' ? '停止' : '重启'} ${s.display_name}?可能影响正在进行的视频生成。`,
        `${verb === 'stop' ? '停止' : '重启'}服务`,
        { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }
  }
  busy[s.name] = true
  try {
    await serviceAction(s.name, verb, false)
    ElMessage.success(`${s.display_name} 已${verb === 'stop' ? '停止' : verb === 'restart' ? '重启' : '启动'}`)
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      const detail = e.payload as { message?: string } | null
      try {
        await ElMessageBox.confirm(
          `${detail?.message || e.message}\n\n仍然${verb === 'stop' ? '停止' : '重启'}?`,
          '高风险操作二次确认',
          { confirmButtonText: '仍然' + (verb === 'stop' ? '停止' : '重启'), cancelButtonText: '取消', type: 'warning' },
        )
      } catch {
        return
      }
      try {
        await serviceAction(s.name, verb, true)
        ElMessage.success(`${s.display_name} 已强制${verb === 'stop' ? '停止' : '重启'}`)
      } catch (e2) {
        ElMessage.error(e2 instanceof Error ? e2.message : '操作失败')
      }
    } else {
      ElMessage.error(e instanceof Error ? e.message : '操作失败')
    }
  } finally {
    busy[s.name] = false
    refresh()
  }
}

async function openLogs(s: ServiceStatus) {
  logsService.value = s
  logsVisible.value = true
  await reloadLogs(logsLines.value)
}

async function reloadLogs(lines: number) {
  if (!logsService.value) return
  logsLines.value = lines
  try {
    logsData.value = await getServiceLogs(logsService.value.name, lines)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '读取日志失败')
  }
}

function openComfyui() {
  window.open('/comfyui/', '_blank')
}

let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  refresh()
  timer = setInterval(() => {
    if (document.visibilityState === 'visible') refresh()
  }, 5000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
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
.service-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}
.svc-title {
  font-weight: 600;
}
.svc-fields {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
}
.svc-fields .f {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}
.svc-fields .f span {
  color: #909399;
}
.mono {
  font-family: Consolas, monospace;
  font-size: 12px;
}
.svc-desc {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}
.svc-actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.logs-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 13px;
  color: #606266;
}
.logs-pre {
  background: #1f2d3d;
  color: #d1e3f8;
  font-size: 12px;
  line-height: 1.6;
  padding: 12px;
  border-radius: 4px;
  overflow: auto;
  max-height: calc(100vh - 200px);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
