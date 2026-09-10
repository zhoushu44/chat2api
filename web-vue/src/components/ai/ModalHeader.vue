<template>
  <div
    class="modal-header"
    :class="[
      bordered ? 'modal-header--bordered' : '',
      compact ? 'modal-header--compact' : '',
      flush ? 'modal-header--flush' : '',
    ]"
  >
    <div class="modal-header__copy">
      <component :is="headingTag" v-if="title" :class="titleClass">{{ title }}</component>
      <p v-if="subtitle" class="modal-header__subtitle">{{ subtitle }}</p>
      <slot name="copy" />
    </div>
    <div v-if="showClose || $slots.actions" class="modal-header__actions">
      <slot name="actions" />
      <Button
        v-if="showClose"
        size="xs"
        variant="outline"
        root-class="min-w-14 justify-center text-muted-foreground"
        :disabled="closeDisabled"
        @click="$emit('close')"
      >
        {{ closeText }}
      </Button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Button } from 'nanocat-ui'

withDefaults(defineProps<{
  title?: string
  subtitle?: string
  titleClass?: string
  headingTag?: 'h3' | 'h4' | 'p'
  closeText?: string
  closeDisabled?: boolean
  showClose?: boolean
  bordered?: boolean
  compact?: boolean
  flush?: boolean
}>(), {
  title: '',
  subtitle: '',
  titleClass: 'ui-section-title',
  headingTag: 'p',
  closeText: '关闭',
  closeDisabled: false,
  showClose: true,
  bordered: true,
  compact: false,
  flush: false,
})

defineEmits<{
  close: []
}>()
</script>

<style scoped>
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
}

.modal-header--compact {
  padding-block: 12px;
}

.modal-header--flush {
  padding: 0;
}

.modal-header--bordered {
  border-bottom: 1px solid hsl(var(--border));
}

.modal-header__copy {
  min-width: 0;
}

.modal-header__subtitle {
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.modal-header__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

@media (max-width: 640px) {
  .modal-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .modal-header__actions {
    width: 100%;
  }
}
</style>
