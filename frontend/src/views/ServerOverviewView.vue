<template>
  <div>
    <el-card shadow="never" class="block" data-testid="env-card">
      <template #header>
        <div class="card-header-row">
          <span class="block-title">{{ profileName }}</span>
          <el-button data-testid="recheck-btn" @click="refreshAll(true)">重新检查</el-button>
        </div>
      </template>

      <div v-if="loading">正在获取环境状态…</div>
      <template v-else>
        <div class="env-head">
          <el-tag :type="ready ? 'success' : 'danger'" size="large" data-testid="env-ready-tag" effect="dark">
            {{ ready ? 'READY' : 'NOT READY' }}
          </el-tag>
          <span v-if="!ready && !agentOk" class="env-reason">Agent 离线,无法管理宿主机服务</span>
        </div>
        <div class="env-grid" v-if="agentOk">
          <div class="env-item">
            <span class="e-name">GPU</span>
            <el-tag :type="gpuCount > 0 ? 'success' : 'danger'" size="small" data-testid="env-gpu-tag">
              {{ gpuCount > 0 ? `${gpuCount}/${gpuCount} OK` : '0 卡' }}
            </el-tag>
          </div>
          <div class="env-item">
            <span class="e-name">Power Limit</span>
            <span class="e-val" data-testid="env-power">{{ powerLimitText }}</span>
          </div>
          <div class="env-item">
            <span class="e-name">MiniMax H3</span>
            <el-tag :type="h3TagType" size="small" data-testid="env-h3-tag">{{ h3Text }}</el-tag>
          </div>
          <div class="env-item">
            <span class="e-name">ComfyUI</span>
            <el-tag :type="comfyTagType" size="small" data-testid="env-comfy-tag">{{ comfyText }}</el-tag>
          </div>
        </div>
      </template>
    </el-card>

    <el-card shadow="never" class="block" data-testid="manual-prep-card">
      <template #header>
        <div class="card-header-row">
          <span class="block-title">视频环境准备 · 手动逐项</span>
          <span class="hint">按顺序逐项确认执行;每项操作前均有确认提示</span>
        </div>
      </template>

      <div v-if="profileError" class="profile-error">
        Profile 配置不可用:{{ profileError }}(检查 server/profiles.yaml)
      </div>
      <template v-else-if="profile">
        <!-- ① GPU 功耗 -->
        <div class="prep-item" data-testid="prep-item-power">
          <span class="p-no">①</span>
          <span class="p-title">设置 GPU 功耗</span>
          <span class="p-state" data-testid="prep-power-state">
            <template v-if="powerMatchesTarget">
              <el-tag type="success" size="small" data-testid="prep-power-done">✓ 已是目标值 {{ profile.gpu_power.watts }}W</el-tag>
            </template>
            <template v-else-if="profile.gpu_power.enabled && profile.gpu_power.watts != null">
              当前 {{ powerLimitText }} / 目标 {{ profile.gpu_power.watts }}W
            </template>
            <template v-else>Profile 未启用功耗设置</template>
          </span>
          <el-button
            v-if="powerActionable"
            size="small"
            type="primary"
            data-testid="prep-power-btn"
            :loading="busyItem === 'power'"
            @click="applyPower"
          >设置为 {{ profile.gpu_power.watts }}W</el-button>
        </div>

        <!-- ② 停止冲突服务(自动检测占用 GPU 的负载 + Profile 登记服务) -->
        <div class="prep-subhead" data-testid="prep-stop-head">
          ② 停止冲突服务
          <span class="hint">自动检测当前占用 GPU 显存的服务,未占用的不列出;新增服务同样会被检测到</span>
        </div>
        <template v-if="conflictRows.length">
          <div
            v-for="(row, idx) in conflictRows"
            :key="row.key"
            class="prep-item"
            :data-testid="`prep-item-conflict-${row.key}`"
          >
            <span class="p-no">{{ circledNo(1 + idx) }}</span>
            <span class="p-title">{{ row.title }}</span>
            <span class="p-state" data-testid="prep-conflict-state">
              <el-tag size="small" type="info">GPU{{ row.gpuText }}</el-tag>
              <el-tag size="small" type="warning">{{ row.memText }} MiB</el-tag>
              <el-tag v-if="!row.stoppable" size="small" type="info">非受管 · 只读</el-tag>
            </span>
            <el-button
              v-if="row.stoppable"
              size="small"
              type="danger"
              :data-testid="`prep-conflict-stop-${row.key}`"
              :loading="busyItem === row.key"
              @click="stopConflict(row)"
            >停止</el-button>
          </div>
        </template>
        <div v-else class="prep-item">
          <span class="p-no">✓</span>
          <span class="p-state" data-testid="prep-conflict-none">无占用 GPU 的冲突服务</span>
        </div>

        <!-- ③ 启动服务(编号顺延冲突服务数量) -->
        <div
          v-for="(name, i) in profile.start_services"
          :key="`start-${name}`"
          class="prep-item"
          :data-testid="`prep-item-start-${name}`"
        >
          <span class="p-no">{{ circledNo(1 + conflictRows.length + i) }}</span>
          <span class="p-title">启动:{{ serviceDisplay(name) }}</span>
          <span class="p-state"><service-inline-status :service="serviceByName(name)" /></span>
          <template v-if="!serviceReady(name)">
            <el-button
              v-if="serviceByName(name)?.process_state === 'running'"
              size="small"
              type="warning"
              :data-testid="`prep-restart-btn-${name}`"
              :loading="busyItem === name"
              @click="startService(name, 'restart')"
            >重启(运行中但未就绪)</el-button>
            <el-button
              v-else
              size="small"
              type="primary"
              :data-testid="`prep-start-btn-${name}`"
              :loading="busyItem === name"
              @click="startService(name, 'start')"
            >启动</el-button>
          </template>
          <el-tag v-else type="success" size="small" :data-testid="`prep-start-done-${name}`">✓ Running / Healthy</el-tag>
        </div>

        <div class="prep-note">
          说明:未登记的 GPU 进程只在「GPU」页只读展示;启动后健康状态转为 Healthy 需要模型加载时间,可点「重新检查」刷新。
        </div>
      </template>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header><span class="block-title">服务速览</span></template>
      <div v-if="services.length" class="quick-grid">
        <div v-for="s in services" :key="s.name" class="quick-item" :data-testid="`quick-${s.name}`">
          <span class="q-name">{{ s.display_name }}</span>
          <el-tag size="small" :type="s.process_state === 'running' ? 'success' : 'info'">
            {{ s.process_state === 'running' ? 'Running' : s.process_state }}
          </el-tag>
          <el-tag size="small" :type="s.health_state === 'healthy' ? 'success' : s.health_state === 'unhealthy' ? 'danger' : 'info'">
            {{ s.health_state }}
          </el-tag>
        </div>
      </div>
      <div v-else class="quick-empty">{{ agentOk ? '注册表为空' : 'Agent 离线' }}</div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onBeforeUnmount, onMounted, ref, type PropType } from 'vue'
