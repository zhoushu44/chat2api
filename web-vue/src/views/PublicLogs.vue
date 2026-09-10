<template>
  <div class="min-h-screen overflow-x-hidden bg-card/70 text-foreground backdrop-blur">
    <div class="mx-auto w-full max-w-6xl min-w-0 px-4 py-8">
      <PagePanel>
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="flex items-center gap-3">
            <img :src="logoUrl" alt="ChatGPT2API" class="h-8 w-8 object-contain" />
            <div>
              <p class="ui-section-title">公开日志</p>
            </div>
          </div>
          <div class="flex items-center gap-2 text-xs text-muted-foreground">
            <span>自动刷新：3s</span>
          </div>
        </div>

        <InfoCard class="mt-4" tone="muted" density="compact">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="text-xs text-muted-foreground">
              展示最近 <span class="font-semibold text-foreground">{{ limit }}</span> 条会话日志
            </div>
            <Button
              v-if="chatUrl"
              tag="a"
              :href="chatUrl"
              target="_blank"
              size="sm"
              variant="outline"
            >
              开始对话
            </Button>
            <span v-else class="text-xs text-muted-foreground">开始对话</span>
          </div>
        </InfoCard>

        <MetricStrip
          class="mt-4"
          :items="statCards"
          columns-class="grid-cols-2 md:grid-cols-4"
          density="compact"
        />

        <ResultState
          v-if="logs.length === 0"
          class="mt-4"
          title="暂无日志"
          description="当前还没有可展示的公开会话日志。"
        />

        <div v-else-if="logs.length > 0" class="mt-4 max-h-[60vh] space-y-3 overflow-y-auto pr-1 scrollbar-slim">
          <RequestLogGroup
            v-for="log in visibleLogs"
            :key="log.request_id"
            :status-label="statusLabel(log.status)"
            :status-badge-class="statusBadgeClass(log.status)"
            :request-id="log.request_id"
            :collapsed="isCollapsed(log.request_id)"
            :count-text="`${log.events.length} 条事件`"
            @toggle="toggleGroup(log.request_id)"
          >
            <div class="space-y-2">
              <LogEntryRow
                v-for="event in log.events"
                :key="`${log.request_id}-${event.time}-${event.type}`"
                :time="event.time"
                :text="event.content"
                :badge-text="eventLabel(event)"
                :badge-class="eventBadgeClass(event)"
              />
            </div>
          </RequestLogGroup>
        </div>
      </PagePanel>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { publicDisplayApi, publicLogsApi, publicStatsApi } from '@/api'
import { Button, ResultState } from 'nanocat-ui'
import { useToast } from '@/composables/useToast'
import { InfoCard, LogEntryRow, MetricStrip, PagePanel, RequestLogGroup } from '@/components/ai'
import { getJsonPreference, preferenceKeys, setJsonPreference } from '@/lib/preferences'
import type {
  PublicDisplay,
  PublicLogEvent,
  PublicLogGroup,
  PublicLogStatus,
  PublicStats,
} from '@/types/api'

const logs = ref<PublicLogGroup[]>([])
const stats = ref<PublicStats | null>(null)
const display = ref<PublicDisplay | null>(null)
const toast = useToast()
const lastUpdated = ref('--:--')
const collapsedState = ref<Record<string, boolean>>({})
const limit = 1000
const renderLimit = 1000
const refreshIntervalMs = 3000
let timer: number | undefined
let isFetching = false

const logoUrl = computed(() => {
  const url = display.value?.logo_url?.trim()
  return url || '/logo.svg'
})
const chatUrl = computed(() => display.value?.chat_url?.trim() || '')

const totalLogs = computed(() => logs.value.length)
const successLogs = computed(() => logs.value.filter(log => log.status === 'success').length)
const errorLogs = computed(() => logs.value.filter(log => log.status === 'error').length)

const visibleLogs = computed(() => {
  if (logs.value.length > renderLimit) {
    return logs.value.slice(-renderLimit)
  }
  return logs.value
})

const avgResponseTime = computed(() => {
  let total = 0
  let count = 0

  logs.value.forEach(log => {
    if (log.status !== 'success') return
    log.events.forEach(event => {
      if (event.type !== 'complete') return
      const match = event.content.match(/([0-9]+(?:\.[0-9]+)?)\s*s/)
      if (match) {
        total += Number(match[1])
        count += 1
      }
    })
  })

  if (count === 0) return '-'
  return `${(total / count).toFixed(1)}s`
})

const successRate = computed(() => {
  const completed = successLogs.value + errorLogs.value
  if (completed === 0) return '-'
  return `${((successLogs.value / completed) * 100).toFixed(1)}%`
})

