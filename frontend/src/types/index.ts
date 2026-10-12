/** 后端 API 类型定义(与 backend/app/schemas 对应)。 */

export interface ParsedMetadata {
  title: string
  dynasty: string
  author: string
}

export interface ParsedGlobal {
  width: number | null
  height: number | null
  fps: number | null
  num_frames: number | null
  negative_prompt: string
}

export interface ParsedScene {
  scene_key: string
  scene_order: number
  speech: string
  prompt: string
}

export interface ParseResult {
  version: string
  metadata: ParsedMetadata
  global: ParsedGlobal
  scenes: ParsedScene[]
  warnings: string[]
  errors: string[]
  ok: boolean
}

export interface UploadItem {
  upload_id: string
  original_name: string
  guessed_scene_key: string | null
  size: number
  image_url: string
}

export interface BatchSummary {
  id: string
  title: string
  dynasty: string
  author: string
  status: string
  total_tasks: number
  completed_tasks: number
  failed_tasks: number
  created_at: number
  updated_at: number
}

export interface TaskOutputItem {
  output_id: string
  version: number
  output_path: string
  filename: string
  created_at: number
  download_url: string
}
export interface TaskOut {
  id: string
  batch_id: string
  scene_key: string
  scene_order: number
  image_path: string
  image_url: string
  prompt: string
  negative_prompt: string
  speech: string
  width: number
  height: number
  fps: number
  num_frames: number
  comfy_prompt_id: string | null
  status: string
  output_path: string
  video_url: string | null
  download_url: string | null
  error_message: string
  created_at: number
  started_at: number | null
  finished_at: number | null
  outputs: TaskOutputItem[]
}


export interface HealthCheck {
  ok: boolean
  message: string
}

export interface HealthResult {
  status: 'ok' | 'degraded' | 'error'
  checks: Record<string, HealthCheck>
}

export type WsTaskStatus = Pick<
  TaskOut,
  'id' | 'scene_key' | 'scene_order' | 'status' | 'comfy_prompt_id' | 'output_path' | 'error_message' | 'started_at' | 'finished_at'
>

export interface WsBatchSnapshot {
  batch_id: string
  batch_status: string
  tasks: WsTaskStatus[]
}

// ---- 服务器控制中心(任务04/05) ----

export interface GpuProcess {
  gpu_uuid: string | null
  pid: number | null
  process_name: string | null
  used_gpu_memory_mib: number | null
}

export interface GpuInfo {
  index: number
  uuid: string | null
  name: string | null
  temperature_c: number | null
  utilization_gpu_percent: number | null
  memory_used_mib: number | null
  memory_total_mib: number | null
  power_draw_w: number | null
  power_limit_w: number | null
  min_power_limit_w: number | null
  max_power_limit_w: number | null
  pstate: string | null
  fan_speed_percent: number | null
  processes: GpuProcess[]
}

export interface GpuPowerLimitResult {
  index: number
  before_watts: number | null
  requested_watts: number
  after_watts: number | null
}

export interface BulkPowerResultItem {
  index: number
  ok: boolean
  before_watts?: number | null
  after_watts?: number | null
  error?: string
}

export interface BulkPowerLimitResponse {
  all_ok: boolean
  watts: number
  results: BulkPowerResultItem[]
}

export interface GpuPowerSettings {
  enabled: boolean
  default_power_limit: number | null
  agent_online?: boolean
  agent_synced?: boolean
  agent_config?: { enabled: boolean; default_power_limit: number | null; per_gpu: Record<string, number> } | null
  agent_message?: string
  apply_results?: BulkPowerResultItem[] | null
}

export type ProcessState = 'running' | 'stopped' | 'failed' | 'activating' | 'deactivating' | 'unknown'
export type HealthState = 'healthy' | 'unhealthy' | 'starting' | 'unknown'

export interface ServiceStatus {
  name: string
  display_name: string
  unit: string
  gpu_profile: string
  description: string
  process_state: ProcessState
  health_state: HealthState
  health_url: string
  pid: number | null
  started_at: number | null
  uptime_seconds: number | null
}

export interface ServiceLogs {
  name: string
  unit: string
  lines: number
  logs: string[]
}

export interface PrepareStep {
  no: number
  key: string
  title: string
  state: 'pending' | 'running' | 'success' | 'skipped' | 'failed'
  detail: string
  started_at: number | null
  finished_at: number | null
  error: string
}

export interface PrepareRun {
  state: 'never' | 'running' | 'success' | 'failed'
  profile: Record<string, unknown>
  steps: PrepareStep[]
  started_at: number | null
  finished_at: number | null
  failure_step: string
  error_message: string
  total_seconds: number | null
}

export interface EnvironmentProfile {
  name: string
  display_name: string
  gpu_power: { enabled: boolean; watts: number | null }
  stop_services: string[]
  start_services: string[]
  readiness: { minimax_h3_timeout_seconds: number; comfyui_timeout_seconds: number }
}

export interface GpuWorkload {
  kind: 'docker' | 'systemd' | 'process'
  name: string
  display_name: string
  pids: number[]
  gpu_indices: number[]
  used_memory_mib: number
  command: string
  stoppable: boolean
}

export interface ServiceBrief {
  registered: boolean
  process_state: string
  health_state: string
}

export interface ServerSummary {
  agent: { ok: boolean; message: string; problems?: string[] }
  gpus: GpuInfo[]
  services: ServiceStatus[]
  environment: {
    ready: boolean
    reason?: string
    minimax_h3: ServiceBrief
    comfyui: ServiceBrief
    gpu_count: number
    power_limits: (number | null)[]
    prepare: PrepareRun
  }
}

export interface ServerOperationItem {
  id: string
  request_id: string
  action: string
  target_type: string
  target_name: string
  parameters: Record<string, unknown>
  result: string
  error_message: string
  source_ip: string
  created_at: number
  finished_at: number | null
}

export interface WorkflowTemplateItem {
  name: string
  has_map: boolean
  valid: boolean
  problems: string[]
  updated_at: number
  is_default: boolean
}

export interface WorkflowListResult {
  templates: WorkflowTemplateItem[]
  default: string
}

export interface UserWorkflowSource {
  filename: string
  size: number
}

export interface ConvertPreview {
  source: string
  suggested_name: string
  workflow_api: Record<string, unknown>
  map_draft: string
  warnings: string[]
}

