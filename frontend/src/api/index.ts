/** 后端 REST API 封装,统一错误信息提取。 */
import type {
  BatchSummary,
  BulkPowerLimitResponse,
  EnvironmentProfile,
  GpuInfo,
  GpuPowerLimitResult,
  GpuPowerSettings,
  GpuWorkload,
  HealthResult,
  ParseResult,
  PrepareRun,
  ServerOperationItem,
  ServerSummary,
  ServiceLogs,
  ServiceStatus,
  TaskOut,
  UploadItem,
  UserWorkflowSource,
  WorkflowListResult,
  ConvertPreview,
} from '@/types'

/** 携带 HTTP 状态码与后端 detail 的请求异常(409 停止保护等流程需要)。 */
export class ApiError extends Error {
  status: number
  payload: unknown

  constructor(message: string, status: number, payload: unknown) {
    super(message)
    this.status = status
    this.payload = payload
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init)
  const contentType = resp.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    if (!resp.ok) {
      throw new ApiError(`请求失败(${resp.status})`, resp.status, null)
    }
    return undefined as T
  }
  const data = await resp.json()
  if (!resp.ok) {
    const detail = (data as { detail?: unknown }).detail
    if (detail && typeof detail === 'object' && detail !== null && 'message' in detail) {
      const d = detail as { message: string; errors?: string[] }
      throw new ApiError([d.message, ...(d.errors || [])].filter(Boolean).join(';'), resp.status, detail)
    }
    throw new ApiError(typeof detail === 'string' ? detail : `请求失败(${resp.status})`, resp.status, detail ?? data)
  }
  return data as T
}

export function parseBatch(text: string): Promise<ParseResult> {
  return request<ParseResult>('/api/batches/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
}

export async function uploadImages(files: File[]): Promise<{ group_id: string; files: UploadItem[] }> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  return request('/api/uploads', { method: 'POST', body: form })
}

export function createBatch(payload: {
  title: string
  dynasty: string
  author: string
  raw_batch_text: string
  image_bindings: Record<string, string>
}): Promise<BatchSummary> {
  return request<BatchSummary>('/api/batches', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function listBatches(): Promise<BatchSummary[]> {
  return request<BatchSummary[]>('/api/batches')
}

export function getBatch(id: string): Promise<BatchSummary> {
  return request<BatchSummary>(`/api/batches/${id}`)
}

export function getBatchTasks(id: string): Promise<TaskOut[]> {
  return request<TaskOut[]>(`/api/batches/${id}/tasks`)
}

export function submitBatch(id: string): Promise<{ submitted: number; failed: number; message: string }> {
  return request(`/api/batches/${id}/submit`, { method: 'POST' })
}

export function retryTask(id: string): Promise<TaskOut> {
  return request<TaskOut>(`/api/tasks/${id}/retry`, { method: 'POST' })
}

export function getHealth(): Promise<HealthResult> {
  return request<HealthResult>('/api/system/health')
}

// ---- 服务器控制中心 ----

export function getServerSummary(): Promise<ServerSummary> {
  return request<ServerSummary>('/api/server/summary')
}

export function getServerGpus(): Promise<{ agent_online: boolean; gpus: GpuInfo[] }> {
  return request('/api/server/gpus')
}

export function setGpuPowerLimit(index: number, watts: number): Promise<GpuPowerLimitResult> {
  return request(`/api/server/gpus/${index}/power-limit`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ watts }),
  })
}

export function setAllGpuPowerLimit(watts: number, gpuIndices?: number[]): Promise<BulkPowerLimitResponse> {
  return request('/api/server/gpus/power-limit', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ watts, gpu_indices: gpuIndices ?? null }),
  })
}

export function getGpuPowerSettings(): Promise<GpuPowerSettings> {
  return request('/api/server/settings/gpu-power')
}

export function putGpuPowerSettings(payload: {
  enabled: boolean
  default_power_limit: number | null
  apply_now?: boolean
}): Promise<GpuPowerSettings> {
  return request('/api/server/settings/gpu-power', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getServerServices(): Promise<{ agent_online: boolean; services: ServiceStatus[] }> {
  return request('/api/server/services')
}

export function serviceAction(
  name: string,
  verb: 'start' | 'stop' | 'restart',
  force = false,
): Promise<ServiceStatus> {
  return request(`/api/server/services/${name}/${verb}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force }),
  })
}

export function getServiceLogs(name: string, lines: number): Promise<ServiceLogs> {
  return request(`/api/server/services/${name}/logs?lines=${lines}`)
}

export function prepareEnvironment(): Promise<{ started: boolean; message: string }> {
  return request('/api/server/environment/h3/prepare', { method: 'POST' })
}

export function getEnvironmentProfile(): Promise<EnvironmentProfile> {
  return request('/api/server/environment/h3/profile')
}

export function getGpuWorkloads(): Promise<{ agent_online: boolean; workloads: GpuWorkload[] }> {
  return request('/api/server/gpu-workloads')
}

export function stopGpuWorkload(container: string): Promise<{ stopped: string; freed_memory_mib: number }> {
  return request(`/api/server/gpu-workloads/${encodeURIComponent(container)}/stop`, { method: 'POST' })
}

export function getPrepareStatus(): Promise<PrepareRun> {
  return request('/api/server/environment/h3/status')
}

export function getServerOperations(
  limit = 100,
  offset = 0,
): Promise<{ total: number; items: ServerOperationItem[] }> {
  return request(`/api/server/operations?limit=${limit}&offset=${offset}`)
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function formatTime(ts: number | null | undefined): string {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

// ---- Workflow 模板管理 ----

export function listWorkflowTemplates(): Promise<WorkflowListResult> {
  return request<WorkflowListResult>('/api/workflows')
}

export function listUserWorkflowSources(): Promise<{ sources: UserWorkflowSource[] }> {
  return request<{ sources: UserWorkflowSource[] }>('/api/workflows/user-sources')
}

export function convertUserWorkflow(filename: string): Promise<ConvertPreview> {
  return request<ConvertPreview>('/api/workflows/convert', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename }),
  })
}

export function saveWorkflowTemplate(payload: {
  name: string
  workflow_api: Record<string, unknown>
  map_yaml: string
}): Promise<{ name: string; node_count: number; problems: string[] }> {
  return request('/api/workflows', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function setDefaultWorkflowTemplate(name: string): Promise<{ default: string }> {
  return request('/api/workflows/default', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export function deleteWorkflowTemplate(name: string): Promise<{ removed: string[] }> {
  return request(`/api/workflows/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

export function cancelQueuedBatch(batchId: string): Promise<{
  batch_id: string
  cancelled: number
  remaining_running?: number
  message: string
}> {
  return request(`/api/batches/${batchId}/cancel-queued`, { method: 'POST' })
}

export function updateTaskParams(
  taskId: string,
  payload: Partial<{
    width: number
    height: number
    fps: number
    num_frames: number
    prompt: string
    negative_prompt: string
    speech: string
  }>,
): Promise<TaskOut> {
  return request<TaskOut>(`/api/tasks/${taskId}/params`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
