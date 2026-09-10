<template>
  <div class="space-y-6">
    <PagePanel class="space-y-5">
      <PanelHeader title="实时监控" align="start">
        <template #copy>
          <p class="mt-1 text-xs text-muted-foreground">
            容器内存实时窗口，不做历史时间范围；用于观察入口排队、账号等待、上游生成和下载耗时。
          </p>
          <p class="mt-1 text-xs text-muted-foreground">
            最近更新：{{ monitorData?.updated_at || '未获取' }}
          </p>
        </template>
        <template #actions>
          <StateBadge :tone="autoRefresh ? 'success' : 'muted'" shape="rounded">
            {{ autoRefresh ? '自动刷新' : '已暂停' }}
          </StateBadge>
          <Button size="sm" variant="outline" :disabled="isLoading" @click="loadMonitor(false)">
            {{ isLoading ? '刷新中...' : '立即刷新' }}
          </Button>
          <Button size="sm" variant="outline" @click="toggleAutoRefresh">
            {{ autoRefresh ? '暂停刷新' : '继续刷新' }}
          </Button>
        </template>
      </PanelHeader>

      <MetricStrip
        :items="summaryItems"
        columns-class="grid-cols-2 md:grid-cols-3 xl:grid-cols-6"
        density="compact"
      />

      <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div
          v-for="item in stageItems"
          :key="item.key"
          class="rounded-2xl border border-border bg-background px-4 py-3"
        >
          <p class="text-xs text-muted-foreground">{{ item.label }}</p>
          <p class="mt-1 text-base font-semibold text-foreground">{{ item.value }}</p>
          <p class="mt-1 text-[11px] text-muted-foreground">{{ item.meta }}</p>
        </div>
      </div>

      <StateBlock
        v-if="loadError"
        compact
        dashed
        title="实时监控加载失败"
        :description="loadError"
      />
    </PagePanel>

    <PagePanel flush>
      <div class="p-4">
        <PanelHeader title="活跃请求" align="start">
          <template #copy>
            <p class="mt-1 text-xs text-muted-foreground">
              正在运行的图片请求，按进入时间排序。
            </p>
          </template>
          <template #actions>
            <MetaChip size="xs" tone="info">线程 {{ threadTokens }}</MetaChip>
            <MetaChip size="xs" tone="muted">活跃 {{ activeRows.length }}</MetaChip>
          </template>
        </PanelHeader>
      </div>
      <TableShell v-if="activeRows.length">
        <table class="monitor-table">
          <thead>
            <tr>
              <th>请求</th>
              <th>模型</th>
              <th>阶段</th>
              <th>已耗时</th>
              <th>关键耗时</th>
              <th>账号</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in activeRows" :key="row.call_id">
              <td>
                <p class="font-mono text-xs text-foreground">{{ shortCallId(row.call_id) }}</p>
                <p class="mt-1 text-[11px] text-muted-foreground">{{ row.endpoint || '-' }}</p>
              </td>
              <td>
                <MetaChip size="xs" tone="muted">{{ row.model || '-' }}</MetaChip>
              </td>
              <td>
                <StateBadge tone="info" shape="rounded" :bordered="false">
                  {{ row.stage_label || row.stage || '运行中' }}
                </StateBadge>
              </td>
              <td>{{ formatMs(row.elapsed_ms) }}</td>
              <td>{{ metricDigest(row) }}</td>
              <td class="max-w-[12rem] truncate">{{ row.account_email || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </TableShell>
      <div v-else class="px-4 pb-4">
        <StateBlock compact dashed title="暂无活跃请求" description="开始压测或发起图片请求后，这里会实时出现运行中的调用。" />
      </div>
    </PagePanel>

    <div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(22rem,0.72fr)]">
      <PagePanel flush>
        <div class="p-4">
          <PanelHeader title="最近完成" align="start">
            <template #copy>
              <p class="mt-1 text-xs text-muted-foreground">
                最近完成的图片相关调用，窗口保存在进程内存中。
              </p>
            </template>
            <template #actions>
              <MetaChip size="xs" tone="muted">{{ completedWindowText }}</MetaChip>
            </template>
          </PanelHeader>
        </div>
        <TableShell v-if="recentRows.length">
          <table class="monitor-table">
            <thead>
              <tr>
                <th>请求</th>
                <th>状态</th>
                <th>模型</th>
                <th>总耗时</th>
                <th>线程等待</th>
                <th>账号等待</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in recentRows" :key="`recent-${row.call_id}-${row.ended_at}`">
                <td>
                  <p class="font-mono text-xs text-foreground">{{ shortCallId(row.call_id) }}</p>
                  <p class="mt-1 text-[11px] text-muted-foreground">{{ row.ended_at || row.updated_at || '-' }}</p>
                </td>
                <td>
                  <StateBadge :tone="statusTone(row.status)" shape="rounded" :bordered="false">
                    {{ statusLabel(row.status) }}
                  </StateBadge>
                </td>
                <td class="max-w-[12rem] truncate">{{ row.model || '-' }}</td>
                <td>{{ formatMs(row.duration_ms) }}</td>
                <td>{{ formatMs(metricValue(row, 'handler_queue_ms')) }}</td>
                <td>{{ formatMs(metricValue(row, 'account_wait_ms')) }}</td>
              </tr>
            </tbody>
          </table>
        </TableShell>
        <div v-else class="px-4 pb-4">
          <StateBlock compact dashed title="暂无完成记录" description="当前容器启动后还没有图片相关请求完成。" />
        </div>
      </PagePanel>

      <PagePanel flush>
        <div class="p-4">
          <PanelHeader title="慢请求" align="start">
            <template #copy>
              <p class="mt-1 text-xs text-muted-foreground">
                按总耗时、线程等待和账号等待综合排序。
              </p>
            </template>
          </PanelHeader>
        </div>
        <div v-if="slowRows.length" class="space-y-2 px-4 pb-4">
          <div
            v-for="row in slowRows"
            :key="`slow-${row.call_id}-${row.ended_at}`"
            class="rounded-2xl border border-border bg-background px-3 py-3"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="truncate text-sm font-medium text-foreground">
                  {{ row.model || '-' }}
                  <span class="font-mono text-xs text-muted-foreground">{{ shortCallId(row.call_id) }}</span>
                </p>
                <p class="mt-1 text-xs text-muted-foreground">{{ row.endpoint || '-' }}</p>
              </div>
              <StateBadge :tone="statusTone(row.status)" size="xs" shape="rounded" :bordered="false">
                {{ formatMs(row.duration_ms) }}
              </StateBadge>
            </div>
            <div class="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
              <span
                v-for="item in slowMetricItems(row)"
                :key="`${row.call_id}-${item.key}`"
                class="rounded-xl px-2 py-1"
                :class="item.important ? 'bg-primary/10 text-primary' : 'bg-muted/60'"
              >
                {{ item.label }} {{ item.value }}
              </span>
            </div>
            <p v-if="slowRowReason(row)" class="mt-2 text-xs text-muted-foreground">
              {{ slowRowReason(row) }}
            </p>
            <p v-if="row.error" class="mt-2 line-clamp-2 text-xs text-muted-foreground">
              {{ row.error }}
            </p>
          </div>
        </div>
        <div v-else class="px-4 pb-4">
          <StateBlock compact dashed title="暂无慢请求" description="窗口内没有可排序的完成请求。" />
        </div>
      </PagePanel>
    </div>

    <PagePanel flush>
      <div class="p-4">
        <PanelHeader title="阶段事件" align="start">
          <template #copy>
            <p class="mt-1 text-xs text-muted-foreground">
              最近阶段变化，辅助观察请求是否集中卡在同一环节。
            </p>
          </template>
        </PanelHeader>
      </div>
      <TableShell v-if="eventRows.length">
        <table class="monitor-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>请求</th>
              <th>模型</th>
              <th>阶段</th>
              <th>耗时</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in eventRows" :key="`${row.call_id}-${row.event}-${index}`">
              <td>{{ row.time || '-' }}</td>
              <td class="font-mono text-xs">{{ shortCallId(row.call_id) }}</td>
              <td class="max-w-[14rem] truncate">{{ row.model || '-' }}</td>
              <td>{{ row.label || row.event }}</td>
              <td>{{ eventMetricText(row) }}</td>
            </tr>
          </tbody>
        </table>
      </TableShell>
      <div v-else class="px-4 pb-4">
        <StateBlock compact dashed title="暂无阶段事件" description="有图片请求进入后会开始记录。" />
      </div>
    </PagePanel>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Button } from 'nanocat-ui'
