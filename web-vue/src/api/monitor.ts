import apiClient from './client'
import type { UptimeResponse } from '@/types/api'

export type MonitorMetricMap = Record<string, number>

export interface RealtimeMonitorImage {
  index?: number
  total?: number
  stage?: string
  stage_label?: string
  status?: string
  returned_result?: boolean
  returned_message?: boolean
  metrics?: MonitorMetricMap
}

export interface RealtimeMonitorRecord {
  call_id: string
  endpoint?: string
  model?: string
  summary?: string
  role?: string
  key_name?: string
  status?: string
  stage?: string
  stage_label?: string
  started_at?: string
  ended_at?: string
  updated_at?: string
  elapsed_ms?: number
  duration_ms?: number
  metrics?: MonitorMetricMap
  perf?: MonitorMetricMap
  images?: Record<string, RealtimeMonitorImage>
  account_email?: string
  conversation_id?: string
  error?: string
  url_count?: number
}

export interface RealtimeMonitorSummary {
  active: number
  completed: number
  success: number
  failed: number
  success_rate: number
  avg_duration_ms: number
  p95_duration_ms: number
  metric_p95: MonitorMetricMap
  slow_counts: {
    handler_queue: number
    stream_first_queue: number
    account_wait: number
    total_over_120s: number
  }
  bottleneck: {
    key: string
    label: string
    value_ms: number
  }
  by_model: Record<string, number>
  active_by_model: Record<string, number>
}

export interface RealtimeMonitorEvent {
  time: string
  call_id: string
  event: string
  label: string
  model?: string
  index?: number
  total?: number
  status?: string
  [key: string]: unknown
}

export interface RealtimeMonitorResponse {
  updated_at: string
  threadpool: {
    tokens: number
    previous_tokens: number
  }
  window: {
    completed: number
    completed_capacity: number
    events: number
    event_capacity: number
  }
  summary: RealtimeMonitorSummary
  active: RealtimeMonitorRecord[]
  recent: RealtimeMonitorRecord[]
  slow: RealtimeMonitorRecord[]
  events: RealtimeMonitorEvent[]
  metric_labels: Record<string, string>
}

export const monitorApi = {
  uptime(days = 90) {
    return apiClient.get<never, UptimeResponse>('/public/uptime', { params: { days } })
  },
  realtime() {
    return apiClient.get<never, RealtimeMonitorResponse>('/api/monitor/realtime')
  },
}
