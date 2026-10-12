<template>
  <div class="batch-create">
    <EnvBanner />
    <!-- 基本信息 -->
    <el-card shadow="never" class="block">
      <template #header><span class="block-title">诗词基本信息</span></template>
      <el-form inline label-width="80px">
        <el-form-item label="诗词名称" required>
          <el-input v-model="form.title" data-testid="input-title" placeholder="如:宿建德江" style="width: 240px" />
        </el-form-item>
        <el-form-item label="朝代">
          <el-input v-model="form.dynasty" data-testid="input-dynasty" placeholder="如:唐" style="width: 120px" />
        </el-form-item>
        <el-form-item label="作者">
          <el-input v-model="form.author" data-testid="input-author" placeholder="如:孟浩然" style="width: 160px" />
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 图片上传 -->
    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-header-row">
          <span class="block-title">首帧图片(封面 + 各句场景图)</span>
          <span class="hint">支持 PNG / JPG / WEBP,可一次拖入多张;文件名 cover.png / 01.png 可辅助识别,手工绑定优先</span>
        </div>
      </template>
      <el-upload
        drag
        multiple
        action=""
        :http-request="uploadOne"
        :before-upload="validateFile"
        :show-file-list="false"
        accept=".png,.jpg,.jpeg,.webp"
      >
        <el-icon class="upload-icon"><UploadFilled /></el-icon>
        <div>拖入图片到此处,或点击选择文件</div>
      </el-upload>

      <div v-if="uploads.length" class="image-grid" data-testid="image-grid">
        <div v-for="(item, idx) in uploads" :key="item.upload_id" class="image-card" data-testid="image-card">
          <img :src="item.image_url" class="thumb" :alt="item.original_name" />
          <div class="image-name" :title="item.original_name">{{ item.original_name }}</div>
          <div class="image-meta">
            <el-tag v-if="item.guessed_scene_key" size="small" type="info">识别:{{ item.guessed_scene_key }}</el-tag>
            <span class="size">{{ (item.size / 1024).toFixed(0) }} KB</span>
          </div>
          <div class="image-actions">
            <el-select
              v-model="item.assigned_key"
              size="small"
              placeholder="绑定场景"
              clearable
              data-testid="bind-select"
              :disabled="!scenes.length"
              style="width: 130px"
              @change="(v?: string) => assignKey(item, v ?? null)"
            >
              <el-option v-for="s in scenes" :key="s.scene_key" :value="s.scene_key" :label="sceneLabel(s.scene_key)" />
            </el-select>
            <el-button size="small" :disabled="idx === 0" @click="moveUpload(idx, -1)" title="上移">↑</el-button>
            <el-button size="small" :disabled="idx === uploads.length - 1" @click="moveUpload(idx, 1)" title="下移">↓</el-button>
            <el-button size="small" type="danger" plain @click="removeUpload(idx)">移除</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 批量文本 -->
    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-header-row">
          <div class="title-wrap">
            <span class="block-title">批量任务文本(POEM_VIDEO_BATCH_V1)</span>
            <a class="template-link" href="/api/batches/text-template" download data-testid="template-link">下载文本模板</a>
          </div>
          <div>
            <el-button data-testid="parse-btn" type="primary" :loading="parsing" @click="doParse">解析任务</el-button>
            <el-button data-testid="clear-btn" @click="clearAll">清空</el-button>
          </div>
        </div>
      </template>
      <el-input
        v-model="batchText"
        type="textarea"
        :rows="14"
        data-testid="batch-textarea"
        placeholder="POEM_VIDEO_BATCH_V1 开头的批量文本……"
      />
      <div v-if="parseErrors.length" class="alert-list" data-testid="error-list">
        <el-alert v-for="(e, i) in parseErrors" :key="i" :title="e" type="error" :closable="false" show-icon />
      </div>
      <div v-if="parseWarnings.length" class="alert-list">
        <el-alert v-for="(w, i) in parseWarnings" :key="i" :title="w" type="warning" :closable="false" show-icon />
      </div>
    </el-card>

    <!-- 场景预览 -->
    <el-card v-if="scenes.length" shadow="never" class="block">
      <template #header>
        <div class="card-header-row">
          <span class="block-title">解析预览</span>
          <span class="stats" data-testid="stats-text">
            共 {{ scenes.length }} 个场景 · 已绑定 {{ boundCount }} 张图片 ·
            <el-tag :type="canCreate ? 'success' : 'danger'" size="small">{{ canCreate ? '可以创建批次' : '暂不可创建' }}</el-tag>
          </span>
        </div>
      </template>
      <div class="scene-grid">
        <div v-for="s in scenes" :key="s.scene_key" class="scene-card" data-testid="scene-card">
          <div class="scene-head">
            <el-tag :type="s.scene_key === 'cover' ? 'warning' : 'primary'" size="small">{{ sceneLabel(s.scene_key) }}</el-tag>
            <el-tag v-if="bindingOf(s.scene_key)" type="success" size="small">已绑定图片</el-tag>
            <el-tag v-else type="danger" size="small">未绑定图片</el-tag>
          </div>
          <img v-if="bindingOf(s.scene_key)" :src="bindingOf(s.scene_key)!.image_url" class="thumb" />
          <div v-else class="thumb thumb-empty">未绑定</div>
          <div class="speech" :title="s.speech">语音:{{ s.speech }}</div>
          <div class="prompt" :title="s.prompt">Prompt:{{ promptSummary(s.prompt) }}</div>
          <div class="params">{{ effWidth }} × {{ effHeight }} · {{ effFps }} fps · {{ effNumFrames }} 帧</div>
        </div>
      </div>
    </el-card>

    <div class="footer-actions">
      <el-button size="large" data-testid="create-btn" type="primary" :disabled="!canCreate" :loading="creating" @click="doCreate">
        创建批次
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { createBatch, parseBatch, submitBatch, uploadImages } from '@/api'
import type { ParseResult, UploadItem } from '@/types'
import EnvBanner from '@/components/EnvBanner.vue'

