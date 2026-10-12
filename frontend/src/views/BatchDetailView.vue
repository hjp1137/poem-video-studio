<template>
  <div v-if="batch">
    <EnvBanner />
    <el-card shadow="never" class="block">
      <div class="head-row">
        <div>
          <span class="poem-title">《{{ batch.title }}》</span>
          <span class="poem-meta">{{ batch.dynasty }} · {{ batch.author }}</span>
          <el-tag :type="statusType(batch.status)" size="small" style="margin-left: 12px">{{ statusText(batch.status) }}</el-tag>
        </div>
        <div class="head-actions">
          <el-button data-testid="refresh-btn" @click="loadAll">刷新</el-button>
          <el-button
            v-if="canSubmit"
            data-testid="submit-all-btn"
            type="primary"
            :loading="submitting"
            @click="confirmSubmit"
          >
            全部加入生成队列
          </el-button>
        </div>
      </div>
      <div class="progress-row" data-testid="progress-row">
        总进度:{{ completedCount }} / {{ tasks.length }} 已完成
        <el-tag v-if="comfyuiOk === true" type="success" size="small">ComfyUI 已连接</el-tag>
        <el-tag v-else-if="comfyuiOk === false" type="danger" size="small">ComfyUI 不可达(任务提交将失败,请先启动 ComfyUI)</el-tag>
        <el-tag v-else size="small">ComfyUI 状态检测中…</el-tag>
        <el-tooltip v-if="defaultTemplate" content="在「模板管理」页可更换默认模板" placement="top">
          <el-tag size="small" type="info" data-testid="default-template-tag">生成模板:{{ defaultTemplate }}</el-tag>
        </el-tooltip>
        <el-tag v-else size="small" type="warning" data-testid="default-template-tag">
          未设置默认模板(请到「模板管理」页导入并设为默认)
        </el-tag>
      </div>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-header-row">
          <span class="block-title">场景任务</span>
          <el-button
            type="success"
            plain
            size="small"
            data-testid="download-selected-btn"
            :disabled="!selectedTasks.length"
            @click="downloadSelected"
          >
            下载选中 ({{ selectedTasks.length }})
          </el-button>
        </div>
      </template>
      <el-table
        ref="taskTableRef"
        :data="tasks"
        v-loading="loading"
        data-testid="task-table"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="42" :selectable="(row: TaskOut) => row.outputs.length > 0" />
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="params-panel" :data-testid="`params-panel-${row.scene_key}`">
              <div class="params-title">视频生成参数(修改后「保存并重新生成」即可二次创作)</div>
              <div class="params-grid">
                <div class="param-item">
                  <span class="param-label">width</span>
                  <el-input-number v-model="paramOf(row).width" :min="64" :max="8192" :step="1" size="small" data-testid="param-width" />
                </div>
                <div class="param-item">
                  <span class="param-label">height</span>
                  <el-input-number v-model="paramOf(row).height" :min="64" :max="8192" :step="1" size="small" />
                </div>
                <div class="param-item">
                  <span class="param-label">fps</span>
                  <el-input-number v-model="paramOf(row).fps" :min="1" :max="240" :step="1" size="small" />
                </div>
                <div class="param-item">
                  <span class="param-label">num_frames</span>
                  <el-input-number v-model="paramOf(row).num_frames" :min="1" :max="4096" :step="1" size="small" />
                </div>
              </div>
              <div class="param-text">
                <span class="param-label">prompt</span>
                <el-input v-model="paramOf(row).prompt" type="textarea" :rows="3" data-testid="param-prompt" />
              </div>
              <div class="param-text">
                <span class="param-label">negative_prompt</span>
                <el-input v-model="paramOf(row).negative_prompt" type="textarea" :rows="2" />
              </div>
              <div class="param-text">
                <span class="param-label">speech</span>
                <el-input v-model="paramOf(row).speech" type="textarea" :rows="2" data-testid="param-speech" />
              </div>
              <div class="param-actions">
                <el-button size="small" type="primary" plain :loading="savingParamsId === row.id" data-testid="save-params-btn" @click="saveParams(row, false)">保存参数</el-button>
                <el-button size="small" type="warning" plain :disabled="!canRetry(row)" data-testid="save-regen-btn" @click="saveParams(row, true)">保存并重新生成</el-button>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="场景" width="100">
          <template #default="{ row }">
            <el-tag :type="row.scene_key === 'cover' ? 'warning' : 'primary'" size="small">
              {{ row.scene_key === 'cover' ? '封面' : row.scene_key }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="首帧" width="90">
          <template #default="{ row }">
            <img :src="row.image_url" class="task-thumb" :alt="row.scene_key" />
          </template>
        </el-table-column>
        <el-table-column prop="speech" label="语音文本" min-width="170" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="taskStatusType(row.status)" size="small">{{ taskStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="prompt_id" width="130">
          <template #default="{ row }">
            <span class="mono">{{ row.comfy_prompt_id || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="开始 / 完成" width="170">
          <template #default="{ row }">{{ formatTime(row.started_at) }}<br />{{ formatTime(row.finished_at) }}</template>
        </el-table-column>
        <el-table-column label="错误原因" min-width="150">
          <template #default="{ row }">
            <span v-if="row.error_message" class="error-text" :title="row.error_message">{{ row.error_message }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.video_url" size="small" type="primary" plain @click="preview(row)">预览</el-button>
            <a v-if="row.download_url" :href="row.download_url" download>
              <el-button size="small" type="success" plain>下载</el-button>
            </a>
            <span v-if="row.outputs.length > 1" class="versions" data-testid="version-links">
              <a v-for="o in row.outputs" :key="o.output_id" :href="o.download_url" download class="ver-link" :title="formatTime(o.created_at)">v{{ o.version }}</a>
            </span>
            <el-button
              v-if="canRetry(row)"
              size="small"
              type="warning"
              plain
              :loading="retryingId === row.id"
              data-testid="retry-btn"
              @click="doRetry(row)"
            >
              重试
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="previewVisible" :title="`视频预览:${previewTask?.speech ?? ''}`" width="480px">
      <video v-if="previewTask?.video_url" :src="previewTask.video_url" controls autoplay class="preview-video" />
    </el-dialog>
  </div>
  <el-empty v-else-if="!loading" description="批次不存在" />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatTime, getBatch, getBatchTasks, getServerSummary, listWorkflowTemplates, retryTask, submitBatch, updateTaskParams } from '@/api'
import type { BatchSummary, TaskOut, WsBatchSnapshot } from '@/types'
import EnvBanner from '@/components/EnvBanner.vue'

const route = useRoute()
const batchId = route.params.id as string

const batch = ref<BatchSummary | null>(null)
const tasks = ref<TaskOut[]>([])
const loading = ref(false)
const submitting = ref(false)
const defaultTemplate = ref('')
const retryingId = ref('')
const previewVisible = ref(false)
const previewTask = ref<TaskOut | null>(null)
const comfyuiOk = ref<boolean | null>(null)
const taskTableRef = ref()
const selectedTasks = ref<TaskOut[]>([])
const savingParamsId = ref('')
const paramForms = reactive<Record<string, { width: number; height: number; fps: number; num_frames: number; prompt: string; negative_prompt: string; speech: string }>>({})

let ws: WebSocket | null = null
let pollTimer: number | null = null

const completedCount = computed(() => tasks.value.filter((t) => t.status === 'completed').length)
const canSubmit = computed(() =>
  ['pending', 'failed', 'recover_pending'].some((s) => tasks.value.some((t) => t.status === s)),
)

const batchStatusMap: Record<string, { text: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  draft: { text: '草稿', type: 'info' },
  parsed: { text: '已解析', type: 'info' },
  queued: { text: '已入队', type: 'warning' },
  running: { text: '生成中', type: 'primary' },
  completed: { text: '已完成', type: 'success' },
  partial_failed: { text: '部分失败', type: 'danger' },
  failed: { text: '失败', type: 'danger' },
}
const taskStatusMap: Record<string, { text: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  pending: { text: '待提交', type: 'info' },
  submitting: { text: '提交中', type: 'warning' },
  queued: { text: '排队中', type: 'warning' },
  running: { text: '生成中', type: 'primary' },
  completed: { text: '完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  cancelled: { text: '已取消', type: 'info' },
  recover_pending: { text: '待恢复确认', type: 'warning' },
}

function statusText(s: string) {
  return batchStatusMap[s]?.text ?? s
}
function statusType(s: string) {
  return batchStatusMap[s]?.type ?? 'info'
}
function taskStatusText(s: string) {
  return taskStatusMap[s]?.text ?? s
}
function taskStatusType(s: string) {
  return taskStatusMap[s]?.type ?? 'info'
}
function onSelectionChange(rows: TaskOut[]) {
  selectedTasks.value = rows
}

function downloadSelected() {
  if (!selectedTasks.value.length) return
  const ids = selectedTasks.value.map((t) => t.id).join(',')
  window.open(`/api/batches/${batchId}/download?task_ids=${encodeURIComponent(ids)}`)
}

function paramOf(row: TaskOut) {
  if (!paramForms[row.id]) {
    paramForms[row.id] = {
      width: row.width,
      height: row.height,
      fps: row.fps,
      num_frames: row.num_frames,
      prompt: row.prompt,
      negative_prompt: row.negative_prompt,
      speech: row.speech,
    }
  }
  return paramForms[row.id]
}

async function saveParams(row: TaskOut, regen: boolean) {
  const form = paramForms[row.id]
  if (!form) return
  savingParamsId.value = row.id
  try {
    const updated = await updateTaskParams(row.id, { ...form })
    applyTask(updated)
    if (regen) {
      const result = await retryTask(row.id)
      applyTask(result)
      ElMessage.success(`场景 ${row.scene_key} 已按新参数重新生成`)
    } else {
      ElMessage.success(`场景 ${row.scene_key} 参数已保存`)
    }
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '参数保存失败')
  } finally {
    savingParamsId.value = ''
  }
}

function applyTask(updated: TaskOut) {
  const idx = tasks.value.findIndex((t) => t.id === updated.id)
  if (idx >= 0) tasks.value[idx] = updated
  delete paramForms[updated.id] // 下次展开用最新值
}

function canRetry(row: TaskOut) {
  return ['failed', 'completed', 'pending', 'cancelled', 'recover_pending'].includes(row.status)
}

async function loadTemplate() {
  try {
    defaultTemplate.value = (await listWorkflowTemplates()).default
  } catch {
    defaultTemplate.value = ''
  }
}

async function loadAll() {
  loadTemplate()
  loading.value = true
  try {
    batch.value = await getBatch(batchId)
    tasks.value = await getBatchTasks(batchId)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载批次失败')
  } finally {
    loading.value = false
  }
}

async function checkComfyui() {
  try {
    const resp = await fetch('/api/system/comfyui')
    const data = (await resp.json()) as { http: [boolean, string]; queue: [boolean, string] }
    comfyuiOk.value = data.http[0]
  } catch {
    comfyuiOk.value = false
  }
}

async function confirmSubmit() {
  // 任务05 §16:加入生成队列前必须检查 ComfyUI;未就绪提示用户先准备环境(不自动改服务器状态)
  try {
    const summary = await getServerSummary()
    const comfy = summary.environment?.comfyui
    if (!(comfy?.process_state === 'running' && comfy?.health_state === 'healthy')) {
      ElMessage.warning('视频生成环境未就绪(ComfyUI 不可用):请先到「服务器 → 总览」准备环境')
    }
  } catch {
    /* 环境检查失败不阻断提交,提交本身会给出具体错误 */
  }
  try {
    await ElMessageBox.confirm(
      `将把 ${tasks.value.filter((t) => canRetry(t)).length} 个场景按顺序提交到 ComfyUI 生成队列,是否继续?`,
      '全部加入生成队列',
      { confirmButtonText: '提交', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  submitting.value = true
  try {
    const result = await submitBatch(batchId)
    if (result.failed > 0) {
      ElMessage.warning(result.message)
    } else {
      ElMessage.success(result.message)
    }
    await loadAll()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '提交失败')
  } finally {
    submitting.value = false
  }
}

async function doRetry(row: TaskOut) {
  retryingId.value = row.id
  try {
    const updated = await retryTask(row.id)
    const idx = tasks.value.findIndex((t) => t.id === row.id)
    if (idx >= 0) tasks.value[idx] = updated
    if (updated.status === 'failed') {
      ElMessage.error(`重试失败:${updated.error_message.slice(0, 120)}`)
    } else {
      ElMessage.success('已重新提交,生成新的 ComfyUI 任务')
    }
    batch.value = await getBatch(batchId)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '重试失败')
  } finally {
    retryingId.value = ''
  }
}

function preview(row: TaskOut) {
  previewTask.value = row
  previewVisible.value = true
}

function applySnapshot(snap: WsBatchSnapshot) {
  if (snap.batch_id !== batchId) return
  if (batch.value) batch.value.status = snap.batch_status
  for (const wsTask of snap.tasks) {
    const idx = tasks.value.findIndex((t) => t.id === wsTask.id)
    if (idx >= 0) {
      tasks.value[idx] = { ...tasks.value[idx], ...wsTask, video_url: wsTask.output_path ? `/api/tasks/${wsTask.id}/video` : null, download_url: wsTask.output_path ? `/api/tasks/${wsTask.id}/download` : null }
    }
  }
}

function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  try {
    ws = new WebSocket(`${proto}://${location.host}/api/ws/batches/${batchId}`)
    ws.onmessage = (ev) => {
      try {
        applySnapshot(JSON.parse(ev.data) as WsBatchSnapshot)
      } catch {
        /* 忽略无法解析的帧 */
      }
    }
    ws.onclose = startPolling
    ws.onerror = () => ws?.close()
  } catch {
    startPolling()
  }
}

function startPolling() {
  if (pollTimer !== null) return
  pollTimer = window.setInterval(async () => {
    try {
      const resp = await fetch(`/api/batches/${batchId}/status`)
      if (!resp.ok) return
      const data = await resp.json()
      batch.value = batch.value ?? (await getBatch(batchId))
      if (batch.value) batch.value.status = data.batch_status
      for (const t of data.tasks as TaskOut[]) {
        const idx = tasks.value.findIndex((x) => x.id === t.id)
        if (idx >= 0) tasks.value[idx] = t
      }
    } catch {
      /* 网络异常时保持现状,下轮重试 */
    }
  }, 3000)
}

onMounted(async () => {
  await loadAll()
  checkComfyui()
  connectWs()
})

onBeforeUnmount(() => {
  ws?.close()
  if (pollTimer !== null) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.block {
  margin-bottom: 16px;
}
.block-title {
  font-weight: 600;
}
.head-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.poem-title {
  font-size: 20px;
  font-weight: 600;
  margin-right: 8px;
}
.poem-meta {
  color: #909399;
  font-size: 14px;
}
.progress-row {
  margin-top: 12px;
  display: flex;
  gap: 12px;
  align-items: center;
  color: #606266;
  font-size: 14px;
}
.task-thumb {
  width: 64px;
  height: 48px;
  object-fit: cover;
  border-radius: 4px;
}
.mono {
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  color: #909399;
}
.error-text {
  color: #f56c6c;
  font-size: 12px;
}
.card-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.versions {
  margin-left: 6px;
}
.ver-link {
  margin-right: 6px;
  color: #409eff;
  text-decoration: none;
  font-size: 12px;
}
.params-panel {
  padding: 8px 12px 12px;
  background: #fafafa;
}
.params-title {
  font-size: 13px;
  color: #606266;
  margin-bottom: 10px;
}
.params-grid {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.param-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.param-label {
  font-family: Consolas, monospace;
  font-size: 12px;
  color: #909399;
  min-width: 110px;
}
.param-text {
  display: flex;
  gap: 10px;
  margin-bottom: 8px;
  align-items: flex-start;
}
.param-actions {
  display: flex;
  gap: 8px;
}
.preview-video {
  width: 100%;
  max-height: 70vh;
  background: #000;
}
</style>
