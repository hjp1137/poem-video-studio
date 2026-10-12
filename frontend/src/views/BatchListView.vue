<template>
  <div>
    <EnvBanner />
    <el-card shadow="never" class="block" data-testid="system-status">
      <template #header><span class="block-title">系统运行状态</span></template>
      <div v-if="health" class="status-grid">
        <div v-for="(check, key) in health.checks" :key="key" class="status-item">
          <span class="status-name">{{ checkNames[key as string] || key }}</span>
          <el-tag :type="check.ok ? 'success' : 'danger'" size="small">{{ check.ok ? '正常' : '异常' }}</el-tag>
          <span class="status-msg" :title="check.message">{{ check.message }}</span>
        </div>
      </div>
      <div v-else>正在获取系统状态…</div>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-header-row">
          <span class="block-title">批次列表</span>
          <el-button data-testid="refresh-btn" @click="loadAll">刷新</el-button>
        </div>
      </template>
      <el-empty v-if="!batches.length && !loading" description="暂无批次,先去新建批量任务吧" data-testid="batch-empty" />
      <el-table v-else :data="batches" v-loading="loading" data-testid="batch-table">
        <el-table-column label="诗词" min-width="180">
          <template #default="{ row }">
            <router-link :to="`/batches/${row.id}`" class="poem-link">《{{ row.title }}》</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="dynasty" label="朝代" width="80" />
        <el-table-column prop="author" label="作者" width="110" />
        <el-table-column label="进度" width="140">
          <template #default="{ row }">{{ row.completed_tasks }} / {{ row.total_tasks }} 已完成</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230">
          <template #default="{ row }">
            <router-link :to="`/batches/${row.id}`" class="row-link"><el-button size="small" plain>详情</el-button></router-link>
            <el-button
              v-if="isInQueue(row)"
              size="small"
              type="warning"
              plain
              class="row-btn"
              :loading="actingId === row.id"
              data-testid="cancel-queue-btn"
              @click="doCancelQueue(row)"
            >
              移除队列
            </el-button>
            <el-button
              v-else
              size="small"
              type="primary"
              plain
              class="row-btn"
              :disabled="row.completed_tasks >= row.total_tasks && row.status === 'completed'"
              :loading="actingId === row.id"
              data-testid="submit-queue-btn"
              @click="doSubmitQueue(row)"
            >
              提交队列
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { cancelQueuedBatch, formatTime, getHealth, listBatches, submitBatch } from '@/api'
import type { BatchSummary, HealthResult } from '@/types'
import EnvBanner from '@/components/EnvBanner.vue'

const batches = ref<BatchSummary[]>([])
const health = ref<HealthResult | null>(null)
const loading = ref(false)
const actingId = ref('')

function isInQueue(row: BatchSummary): boolean {
  return ['queued', 'running', 'submitting'].includes(row.status)
}

async function doSubmitQueue(row: BatchSummary) {
  actingId.value = row.id
  try {
    const result = await submitBatch(row.id)
    ElMessage.success(`${row.title}:${result.message}`)
    await loadAll()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '提交队列失败')
  } finally {
    actingId.value = ''
  }
}

async function doCancelQueue(row: BatchSummary) {
  actingId.value = row.id
  try {
    const result = await cancelQueuedBatch(row.id)
    ElMessage.success(`${row.title}:${result.message}`)
    await loadAll()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '移除队列失败')
  } finally {
    actingId.value = ''
  }
}

const checkNames: Record<string, string> = {
  api: 'PoemVideo Studio API',
  sqlite: 'SQLite',
  data_dir: 'Data Directory',
  workflow_template: 'Workflow Template',
  comfyui_http: 'ComfyUI HTTP',
  comfyui_queue: 'ComfyUI Queue',
}

const statusMap: Record<string, { text: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  draft: { text: '草稿', type: 'info' },
  parsed: { text: '已解析', type: 'info' },
  queued: { text: '已入队', type: 'warning' },
  running: { text: '生成中', type: 'primary' },
  completed: { text: '已完成', type: 'success' },
  partial_failed: { text: '部分失败', type: 'danger' },
  failed: { text: '失败', type: 'danger' },
}

function statusText(s: string) {
  return statusMap[s]?.text ?? s
}
function statusType(s: string) {
  return statusMap[s]?.type ?? 'info'
}

async function loadAll() {
  loading.value = true
  try {
    ;[batches.value, health.value] = await Promise.all([listBatches(), getHealth().catch(() => null)])
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)
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
}
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 8px;
}
.status-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.status-name {
  min-width: 170px;
  color: #606266;
}
.status-msg {
  color: #909399;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
}
.poem-link {
  color: #409eff;
  text-decoration: none;
}
.row-link {
  margin-right: 8px;
}
.row-btn {
  margin-left: 0;
}
</style>
