<template>
  <div class="ui-surface">
    <button
      type="button"
      class="flex w-full flex-wrap items-center gap-2 rounded-2xl bg-secondary/40 px-4 py-3 text-left text-xs transition hover:bg-secondary/60"
      @click="$emit('toggle')"
    >
      <span :class="statusBadgeClass">{{ statusLabel }}</span>
      <span class="text-muted-foreground">req_{{ requestId }}</span>
      <span
        v-if="accountText"
        class="text-xs font-semibold"
        :style="accountStyle"
      >
        {{ accountText }}
      </span>
      <span
        v-for="meta in metaTexts"
        :key="meta"
        class="text-muted-foreground"
      >
        {{ meta }}
      </span>
      <span v-if="hintText" class="text-[10px] text-muted-foreground">{{ hintText }}</span>
      <span class="text-muted-foreground">{{ countText }}</span>
      <span class="ml-auto text-muted-foreground transition-transform" :class="{ 'rotate-90': !collapsed }">▸</span>
    </button>

    <div v-if="!collapsed" class="space-y-3 px-4 py-3">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    statusLabel: string
    statusBadgeClass: string
    requestId: string
    collapsed: boolean
    countText: string
    metaTexts?: string[]
    hintText?: string
    accountText?: string
    accountStyle?: Record<string, string>
  }>(),
  {
    metaTexts: () => [],
    hintText: '',
    accountText: '',
    accountStyle: () => ({}),
  }
)

defineEmits<{
  (e: 'toggle'): void
}>()
</script>
