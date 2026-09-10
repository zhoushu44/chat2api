<template>
  <NanocatMetaChip
    :tone="resolvedTone"
    :variant="variant"
    :size="resolvedSize"
    :chip-class="resolvedChipClass"
  >
    <slot />
  </NanocatMetaChip>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { MetaChip as NanocatMetaChip } from 'nanocat-ui'

const props = withDefaults(defineProps<{
  tone?: 'default' | 'muted' | 'success' | 'warning' | 'danger' | 'info'
  variant?: 'soft' | 'outline' | 'solid'
  size?: 'xs' | 'sm' | 'md'
  strong?: boolean
  chipClass?: string
}>(), {
  tone: 'default',
  variant: 'soft',
  size: 'sm',
  strong: false,
  chipClass: '',
})

const resolvedTone = computed(() => {
  if (props.tone === 'success') return 'success'
  if (props.tone === 'warning') return 'warning'
  if (props.tone === 'danger') return 'error'
  if (props.tone === 'info') return 'info'
  return 'neutral'
})

const resolvedSize = computed(() => props.size === 'md' ? 'md' : 'sm')

const resolvedChipClass = computed(() => {
  const classes = ['ai-meta-chip']
  if (props.size === 'xs') classes.push('min-h-5 px-2 py-0.5 text-[11px]')
  if (props.tone === 'muted') classes.push('text-muted-foreground')
  if (props.strong) classes.push('font-semibold')
  if (props.chipClass) classes.push(props.chipClass)
  return classes.join(' ')
})
</script>
