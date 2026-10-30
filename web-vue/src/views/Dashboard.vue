<template>
  <div class="space-y-5">
    <section class="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-7">
      <StatCard
        v-for="stat in stats"
        :key="stat.label"
        :label="stat.label"
        :value="stat.value"
        :caption="stat.meta"
        :icon="stat.icon"
        :icon-bg="stat.iconBg"
        :icon-color="stat.iconColor"
      />
    </section>

    <!-- 账号产出与存活统计 -->
    <section class="grid grid-cols-1 gap-4">
      <div class="rounded-xl border border-border bg-card p-4">
        <div class="mb-3 flex items-center justify-between">
          <div>
            <h3 class="text-sm font-semibold text-foreground">账号产出与存活</h3>
            <p class="mt-0.5 text-xs text-muted-foreground">
              单号能出多少图、能活多久（含协议恢复后的产出与存活）
            </p>
          </div>
          <button
            type="button"
            class="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
            :disabled="accountStatsLoading"
            @click="loadAccountStats"
          >
            {{ accountStatsLoading ? '刷新中' : '刷新' }}
          </button>
        </div>

        <p v-if="accountStatsError" class="text-xs text-rose-600">统计读取失败，点击刷新重试</p>
        <p v-else-if="!accountStats" class="text-xs text-muted-foreground">加载中…</p>

        <template v-else>
          <div class="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <div
              v-for="item in outputSummary"
              :key="item.label"
              class="rounded-lg border border-border/60 bg-muted/30 px-3 py-2"
            >
              <p class="text-xs text-muted-foreground">{{ item.label }}</p>
              <p class="mt-1 text-base font-semibold text-foreground">{{ item.value }}</p>
              <p class="mt-0.5 text-[11px] text-muted-foreground">{{ item.hint }}</p>
            </div>
          </div>

          <div class="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
            <div
              v-for="item in lifeSummary"
              :key="item.label"
              class="rounded-lg border border-border/60 bg-muted/30 px-3 py-2"
            >
              <p class="text-xs text-muted-foreground">{{ item.label }}</p>
              <p class="mt-1 text-base font-semibold text-foreground">{{ item.value }}</p>
              <p class="mt-0.5 text-[11px] text-muted-foreground">{{ item.hint }}</p>
            </div>
          </div>

          <div class="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div>
              <p class="mb-2 text-xs font-medium text-muted-foreground">批次存活率</p>
              <div v-if="!batchSurvival.length" class="text-xs text-muted-foreground">暂无数据</div>
              <div v-else class="space-y-1.5">
                <div v-for="row in batchSurvival" :key="row.batch" class="flex items-center gap-2">
                  <span class="w-20 shrink-0 text-xs text-muted-foreground">{{ row.batch.slice(5) }}</span>
                  <div class="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                    <div
                      class="h-full rounded-full bg-emerald-500"
                      :style="{ width: `${Math.min(row.survival_pct, 100)}%` }"
                    ></div>
                  </div>
                  <span class="w-24 shrink-0 text-right text-xs text-foreground">
                    {{ row.alive }}/{{ row.total }} · {{ row.survival_pct }}%
                  </span>
                </div>
              </div>
            </div>

            <div>
              <p class="mb-2 text-xs font-medium text-muted-foreground">死亡原因</p>
              <div v-if="!deathReasons.length" class="text-xs text-muted-foreground">暂无数据</div>
              <div v-else class="space-y-1.5">
                <div v-for="row in deathReasons" :key="row.key" class="flex items-center justify-between text-xs">
                  <span class="text-muted-foreground">{{ row.label }}</span>
                  <span class="font-medium text-foreground">{{ row.count }} 个</span>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </section>

    <section class="grid grid-cols-1 gap-4">
      <ChartCard title="模型请求分布">
        <template #actions>
          <TimeRangeTabs v-model="timeRangeHourlyRequests" aria-label="模型请求分布时间范围" />
        </template>
        <div ref="hourlyRequestsChartRef" class="h-72 w-full px-2"></div>
      </ChartCard>
    </section>

    <section class="grid grid-cols-1 gap-4">
      <ChartCard title="调用趋势">
        <template #actions>
          <TimeRangeTabs v-model="timeRangeTrend" aria-label="调用趋势时间范围" />
        </template>
        <div ref="trendChartRef" class="h-56 w-full"></div>
      </ChartCard>
    </section>

    <section class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <ChartCard title="成功率趋势">
        <template #actions>
          <TimeRangeTabs v-model="timeRangeSuccessRate" aria-label="成功率趋势时间范围" />
        </template>
        <div ref="successRateChartRef" class="h-56 w-full"></div>
      </ChartCard>

      <ChartCard title="平均响应时间">
        <template #actions>
          <TimeRangeTabs v-model="timeRangeResponseTime" aria-label="平均响应时间范围" />
        </template>
        <div ref="responseTimeChartRef" class="h-56 w-full"></div>
      </ChartCard>
    </section>

    <section class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <ChartCard title="模型调用占比">
        <template #actions>
          <TimeRangeTabs v-model="timeRangeModel" aria-label="模型调用占比时间范围" />
        </template>
        <div ref="modelChartRef" class="h-56 w-full"></div>
      </ChartCard>

      <ChartCard title="模型使用排行">
        <template #actions>
          <TimeRangeTabs v-model="timeRangeModelRank" aria-label="模型使用排行时间范围" />
        </template>
        <div ref="modelRankChartRef" class="h-56 w-full"></div>
      </ChartCard>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ChartCard, StatCard, TimeRangeTabs } from '@/components/ai'
import { useDashboardPage } from './dashboard/useDashboardPage'

const {
  stats,
  accountStats,
  accountStatsLoading,
  accountStatsError,
  outputSummary,
  lifeSummary,
  batchSurvival,
  deathReasons,
  loadAccountStats,
  timeRangeHourlyRequests,
  timeRangeTrend,
  timeRangeSuccessRate,
  timeRangeModel,
  timeRangeModelRank,
  timeRangeResponseTime,
  hourlyRequestsChartRef,
  trendChartRef,
  successRateChartRef,
  responseTimeChartRef,
  modelChartRef,
  modelRankChartRef,
} = useDashboardPage()
</script>
