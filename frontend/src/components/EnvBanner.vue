<template>
  <el-alert
    v-if="visible"
    :type="ready ? 'success' : 'warning'"
    :closable="false"
    show-icon
    class="env-banner"
    data-testid="env-banner"
  >
    <template #title>
      <span v-if="ready" data-testid="env-banner-ready">
        视频环境:READY · MiniMax H3 {{ h3Text }} · ComfyUI {{ comfyText }}
      </span>
      <span v-else data-testid="env-banner-notready">
        视频环境:NOT READY · MiniMax H3 {{ h3Text }} · ComfyUI {{ comfyText }}
        <el-button size="small" type="warning" plain class="prepare-link" data-testid="env-prepare-link" @click="goPrepare">
          准备环境
        </el-button>
      </span>
    </template>
  </el-alert>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getServerSummary } from '@/api'
import type { ServerSummary, ServiceBrief } from '@/types'

/** 批量页面环境条:只读展示 + 跳转准备;绝不因打开页面就自动停止模型或改功耗。 */
const router = useRouter()
const summary = ref<ServerSummary | null>(null)
const failed = ref(false)

const visible = computed(() => summary.value !== null || failed.value)
const ready = computed(() => summary.value?.environment?.ready ?? false)

function stateText(brief: ServiceBrief | undefined): string {
  if (!brief || !brief.registered) return '未登记'
  if (brief.health_state === 'healthy') return 'Healthy'
  if (brief.process_state === 'running') return 'Starting'
  return brief.process_state === 'stopped' ? 'Stopped' : brief.process_state
}

const h3Text = computed(() => stateText(summary.value?.environment?.minimax_h3))
const comfyText = computed(() => stateText(summary.value?.environment?.comfyui))

async function refresh() {
  try {
    summary.value = await getServerSummary()
    failed.value = false
  } catch {
    failed.value = true
  }
}

function goPrepare() {
  router.push('/server')
}

let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  refresh()
  timer = setInterval(() => {
    if (document.visibilityState === 'visible') refresh()
  }, 15000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.env-banner {
  margin-bottom: 16px;
}
.prepare-link {
  margin-left: 12px;
}
</style>