import { ElMessage, ElMessageBox, ElTag } from 'element-plus'
import {
  ApiError,
  getEnvironmentProfile,
  getGpuWorkloads,
  getServerSummary,
  serviceAction,
  setAllGpuPowerLimit,
  stopGpuWorkload,
} from '@/api'
import type { EnvironmentProfile, GpuWorkload, ServerSummary, ServiceBrief, ServiceStatus } from '@/types'

/** 手动逐项操作行内的服务状态徽标:Running/Stopped + health 两层。 */
const ServiceInlineStatus = defineComponent({
  name: 'ServiceInlineStatus',
  props: { service: { type: Object as PropType<ServiceStatus | null>, default: null } },
  setup(props) {
    return () => {
      const s = props.service
      if (!s) return h('span', { class: 'p-dim' }, '未登记')
      const running = s.process_state === 'running'
      const healthy = s.health_state === 'healthy'
      return h('span', { class: 'p-svc-state' }, [
        h(ElTag, { size: 'small', type: running ? 'success' : 'info' }, () => (running ? 'Running' : s.process_state)),
        ' ',
        h(ElTag, { size: 'small', type: healthy ? 'success' : s.health_state === 'unhealthy' ? 'danger' : 'info' }, () => s.health_state),
      ])
    }
  },
})

const summary = ref<ServerSummary | null>(null)
const profile = ref<EnvironmentProfile | null>(null)
const profileError = ref('')
const workloads = ref<GpuWorkload[]>([])
const loading = ref(true)
const busyItem = ref('')

const CIRCLED = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']

function circledNo(oneBased: number): string {
  return CIRCLED[oneBased - 1] ?? `${oneBased}.`
}

