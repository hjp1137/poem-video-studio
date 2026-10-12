<template>
  <div class="workflow-templates">
    <!-- 从 ComfyUI 导入 -->
    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-header-row">
          <span class="block-title">从 ComfyUI 导入工作流</span>
          <el-button data-testid="refresh-sources-btn" @click="loadSources">刷新来源</el-button>
        </div>
      </template>
      <div class="import-row">
        <el-select
          v-model="selectedSource"
          data-testid="source-select"
          placeholder="选择 ComfyUI 用户工作流"
          style="width: 360px"
          :loading="sourcesLoading"
        >
          <el-option v-for="s in sources" :key="s.filename" :value="s.filename" :label="s.filename" />
        </el-select>
        <el-button
          type="primary"
          data-testid="convert-btn"
          :disabled="!selectedSource"
          :loading="converting"
          @click="doConvert"
        >
          转换预览
        </el-button>
      </div>
      <div v-if="!sources.length && !sourcesLoading" class="hint">
        未发现 ComfyUI 用户工作流:请先在 ComfyUI 界面保存工作流,或确认服务器挂载了 ComfyUI user 目录。
      </div>

      <div v-if="preview" class="preview" data-testid="convert-preview">
        <el-alert
          v-for="(w, i) in preview.warnings"
          :key="i"
          :title="w"
          type="warning"
          :closable="false"
          show-icon
          class="alert-item"
        />
        <div class="meta-row">
          <span>转换完成:{{ Object.keys(preview.workflow_api).length }} 个节点,草稿映射已按节点特征推断,请核对后保存。</span>
        </div>
        <div class="form-row">
          <span class="form-label">模板名称</span>
          <el-input v-model="previewName" data-testid="template-name-input" style="width: 280px" maxlength="64" />
        </div>
        <div class="form-row">
          <span class="form-label">节点映射 YAML</span>
          <el-input
            v-model="previewMap"
            type="textarea"
            :rows="14"
            data-testid="map-yaml-input"
            class="map-editor"
            spellcheck="false"
          />
        </div>
        <div class="form-row actions">
          <el-button type="primary" data-testid="save-template-btn" :loading="saving" @click="doSave">保存模板</el-button>
          <el-button @click="preview = null">取消</el-button>
        </div>
      </div>
    </el-card>

    <!-- 模板列表 -->
    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-header-row">
          <span class="block-title">Workflow 模板</span>
          <span class="hint">生成提交与重试使用「默认模板」;模板存放于数据卷 workflows 目录</span>
        </div>
      </template>
      <el-empty
        v-if="!templates.length && !loading"
        description="暂无模板:从上方导入 ComfyUI 工作流开始"
        data-testid="template-empty"
      />
      <el-table v-else :data="templates" v-loading="loading" data-testid="template-table">
        <el-table-column label="模板" min-width="200">
          <template #default="{ row }">
            <span class="tpl-name">{{ row.name }}</span>
            <el-tag v-if="row.is_default" type="success" size="small" class="default-tag">默认</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tooltip v-if="!row.valid" :content="row.problems.join('; ')" placement="top">
              <el-tag type="danger" size="small">校验失败</el-tag>
            </el-tooltip>
            <el-tag v-else type="success" size="small">可用</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain :disabled="row.is_default" data-testid="set-default-btn" @click="doSetDefault(row)">
              设为默认
            </el-button>
            <el-popconfirm :title="`确认删除模板「${row.name}」?`" width="240" @confirm="doDelete(row)">
              <template #reference>
                <el-button size="small" type="danger" plain data-testid="delete-template-btn">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  convertUserWorkflow,
  deleteWorkflowTemplate,
  listUserWorkflowSources,
  listWorkflowTemplates,
  saveWorkflowTemplate,
  setDefaultWorkflowTemplate,
} from '@/api'
import type { ConvertPreview, UserWorkflowSource, WorkflowTemplateItem } from '@/types'
import { formatTime } from '@/api'

const templates = ref<WorkflowTemplateItem[]>([])
const loading = ref(false)
const sources = ref<UserWorkflowSource[]>([])
const sourcesLoading = ref(false)
const selectedSource = ref('')
const converting = ref(false)
const preview = ref<ConvertPreview | null>(null)
const previewName = ref('')
const previewMap = ref('')
const saving = ref(false)

async function loadAll() {
  loading.value = true
  try {
    const result = await listWorkflowTemplates()
    templates.value = result.templates
  } finally {
    loading.value = false
  }
}

async function loadSources() {
  sourcesLoading.value = true
  try {
    sources.value = (await listUserWorkflowSources()).sources
  } finally {
    sourcesLoading.value = false
  }
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

async function doConvert() {
  if (!selectedSource.value) return
  converting.value = true
  preview.value = null
  try {
    const result = await convertUserWorkflow(selectedSource.value)
    preview.value = result
    previewName.value = result.suggested_name
    previewMap.value = result.map_draft
  } catch (e) {
    ElMessage.error(`转换失败:${errMsg(e)}`)
  } finally {
    converting.value = false
  }
}

async function doSave() {
  saving.value = true
  try {
    const current = preview.value
    if (!current || !previewName.value.trim()) {
      ElMessage.warning('请填写模板名称')
      return
    }
    const result = await saveWorkflowTemplate({
      name: previewName.value.trim(),
      workflow_api: current.workflow_api,
      map_yaml: previewMap.value,
    })
    if (result.problems.length) {
      ElMessage.warning(`已保存,但存在校验问题:${result.problems.join('; ')}`)
    } else {
      ElMessage.success(`模板「${result.name}」已保存(${result.node_count} 节点)`)
    }
    preview.value = null
    await loadAll()
  } catch (e) {
    ElMessage.error(`保存失败:${errMsg(e)}`)
  } finally {
    saving.value = false
  }
}

async function doSetDefault(row: WorkflowTemplateItem) {
  try {
    await setDefaultWorkflowTemplate(row.name)
    ElMessage.success(`已将「${row.name}」设为默认模板`)
    await loadAll()
  } catch (e) {
    ElMessage.error(`设置失败:${errMsg(e)}`)
  }
}

async function doDelete(row: WorkflowTemplateItem) {
  try {
    await deleteWorkflowTemplate(row.name)
    ElMessage.success(`模板「${row.name}」已删除`)
    await loadAll()
  } catch (e) {
    ElMessage.error(`删除失败:${errMsg(e)}`)
  }
}

onMounted(() => {
  loadAll()
  loadSources()
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
  gap: 12px;
  flex-wrap: wrap;
}
.hint {
  color: #909399;
  font-size: 12px;
}
.import-row {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.preview {
  margin-top: 16px;
  border-top: 1px dashed #dcdfe6;
  padding-top: 16px;
}
.alert-item {
  margin-bottom: 8px;
}
.meta-row {
  color: #606266;
  font-size: 13px;
  margin-bottom: 12px;
}
.form-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}
.form-label {
  min-width: 96px;
  padding-top: 5px;
  color: #606266;
  font-size: 13px;
}
.map-editor {
  width: 640px;
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 12px;
}
.actions {
  align-items: center;
}
.tpl-name {
  font-weight: 500;
}
.default-tag {
  margin-left: 8px;
}
</style>
