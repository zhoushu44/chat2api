<template>
  <div class="min-h-screen overflow-x-hidden bg-card/70 text-foreground backdrop-blur">
    <div class="mx-auto flex min-h-screen w-full max-w-5xl min-w-0 items-center justify-center px-4 py-8">
      <PagePanel class="w-full">
        <div class="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p class="ui-subsection-title">服务状态</p>
          </div>
          <p class="text-xs text-muted-foreground">最近更新：{{ updatedAt || '未获取' }}</p>
        </div>

        <div class="grid gap-8 md:grid-cols-2">
          <ServiceStatusCard
            v-for="service in services"
            :key="service.key"
            :service="service"
          />
          <ResultState
            v-if="!services.length"
            title="暂无监控数据"
            description="当前还没有可展示的服务状态。"
          />
        </div>
      </PagePanel>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ResultState } from 'nanocat-ui'
import { PagePanel, ServiceStatusCard } from '@/components/ai'
import { useUptimeStatus } from '@/composables/useUptimeStatus'

const { services, updatedAt } = useUptimeStatus()
</script>