const agentOk = computed(() => summary.value?.agent?.ok ?? false)
const ready = computed(() => summary.value?.environment?.ready ?? false)
const gpuCount = computed(() => summary.value?.environment?.gpu_count ?? 0)
const profileName = computed(() => profile.value?.display_name || 'MiniMax H3 视频环境')
const services = computed(() => summary.value?.services ?? [])

const powerLimitText = computed(() => {
  const limits = summary.value?.environment?.power_limits ?? []
  if (!limits.length) return '-'
  const uniq = [...new Set(limits.map((w) => (w == null ? '-' : Math.round(w))))].map((w) => `${w}W`)
  return uniq.join('/')
})

const powerMatchesTarget = computed(() => {
  const target = profile.value?.gpu_power.watts
  if (!target) return false
  const limits = summary.value?.environment?.power_limits ?? []
  return limits.length > 0 && limits.every((w) => w != null && Math.round(w) === target)
})
const powerActionable = computed(
  () => agentOk.value && !powerMatchesTarget.value && !!profile.value?.gpu_power.enabled && profile.value.gpu_power.watts != null,
)

const h3Text = computed(() => stateText(summary.value?.environment?.minimax_h3))
const comfyText = computed(() => stateText(summary.value?.environment?.comfyui))
const h3TagType = computed(() => stateTagType(summary.value?.environment?.minimax_h3))
const comfyTagType = computed(() => stateTagType(summary.value?.environment?.comfyui))

function stateText(brief: ServiceBrief | undefined) {
  if (!brief) return '-'
  if (brief.health_state === 'healthy') return 'Healthy'
  if (brief.process_state === 'running') return 'Running / Starting'
  return brief.process_state === 'unknown' ? '-' : brief.process_state
}
function stateTagType(brief: ServiceBrief | undefined): 'success' | 'warning' | 'danger' | 'info' {
  if (!brief) return 'info'
  if (brief.health_state === 'healthy') return 'success'
  if (brief.process_state === 'running') return 'warning'
  return brief.process_state === 'failed' ? 'danger' : 'info'
}

function serviceByName(name: string): ServiceStatus | null {
  return services.value.find((s) => s.name === name) ?? null
}
function serviceDisplay(name: string): string {
  return serviceByName(name)?.display_name ?? name
}
function serviceReady(name: string): boolean {
  const s = serviceByName(name)
  return !!s && s.process_state === 'running' && s.health_state === 'healthy'
}

interface ConflictRow {
  key: string
  title: string
  gpuText: string
  memText: string
  stoppable: boolean
  kind: 'docker' | 'service'
  name: string
}

/** 冲突服务 = 自动检测的 GPU 占用负载 + Profile.stop_services 中仍在运行的注册服务(去重)。 */
const conflictRows = computed<ConflictRow[]>(() => {
  const rows: ConflictRow[] = []
  for (const wl of workloads.value) {
    rows.push({
      key: `wl-${wl.name}`,
      title: wl.kind === 'docker' ? `容器:${wl.name}` : wl.kind === 'systemd' ? `服务:${wl.name}` : `进程:${wl.command || wl.name}`,
      gpuText: wl.gpu_indices.length ? [...wl.gpu_indices].sort((a, b) => a - b).join(',') : '-',
      memText: String(wl.used_memory_mib),
      stoppable: wl.stoppable,
      kind: 'docker',
      name: wl.name,
    })
  }
  if (profile.value) {
    for (const name of profile.value.stop_services) {
      const svc = serviceByName(name)
      if (svc && svc.process_state !== 'stopped' && !rows.some((r) => r.name === name)) {
        rows.push({
          key: `svc-${name}`,
          title: `服务:${svc.display_name}(Profile 登记)`,
          gpuText: '-',
          memText: String(svc.pid ?? ''),
          stoppable: true,
          kind: 'service',
          name,
        })
      }
    }
  }
  return rows
})

async function refreshAll(showError = false) {
  loading.value = !summary.value
  try {
    const [s, w] = await Promise.all([
      getServerSummary(),
      getGpuWorkloads().catch(() => null),
    ])
    summary.value = s
    if (w) workloads.value = w.workloads
  } catch (e) {
    if (showError) ElMessage.error(e instanceof Error ? e.message : '获取状态失败')
  } finally {
    loading.value = false
  }
}