import { monitorApi, type RealtimeMonitorEvent, type RealtimeMonitorRecord, type RealtimeMonitorResponse } from '@/api/monitor'
import { MetaChip, MetricStrip, PagePanel, PanelHeader, StateBadge, StateBlock, TableShell } from '@/components/ai'

type BadgeTone = 'success' | 'danger' | 'warning' | 'info' | 'muted'

const monitorData = ref<RealtimeMonitorResponse | null>(null)
const isLoading = ref(false)
const loadError = ref('')
const autoRefresh = ref(true)
let refreshTimer: number | undefined

const summary = computed(() => monitorData.value?.summary)
const activeRows = computed(() => monitorData.value?.active || [])
const recentRows = computed(() => monitorData.value?.recent.slice(0, 20) || [])
const slowRows = computed(() => monitorData.value?.slow.slice(0, 8) || [])
const eventRows = computed(() => monitorData.value?.events.slice(0, 30) || [])
const threadTokens = computed(() => monitorData.value?.threadpool?.tokens || '-')
const completedWindowText = computed(() => {
  const windowInfo = monitorData.value?.window
  if (!windowInfo) return '窗口 0 / 0'
  return `窗口 ${windowInfo.completed} / ${windowInfo.completed_capacity}`
})

const summaryItems = computed(() => {
  const data = summary.value
  const bottleneckValue = Number(data?.bottleneck?.value_ms || 0)
  return [
    { label: '活跃请求', value: data?.active ?? 0, meta: `线程 ${threadTokens.value}` },
    { label: '完成窗口', value: data?.completed ?? 0, meta: completedWindowText.value },
    { label: '成功率', value: `${data?.success_rate ?? 0}%`, meta: `失败 ${data?.failed ?? 0}` },
    { label: '平均耗时', value: formatMs(data?.avg_duration_ms), meta: `P95 ${formatMs(data?.p95_duration_ms)}` },
    { label: '入口等待 P95', value: formatMs(data?.metric_p95?.handler_queue_ms), meta: `慢 ${data?.slow_counts?.handler_queue ?? 0}` },
    { label: '当前瓶颈', value: data?.bottleneck?.label || '-', meta: bottleneckValue > 0 ? formatMs(bottleneckValue) : '' },
  ]
})

