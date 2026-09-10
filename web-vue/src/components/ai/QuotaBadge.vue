<template>
  <span
    class="inline-flex min-w-[2.75rem] items-center justify-center rounded-full border px-2.5 py-1 font-mono text-xs font-semibold leading-none tabular-nums"
    :class="quotaClass"
  >
    {{ quotaText }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Account } from '@/api/accounts'

const props = defineProps<{
  account: Account
}>()

const quotaValue = computed(() => Number(props.account.quota || 0))

const quotaText = computed(() => {
  if (props.account.image_quota_unknown) return '未知'
  return String(Math.max(0, Math.trunc(quotaValue.value)))
})

const quotaClass = computed(() => {
  if (props.account.image_quota_unknown) {
    return 'border-border bg-muted/40 text-muted-foreground'
  }
  if (quotaValue.value <= 0) {
    return 'border-rose-500/25 bg-rose-500/10 text-rose-700'
  }
  if (quotaValue.value <= 3) {
    return 'border-amber-500/25 bg-amber-500/10 text-amber-700'
  }
  return 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700'
})
</script>
