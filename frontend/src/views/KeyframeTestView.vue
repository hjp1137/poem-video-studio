<template>
  <div class="keyframe-test">
    <el-alert
      title="首尾帧生成试验功能"
      description="使用现有 FL2VA 后端，上传首帧、尾帧并生成一个 5 秒测试片段。不影响原有诗词批量任务或 ComfyUI 工作流。请勿将「参考图」误当成「尾帧」。"
      type="info" show-icon :closable="false" class="tip"
    />
    <el-card shadow="never">
      <template #header><strong>MiniMax H3 · 首帧＋尾帧</strong></template>
      <el-form label-position="top">
        <el-row :gutter="18">
          <el-col :xs="24" :sm="12">
            <el-form-item label="首帧图片（必填）">
              <input data-testid="first-frame" type="file" accept="image/png,image/jpeg,image/webp"
                     @change="onChoose($event, 'first')" />
              <img v-if="firstPreview" class="preview" :src="firstPreview" alt="首帧预览" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="尾帧图片（必填）">
              <input data-testid="last-frame" type="file" accept="image/png,image/jpeg,image/webp"
                     @change="onChoose($event, 'last')" />
              <img v-if="lastPreview" class="preview" :src="lastPreview" alt="尾帧预览" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="视频提示词">
          <el-input v-model="prompt" type="textarea" :rows="5" data-testid="keyframe-prompt"
                    placeholder="描述首帧到尾帧之间的人物动作、场景变化与镜头运动" />
        </el-form-item>

        <el-row :gutter="18">
          <el-col :xs="24" :sm="8">
            <el-form-item label="宽 × 高">
              <div class="size-group">
                <el-input-number v-model="width" :min="256" :max="2048" :step="32" controls-position="right" />
                <span>×</span>
                <el-input-number v-model="height" :min="256" :max="2048" :step="32" controls-position="right" />
              </div>
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="5">
            <el-form-item label="时长（秒）">
              <el-input-number v-model="duration" :min="4" :max="15" :step="0.5" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="5">
            <el-form-item label="Seed">
              <el-input-number v-model="seed" :min="0" :max="2147483647" :step="1" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="6">
            <el-form-item label="推理模式">
              <el-select v-model="turbo">
                <el-option :value="false" label="原版 50步" />
                <el-option :value="true" label="Turbo 8-step" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <p class="help-text">
          默认 768×1024、24fps。图片建议相同画幅；Turbo 8-step 仅在 H3 服务已预加载对应 FL2VA LoRA 时可用。
        </p>
        <el-button data-testid="generate-keyframe" type="primary" :loading="running"
                   :disabled="!ready" @click="run">
          {{ running ? 'H3 正在生成，请稍候…' : '生成首尾帧测试视频' }}
        </el-button>
        <span v-if="message" class="status" role="status">{{ message }}</span>
      </el-form>
    </el-card>
    <el-card v-if="resultUrl" class="result" shadow="never">
      <template #header><strong>生成结果</strong></template>
      <video :src="resultUrl" controls playsinline class="video" />
      <p><a :href="resultUrl" download="h3-first-last.mp4">下载视频 MP4</a></p>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generateKeyframeVideo } from '@/api'

type Slot = 'first' | 'last'
const first = ref<File | null>(null)
const last = ref<File | null>(null)
const firstPreview = ref('')
const lastPreview = ref('')
const prompt = ref('保持中国古典电影风格、人物身份与场景光影一致。镜头平稳地从首帧构图过渡到尾帧构图，动作自然，环境声音真实，无新增无关人物或物体。')
const width = ref(768)
const height = ref(1024)
const duration = ref(5)
const seed = ref(1101)
const turbo = ref(false)
const running = ref(false)
const message = ref('')
const resultUrl = ref('')
const ready = computed(() => !!first.value && !!last.value && !!prompt.value.trim() && !running.value)

function onChoose(event: Event, slot: Slot) {
  const file = (event.target as HTMLInputElement).files?.[0] || null
  if (file && (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 30 * 1024 * 1024)) {
    ElMessage.error('仅支持不超过 30MB 的 PNG/JPG/WEBP 图片')
    return
  }
  const current = slot === 'first' ? firstPreview : lastPreview
  if (current.value) URL.revokeObjectURL(current.value)
  current.value = file ? URL.createObjectURL(file) : ''
  if (slot === 'first') first.value = file
  else last.value = file
}

async function run() {
  if (!ready.value || !first.value || !last.value) return
  if (width.value % 32 !== 0 || height.value % 32 !== 0) {
    ElMessage.error('宽高必须是 32 的倍数')
    return
  }
  running.value = true
  message.value = '已提交到 H3，请勿关闭本页面；可能需要数分钟。'
  if (resultUrl.value) URL.revokeObjectURL(resultUrl.value)
  resultUrl.value = ''
  const form = new FormData()
  form.append('first_frame', first.value)
  form.append('last_frame', last.value)
  form.append('prompt', prompt.value)
  form.append('width', String(width.value))
  form.append('height', String(height.value))
  form.append('duration', String(duration.value))
  form.append('seed', String(seed.value))
  form.append('turbo', String(turbo.value))
  const start = Date.now()
  try {
    const video = await generateKeyframeVideo(form)
    resultUrl.value = URL.createObjectURL(video)
    message.value = '生成成功，耗时 ' + ((Date.now() - start) / 1000).toFixed(1) + ' 秒'
    ElMessage.success('首尾帧测试生成成功')
  } catch (err) {
    message.value = err instanceof Error ? err.message : String(err)
    ElMessage.error('生成失败，请查看错误信息')
  } finally {
    running.value = false
  }
}

onBeforeUnmount(() => {
  for (const url of [firstPreview.value, lastPreview.value, resultUrl.value]) {
    if (url) URL.revokeObjectURL(url)
  }
})
</script>

<style scoped>
.tip { margin-bottom: 16px; }
.keyframe-test { max-width: 1100px; margin: 0 auto; }
.preview { display: block; max-height: 260px; max-width: 100%; object-fit: contain; margin-top: 10px; border: 1px solid #dcdfe6; border-radius: 6px; }
.size-group { display: flex; gap: 8px; align-items: center; }
.size-group :deep(.el-input-number) { max-width: 125px; }
.help-text { color: #909399; font-size: 12px; margin: 0 0 14px; }
.status { margin-left: 12px; color: #606266; font-size: 13px; }
.result { margin-top: 18px; }
.video { width: 100%; max-height: 650px; background: #111; }
</style>