interface LocalUpload extends UploadItem {
  assigned_key: string | null
}

const router = useRouter()
const form = reactive({ title: '', dynasty: '', author: '' })
const batchText = ref('')
const uploads = ref<LocalUpload[]>([])
const parseResult = ref<ParseResult | null>(null)
const parsing = ref(false)
const creating = ref(false)

const scenes = computed(() => parseResult.value?.scenes ?? [])
const parseErrors = computed(() => (parseResult.value && !parseResult.value.ok ? parseResult.value.errors : []))
const parseWarnings = computed(() => parseResult.value?.warnings ?? [])

const effWidth = computed(() => parseResult.value?.global.width ?? 768)
const effHeight = computed(() => parseResult.value?.global.height ?? 1024)
const effFps = computed(() => parseResult.value?.global.fps ?? 24)
const effNumFrames = computed(() => parseResult.value?.global.num_frames ?? 121)

const boundCount = computed(() => scenes.value.filter((s) => bindingOf(s.scene_key)).length)
const canCreate = computed(
  () => !!parseResult.value?.ok && scenes.value.length > 0 && boundCount.value === scenes.value.length,
)

function sceneLabel(key: string): string {
  return key === 'cover' ? '封面 cover' : `场景 ${key}`
}

function promptSummary(p: string): string {
  const flat = p.replace(/\s+/g, ' ')
  return flat.length > 60 ? flat.slice(0, 60) + '…' : flat
}

function bindingOf(sceneKey: string): LocalUpload | undefined {
  return uploads.value.find((u) => u.assigned_key === sceneKey)
}

function validateFile(file: File): boolean {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (!['png', 'jpg', 'jpeg', 'webp'].includes(ext)) {
    ElMessage.error(`不支持的文件类型:${file.name}`)
    return false
  }
  if (file.size > 20 * 1024 * 1024) {
    ElMessage.error(`文件超过 20MB 上限:${file.name}`)
    return false
  }
  return true
}

async function uploadOne(opts: { file: File }) {
  try {
    const resp = await uploadImages([opts.file])
    for (const f of resp.files) {
      uploads.value.push({ ...f, assigned_key: null })
    }
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '上传失败')
  }
}

function removeUpload(idx: number) {
  uploads.value.splice(idx, 1)
}

function moveUpload(idx: number, dir: -1 | 1) {
  const target = idx + dir
  if (target < 0 || target >= uploads.value.length) return
  const list = [...uploads.value]
  ;[list[idx], list[target]] = [list[target], list[idx]]
  uploads.value = list
}