async function loadProfile() {
  try {
    profile.value = await getEnvironmentProfile()
    profileError.value = ''
  } catch (e) {
    profileError.value = e instanceof Error ? e.message : String(e)
  }
}

async function applyPower() {
  const watts = profile.value?.gpu_power.watts
  if (watts == null) return
  try {
    await ElMessageBox.confirm(
      `将 GPU0-${Math.max(0, gpuCount.value - 1)} Power Limit 设置为 ${watts}W?`,
      '设置 GPU 功耗',
      { confirmButtonText: '确认修改', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  busyItem.value = 'power'
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
    busyItem.value = ''
    refreshAll()
  }
}

async function stopService(name: string) {
  try {
    await ElMessageBox.confirm(
      `确认停止 ${serviceDisplay(name)}?可能影响依赖该服务的任务。`,
      '停止冲突服务',
      { confirmButtonText: '确认停止', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  busyItem.value = name
  try {
    await serviceAction(name, 'stop', false)
    ElMessage.success(`${serviceDisplay(name)} 已停止`)
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      const detail = e.payload as { message?: string } | null
      try {
        await ElMessageBox.confirm(
          `${detail?.message || e.message}\n\n仍然停止?`,
          '高风险操作二次确认',
          { confirmButtonText: '仍然停止', cancelButtonText: '取消', type: 'warning' },
        )
      } catch {
        return
      }
      try {
        await serviceAction(name, 'stop', true)
        ElMessage.success(`${serviceDisplay(name)} 已强制停止`)
      } catch (e2) {
        ElMessage.error(e2 instanceof Error ? e2.message : '操作失败')
      }
    } else {
      ElMessage.error(e instanceof Error ? e.message : '操作失败')
    }
  } finally {
    busyItem.value = ''
    refreshAll()
  }
}

async function stopConflict(row: ConflictRow) {
  if (row.kind !== 'docker') {
    await stopService(row.name)
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认停止容器 ${row.name}?将释放约 ${row.memText} MiB GPU 显存,容器内的服务会中断。`,
      '停止占用 GPU 的容器',
      { confirmButtonText: '确认停止', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  busyItem.value = row.key
  try {
    const r = await stopGpuWorkload(row.name)
    ElMessage.success(`${r.stopped} 已停止,释放约 ${r.freed_memory_mib} MiB 显存`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '停止失败')
  } finally {
    busyItem.value = ''
    refreshAll()
  }
}

async function startService(name: string, verb: 'start' | 'restart') {
  if (verb === 'restart') {
    try {
      await ElMessageBox.confirm(
        `${serviceDisplay(name)} 正在运行但未就绪,确认重启?`,
        '重启服务',
        { confirmButtonText: '确认重启', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }
  }
  busyItem.value = name
  try {
    await serviceAction(name, verb, false)
    ElMessage.success(`${serviceDisplay(name)} 已${verb === 'restart' ? '重启,等待就绪' : '启动,等待就绪'}`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    busyItem.value = ''
    refreshAll()
  }
}

let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  refreshAll()
  loadProfile()
  timer = setInterval(() => {
    if (document.visibilityState === 'visible') refreshAll()
  }, 6000)
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
.hint {
  font-size: 12px;
  color: #909399;
}
.env-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
}
.env-reason {
  color: #f56c6c;
  font-size: 13px;
}
.env-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.env-item {
  display: flex;
  align-items: center;
  gap: 10px;
}
.e-name {
  color: #909399;
  font-size: 13px;
  min-width: 90px;
}
.e-val {
  font-weight: 600;
}
.profile-error {
  color: #f56c6c;
  font-size: 13px;
}
.prep-subhead {
  padding: 6px 0 2px;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.prep-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px dashed #ebeef5;
  flex-wrap: wrap;
}
.prep-item:last-of-type {
  border-bottom: none;
}
.p-no {
  width: 22px;
  color: #909399;
  font-weight: 600;
}
.p-title {
  min-width: 220px;
  font-size: 14px;
  color: #303133;
}
.p-state {
  flex: 1;
  font-size: 13px;
  color: #606266;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.p-dim {
  color: #c0c4cc;
}
:deep(.p-svc-state) {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}
.prep-note {
  margin-top: 10px;
  font-size: 12px;
  color: #909399;
}
.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
}
.quick-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.q-name {
  flex: 1;
  font-size: 13px;
}
.quick-empty {
  color: #909399;
  font-size: 13px;
}
</style>
