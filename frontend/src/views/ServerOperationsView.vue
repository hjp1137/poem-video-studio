<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header-row">
        <span class="block-title">服务器操作日志(ServerOperation 审计)</span>
        <el-button data-testid="ops-refresh-btn" size="small" @click="load">刷新</el-button>
      </div>
    </template>
    <el-table :data="items" v-loading="loading" data-testid="ops-table" size="small">
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="action" label="动作" width="170">
        <template #default="{ row }">
          <el-tag size="small" :type="actionTagType(row.action)">{{ row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="目标" min-width="140">
        <template #default="{ row }">{{ row.target_name || row.target_type || '-' }}</template>
      </el-table-column>
      <el-table-column label="参数" min-width="220">
        <template #default="{ row }">
          <span class="mono params" :title="JSON.stringify(row.parameters)">{{ paramsBrief(row.parameters) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="结果" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.result === 'success' ? 'success' : row.result === 'blocked' ? 'warning' : 'danger'">
            {{ row.result }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="来源 IP" width="130">
        <template #default="{ row }">{{ row.source_ip || '-' }}</template>
      </el-table-column>
      <el-table-column label="错误" min-width="200">
        <template #default="{ row }">
          <span class="err" :title="row.error_message">{{ row.error_message || '-' }}</span>
        </template>
      </el-table-column>
    </el-table>
    <div class="pager" v-if="total > pageSize">
      <el-pagination layout="prev, pager, next" :total="total" :page-size="pageSize" :current-page="page" @current-change="onPage" />
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { formatTime, getServerOperations } from '@/api'
import type { ServerOperationItem } from '@/types'

const items = ref<ServerOperationItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)

function actionTagType(action: string): 'primary' | 'warning' | 'info' {
  if (action.startsWith('service.')) return 'warning'
  if (action.startsWith('environment.')) return 'primary'
  return 'info'
}

function paramsBrief(params: Record<string, unknown>): string {
  if (!params || !Object.keys(params).length) return '-'
  return JSON.stringify(params).slice(0, 120)
}

async function load() {
  loading.value = true
  try {
    const data = await getServerOperations(pageSize, (page.value - 1) * pageSize)
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function onPage(p: number) {
  page.value = p
  load()
}

onMounted(load)
</script>

<style scoped>
.block-title {
  font-weight: 600;
}
.card-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mono {
  font-family: Consolas, monospace;
  font-size: 12px;
}
.params {
  color: #606266;
}
.err {
  color: #f56c6c;
  font-size: 12px;
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