function assignKey(item: LocalUpload, key: string | null) {
  // 一个场景只允许绑定一张图:后绑定的顶掉先绑定的
  if (key) {
    for (const u of uploads.value) {
      if (u !== item && u.assigned_key === key) u.assigned_key = null
    }
  }
  item.assigned_key = key
}

function autoBind() {
  const unassigned = uploads.value.filter((u) => !u.assigned_key)
  for (const u of unassigned) {
    const hit = scenes.value.find((s) => s.scene_key === u.guessed_scene_key && !bindingOf(s.scene_key))
    if (hit) u.assigned_key = hit.scene_key
  }
  const restScenes = scenes.value.filter((s) => !bindingOf(s.scene_key))
  const restUploads = uploads.value.filter((u) => !u.assigned_key)
  restScenes.forEach((s, i) => {
    if (restUploads[i]) restUploads[i].assigned_key = s.scene_key
  })
}

async function doParse() {
  if (!batchText.value.trim()) {
    ElMessage.warning('请先粘贴批量任务文本')
    return
  }
  parsing.value = true
  try {
    const result = await parseBatch(batchText.value)
    parseResult.value = result
    if (result.ok) {
      autoBind()
      if (!form.title && result.metadata.title) form.title = result.metadata.title
      if (!form.dynasty && result.metadata.dynasty) form.dynasty = result.metadata.dynasty
      if (!form.author && result.metadata.author) form.author = result.metadata.author
      ElMessage.success(`解析成功:${result.scenes.length} 个场景`)
    } else {
      ElMessage.error(`解析失败,共 ${result.errors.length} 个错误`)
    }
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '解析请求失败')
  } finally {
    parsing.value = false
  }
}

function clearAll() {
  form.title = ''
  form.dynasty = ''
  form.author = ''
  batchText.value = ''
  uploads.value = []
  parseResult.value = null
}

async function doCreate() {
  if (!form.title.trim()) {
    ElMessage.error('请填写诗词名称')
    return
  }
  const image_bindings: Record<string, string> = {}
  for (const s of scenes.value) {
    const b = bindingOf(s.scene_key)
    if (!b) {
      ElMessage.error(`场景 ${s.scene_key} 未绑定图片`)
      return
    }
    image_bindings[s.scene_key] = b.upload_id
  }
  creating.value = true
  try {
    const batch = await createBatch({
      title: form.title,
      dynasty: form.dynasty,
      author: form.author,
      raw_batch_text: batchText.value,
      image_bindings,
    })
    // 创建后自动进入生成队列;提交失败不阻断跳转,可在批次页手动提交
    try {
      const result = await submitBatch(batch.id)
      ElMessage.success(`批次创建成功并已加入生成队列:${result.message}`)
    } catch (err) {
      ElMessage.warning(`批次已创建,但自动提交失败:${err instanceof Error ? err.message : err}。可到批次页手动提交`)
    }
    router.push(`/batches/${batch.id}`)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '创建批次失败')
  } finally {
    creating.value = false
  }
}
</script>

<style scoped>
.batch-create .block {
  margin-bottom: 16px;
}
.block-title {
  font-weight: 600;
}
.card-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.template-link {
  font-size: 12px;
  color: #409eff;
  text-decoration: none;
}
.template-link:hover {
  text-decoration: underline;
}
.hint {
  font-size: 12px;
  color: #909399;
}
.upload-icon {
  font-size: 40px;
  color: #c0c4cc;
  margin-bottom: 8px;
}
.image-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}
.image-card {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 8px;
  background: #fff;
}
.thumb {
  width: 100%;
  height: 120px;
  object-fit: cover;
  border-radius: 4px;
  background: #f5f7fa;
}
.thumb-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #c0c4cc;
  font-size: 13px;
}
.image-name {
  font-size: 12px;
  margin-top: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.image-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
.image-actions {
  display: flex;
  gap: 4px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.scene-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.scene-card {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px;
  background: #fff;
}
.scene-head {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}
.speech,
.prompt {
  font-size: 12px;
  color: #606266;
  margin-top: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.params {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
}
.alert-list {
  margin-top: 10px;
  display: grid;
  gap: 6px;
}
.stats {
  font-size: 13px;
  color: #606266;
}
.footer-actions {
  display: flex;
  justify-content: center;
  padding: 16px 0 32px;
}
</style>