const stageItems = computed(() => {
  const p95 = summary.value?.metric_p95 || {}
  return [
    { key: 'handler_queue_ms', label: '入口线程等待 P95', value: formatMs(p95.handler_queue_ms), meta: '请求进入后等待 run_in_threadpool' },
    { key: 'stream_first_queue_ms', label: '首包线程等待 P95', value: formatMs(p95.stream_first_queue_ms), meta: '流式响应读取首个事件前的等待' },
    { key: 'account_wait_ms', label: '账号等待 P95', value: formatMs(p95.account_wait_ms), meta: '从账号池拿可用图片账号' },
    { key: 'conversation_stream_ms', label: '上游生成 P95', value: formatMs(p95.conversation_stream_ms), meta: 'ChatGPT 会话流返回到解析前' },
    { key: 'resolve_ms', label: '图片解析 P95', value: formatMs(p95.resolve_ms), meta: '从 conversation/file/sediment 解析图片 URL' },
    { key: 'download_ms', label: '图片下载 P95', value: formatMs(p95.download_ms), meta: '下载图片并准备返回' },
    { key: 'retry_wait_ms', label: '重试等待 P95', value: formatMs(p95.retry_wait_ms), meta: '轮询、TLS 或连接失败后的退避等待' },
    { key: 'total_ms', label: '单图总耗时 P95', value: formatMs(p95.total_ms), meta: '单张图内部完整耗时' },
  ]
})

