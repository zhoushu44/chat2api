import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { monitorApi } from '@/api'
import type { UptimeHeartbeat, UptimeResponse, UptimeService } from '@/types/api'
import { useToast } from '@/composables/useToast'

type ServiceView = {
  key: string
  name: string
  statusLabel: string
  statusClass: string
  uptime: number
  total: number
  success: number
  beats: Array<{ className: string; tooltip: string | null }>
}

const slowThresholdMs = 40000
const maxBeats = 60
const AUTO_REFRESH_INTERVAL_MS = 15000

const mapStatusLabel = (statusValue: UptimeService['status']) => {
  if (statusValue === 'up') return '正常'
  if (statusValue === 'warn') return '注意'
  if (statusValue === 'down') return '异常'
  return '未知'
}

const mapStatusClass = (statusValue: UptimeService['status']) => {
  if (statusValue === 'up') return 'monitor-badge--up'
  if (statusValue === 'warn') return 'monitor-badge--warn'
  if (statusValue === 'down') return 'monitor-badge--down'
  return 'monitor-badge--unknown'
}

const buildBeats = (heartbeats: UptimeHeartbeat[] = []) => {
  const beats: Array<{ className: string; tooltip: string | null }> = []
  for (let i = 0; i < maxBeats; i += 1) {
    if (i < heartbeats.length) {
      const beat = heartbeats[i]
      const latencyMs = beat.latency_ms ?? null
      const isSlow = beat.success && latencyMs !== null && latencyMs > slowThresholdMs
      const level = beat.level ?? (isSlow ? 'warn' : (beat.success ? 'up' : 'down'))
      const className = level === 'warn'
        ? 'monitor-beat--warn'
        : (level === 'up' ? 'monitor-beat--up' : 'monitor-beat--down')
      const latencyText = latencyMs !== null
        ? ` · 首响 ${(Math.max(latencyMs, 0) / 1000).toFixed(1)}s`
        : ''
      const statusCodeText = beat.status_code ? ` · HTTP ${beat.status_code}` : ''
      const statusText = level === 'warn' ? '警告' : (beat.success ? '成功' : '失败')

      beats.push({
        className,
        tooltip: `${beat.time} · ${statusText}${statusCodeText}${latencyText}`,
      })
    } else {
      beats.push({ className: 'monitor-beat--empty', tooltip: null })
    }
  }
  return beats
}

export function useUptimeStatus() {
  const toast = useToast()
  const status = ref<UptimeResponse | null>(null)
  const errorMessage = ref('')
  const isLoading = ref(false)
  const isPageActive = ref(false)
  let autoRefreshTimer: number | null = null

  const updatedAt = computed(() => status.value?.updated_at ?? '')

  const services = computed<ServiceView[]>(() => {
    if (!status.value) return []

    const serviceMap = status.value.services && typeof status.value.services === 'object'
      ? status.value.services
      : {}

    return Object.entries(serviceMap).map(([key, service]) => ({
      key,
      name: service.name || key,
      statusLabel: mapStatusLabel(service.status),
      statusClass: mapStatusClass(service.status),
      uptime: Number(service.uptime || 0),
      total: Number(service.total || 0),
      success: Number(service.success || 0),
      beats: buildBeats(Array.isArray(service.heartbeats) ? service.heartbeats : []),
    }))
  })

  const refreshStatus = async () => {
    if (isLoading.value) return
    isLoading.value = true
    errorMessage.value = ''

    try {
      status.value = await monitorApi.uptime()
    } catch (error) {
      const message = (error as Error).message || '监控数据获取失败'
      errorMessage.value = ''
      toast.error(message)
    } finally {
      isLoading.value = false
    }
  }

  const clearAutoRefreshTimer = () => {
    if (autoRefreshTimer === null) return
    window.clearTimeout(autoRefreshTimer)
    autoRefreshTimer = null
  }

  const scheduleAutoRefresh = () => {
    clearAutoRefreshTimer()
    if (!isPageActive.value || document.hidden) return
    autoRefreshTimer = window.setTimeout(async () => {
      await refreshStatus()
      scheduleAutoRefresh()
    }, AUTO_REFRESH_INTERVAL_MS)
  }

  const handleVisibilityChange = () => {
    if (document.hidden) {
      clearAutoRefreshTimer()
      return
    }
    scheduleAutoRefresh()
  }

  onMounted(() => {
    isPageActive.value = true
    void refreshStatus()
    scheduleAutoRefresh()
    document.addEventListener('visibilitychange', handleVisibilityChange)
  })

  onActivated(() => {
    isPageActive.value = true
    void refreshStatus()
    scheduleAutoRefresh()
  })

  onDeactivated(() => {
    isPageActive.value = false
    clearAutoRefreshTimer()
  })

  onBeforeUnmount(() => {
    isPageActive.value = false
    clearAutoRefreshTimer()
    document.removeEventListener('visibilitychange', handleVisibilityChange)
  })

  return {
    services,
    updatedAt,
    errorMessage,
    isLoading,
    refreshStatus,
  }
}