const statCards = computed(() => [
  { key: 'visitors', label: '总访客', value: stats.value?.total_visitors ?? 0 },
  {
    key: 'rpm',
    label: '每分钟请求',
    value: stats.value?.requests_per_minute ?? 0,
    valueStyle: stats.value?.load_color ? { color: stats.value.load_color } : undefined,
  },
  { key: 'avg', label: '平均响应', value: avgResponseTime.value },
  { key: 'success-rate', label: '成功率', value: successRate.value, valueClass: 'text-emerald-600' },
  { key: 'total', label: '对话次数', value: totalLogs.value },
  { key: 'success', label: '成功', value: successLogs.value, valueClass: 'text-emerald-600' },
  { key: 'error', label: '失败', value: errorLogs.value, valueClass: 'text-rose-600' },
  { key: 'updated', label: '更新时间', value: lastUpdated.value, valueClass: 'text-muted-foreground' },
])

const statusLabel = (status: PublicLogStatus) => {
  if (status === 'success') return '成功'
  if (status === 'error') return '失败'
  if (status === 'timeout') return '超时'
  return '进行中'
}

const statusBadgeClass = (status: PublicLogStatus) => {
  const base = 'rounded-md px-2 py-0.5 text-[11px] font-semibold'
  if (status === 'success') return `${base} bg-emerald-100 text-emerald-700`
  if (status === 'error') return `${base} bg-rose-100 text-rose-700`
  if (status === 'timeout') return `${base} bg-amber-100 text-amber-700`
  return `${base} bg-amber-100 text-amber-700`
}

const eventLabel = (event: PublicLogEvent) => {
  if (event.type === 'start') return '开始对话'
  if (event.type === 'select') return '选择'
  if (event.type === 'retry') return '重试'
  if (event.type === 'switch') return '切换'
  if (event.type === 'complete') {
    if (event.status === 'success') return '完成'
    if (event.status === 'error') return '失败'
    if (event.status === 'timeout') return '超时'
    return '完成'
  }
  return '事件'
}

const eventBadgeClass = (event: PublicLogEvent) => {
  const base = 'rounded-md px-2 py-0.5 text-[11px] font-semibold'
  if (event.type === 'start') return `${base} bg-blue-100 text-blue-700`
  if (event.type === 'select') return `${base} bg-violet-100 text-violet-700`
  if (event.type === 'retry') return `${base} bg-amber-100 text-amber-700`
  if (event.type === 'switch') return `${base} bg-cyan-100 text-cyan-700`
  if (event.type === 'complete') {
    if (event.status === 'success') return `${base} bg-emerald-100 text-emerald-700`
    if (event.status === 'error') return `${base} bg-rose-100 text-rose-700`
    if (event.status === 'timeout') return `${base} bg-amber-100 text-amber-700`
  }
  return `${base} bg-slate-100 text-slate-600`
}

const loadCollapseState = () => {
  collapsedState.value = getJsonPreference<Record<string, boolean>>(preferenceKeys.publicLogFoldState, {})
}

const saveCollapseState = () => {
  setJsonPreference(preferenceKeys.publicLogFoldState, collapsedState.value)
}

const isCollapsed = (requestId: string) => collapsedState.value[requestId] === true

const toggleGroup = (requestId: string) => {
  collapsedState.value[requestId] = !isCollapsed(requestId)
  saveCollapseState()
}

const fetchData = async () => {
  if (isFetching) return
  isFetching = true
  try {
    const [logsResponse, statsResponse] = await Promise.all([
      publicLogsApi.list({ limit }),
      publicStatsApi.overview(),
    ])
    logs.value = logsResponse.logs
    stats.value = statsResponse
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch (error: any) {
    toast.error(error.message || '日志加载失败')
  } finally {
    isFetching = false
  }
}

const fetchDisplay = async () => {
  try {
    display.value = await publicDisplayApi.overview()
  } catch {
    display.value = null
  }
}

const stopAutoRefresh = () => {
  if (timer) {
    window.clearTimeout(timer)
    timer = undefined
  }
}

const scheduleAutoRefresh = () => {
  if (document.hidden) return
  timer = window.setTimeout(async () => {
    await fetchData()
    scheduleAutoRefresh()
  }, refreshIntervalMs)
}

const startAutoRefresh = () => {
  stopAutoRefresh()
  scheduleAutoRefresh()
}

const handleVisibilityChange = () => {
  if (document.hidden) {
    stopAutoRefresh()
  } else {
    startAutoRefresh()
  }
}

onMounted(() => {
  loadCollapseState()
  fetchDisplay()
  fetchData()
  startAutoRefresh()
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  stopAutoRefresh()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>