async function loadMonitor(silent = true) {
  if (isLoading.value && silent) return
  isLoading.value = true
  try {
    monitorData.value = await monitorApi.realtime()
    loadError.value = ''
  } catch (error: any) {
    loadError.value = error?.message || 'Request failed'
  } finally {
    isLoading.value = false
  }
}

function startPolling() {
  stopPolling()
  if (!autoRefresh.value) return
  refreshTimer = window.setInterval(() => {
    void loadMonitor(true)
  }, 2000)
}

function stopPolling() {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    void loadMonitor(true)
    startPolling()
  } else {
    stopPolling()
  }
}

function formatMs(value: unknown) {
  const ms = Number(value || 0)
  if (!Number.isFinite(ms) || ms <= 0) return '-'
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

function shortCallId(value: unknown) {
  const text = String(value || '')
  return text ? text.slice(0, 8) : '-'
}

function metricValue(row: RealtimeMonitorRecord, key: string) {
  const perf = row.perf || {}
  const metrics = row.metrics || {}
  return Math.max(Number(perf[key] || 0), Number(metrics[key] || 0))
}

function metricDigest(row: RealtimeMonitorRecord) {
  const pairs = [
    ['入口', 'handler_queue_ms'],
    ['首包', 'stream_first_queue_ms'],
    ['账号', 'account_wait_ms'],
    ['上游', 'conversation_stream_ms'],
    ['解析/轮询', 'resolve_ms'],
    ['下载', 'download_ms'],
    ['重试等待', 'retry_wait_ms'],
    ['单图链路', 'stream_ms'],
  ] as const
  const parts = pairs
    .map(([label, key]) => {
      const value = metricValue(row, key)
      return value > 0 ? { label, value, text: `${label} ${formatMs(value)}` } : null
    })
    .filter(Boolean)
    .sort((a, b) => (b?.value || 0) - (a?.value || 0))
    .map(item => item?.text || '')
  return parts.slice(0, 4).join(' / ') || '-'
}

function rowDurationMs(row: RealtimeMonitorRecord) {
  const value = Math.max(Number(row.duration_ms || 0), Number(row.elapsed_ms || 0))
  return Number.isFinite(value) ? Math.max(0, value) : 0
}

function trackedDurationMs(row: RealtimeMonitorRecord) {
  const queue = metricValue(row, 'handler_queue_ms') + metricValue(row, 'stream_first_queue_ms')
  const linearStages = [
    'account_wait_ms',
    'conversation_stream_ms',
    'resolve_ms',
    'download_ms',
    'retry_wait_ms',
    'response_ms',
  ].reduce((sum, key) => sum + metricValue(row, key), 0)
  const wrappedStage = Math.max(metricValue(row, 'total_ms'), metricValue(row, 'stream_ms'), linearStages)
  return queue + wrappedStage
}

function untrackedDurationMs(row: RealtimeMonitorRecord) {
  return Math.max(0, rowDurationMs(row) - trackedDurationMs(row))
}

function slowMetricItems(row: RealtimeMonitorRecord) {
  const pairs = [
    { key: 'handler_queue_ms', label: '入口' },
    { key: 'stream_first_queue_ms', label: '首包' },
    { key: 'account_wait_ms', label: '账号' },
    { key: 'conversation_stream_ms', label: '上游' },
    { key: 'resolve_ms', label: '解析/轮询' },
    { key: 'download_ms', label: '下载' },
    { key: 'retry_wait_ms', label: '重试等待' },
    { key: 'response_ms', label: '响应整理' },
    { key: 'stream_ms', label: '单图链路' },
    { key: 'total_ms', label: '单图总计' },
  ]
  const items = pairs
    .map((item) => {
      const raw = metricValue(row, item.key)
      return raw > 0
        ? { ...item, raw, value: formatMs(raw), important: raw >= 10_000 }
        : null
    })
    .filter(Boolean) as Array<{ key: string; label: string; raw: number; value: string; important: boolean }>
  const untracked = untrackedDurationMs(row)
  if (untracked >= 1000) {
    items.push({
      key: 'untracked_ms',
      label: '未标记',
      raw: untracked,
      value: formatMs(untracked),
      important: untracked >= 10_000,
    })
  }
  if (!items.length) {
    const total = rowDurationMs(row)
    if (total > 0) {
      items.push({ key: 'duration_ms', label: '总耗时', raw: total, value: formatMs(total), important: total >= 10_000 })
    }
  }
  return items
}

function slowRowReason(row: RealtimeMonitorRecord) {
  const candidates = slowMetricItems(row)
    .filter(item => !['stream_ms', 'total_ms', 'duration_ms'].includes(item.key))
    .sort((a, b) => b.raw - a.raw)
  const top = candidates[0]
  if (!top || top.raw < 1000) return ''
  if (top.key === 'untracked_ms') {
    return `仍有 ${top.value} 没有落到具体阶段，说明这段链路还缺埋点。`
  }
  if (top.key === 'resolve_ms') {
    return `主要卡在图片结果解析/轮询，通常对应等待 ChatGPT 图片任务完成或轮询超时。`
  }
  if (top.key === 'conversation_stream_ms') {
    return `主要卡在上游会话流，通常是 ChatGPT 生成阶段耗时。`
  }
  if (top.key === 'account_wait_ms') {
    return `主要卡在账号等待，通常是可用账号不足或账号并发被占满。`
  }
  if (top.key === 'retry_wait_ms') {
    return `主要卡在重试等待，通常是轮询、TLS 或连接失败后的退避时间。`
  }
  if (top.key === 'handler_queue_ms' || top.key === 'stream_first_queue_ms') {
    return `主要卡在线程入口等待，通常是服务端并发线程被占满。`
  }
  return `主要耗时：${top.label} ${top.value}。`
}

function statusLabel(status: unknown) {
  const value = String(status || '').toLowerCase()
  if (value === 'success') return '成功'
  if (value === 'failed' || value === 'error' || value === 'fail') return '失败'
  if (value === 'running') return '运行中'
  return value || '-'
}

function statusTone(status: unknown): BadgeTone {
  const value = String(status || '').toLowerCase()
  if (value === 'success') return 'success'
  if (value === 'failed' || value === 'error' || value === 'fail') return 'danger'
  if (value === 'running') return 'info'
  return 'muted'
}

function eventMetricText(row: RealtimeMonitorEvent) {
  const pairs = [
    ['入口', 'handler_queue_ms'],
    ['首包', 'stream_first_queue_ms'],
    ['账号', 'account_wait_ms'],
    ['上游', 'conversation_stream_ms'],
    ['解析/轮询', 'resolve_ms'],
    ['下载', 'download_ms'],
    ['重试等待', 'retry_wait_ms'],
    ['响应整理', 'response_ms'],
    ['单图链路', 'stream_ms'],
    ['单图总计', 'total_ms'],
  ] as const
  const parts = pairs
    .map(([label, key]) => {
      const value = Number(row[key] || 0)
      return value > 0 ? `${label} ${formatMs(value)}` : ''
    })
    .filter(Boolean)
  return parts.slice(0, 3).join(' / ') || '-'
}

onMounted(() => {
  void loadMonitor(false)
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped>
.monitor-table {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
  text-align: left;
  font-size: 13px;
}

.monitor-table th {
  border-bottom: 1px solid hsl(var(--border));
  background: hsl(var(--muted) / 0.42);
  padding: 10px 14px;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  font-weight: 600;
}

.monitor-table td {
  border-bottom: 1px solid hsl(var(--border) / 0.72);
  padding: 12px 14px;
  vertical-align: middle;
  color: hsl(var(--foreground));
}

.monitor-table tbody tr:hover td {
  background: hsl(var(--muted) / 0.28);
}
</style>
