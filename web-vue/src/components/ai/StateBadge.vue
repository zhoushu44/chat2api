<template>
  <span
    class="state-badge"
    :class="[
      `state-badge--tone-${tone}`,
      `state-badge--size-${size}`,
      `state-badge--shape-${shape}`,
      bordered ? 'state-badge--bordered' : 'state-badge--plain',
    ]"
  >
    <slot />
  </span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  tone?: 'success' | 'danger' | 'warning' | 'info' | 'muted'
  size?: 'xs' | 'sm'
  shape?: 'pill' | 'rounded'
  bordered?: boolean
}>(), {
  tone: 'muted',
  size: 'sm',
  shape: 'pill',
  bordered: true,
})
</script>

<style scoped>
.state-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  font-weight: 500;
  line-height: 1;
}

.state-badge--size-xs {
  min-height: 1.25rem;
  padding: 0.125rem 0.5rem;
  font-size: 11px;
}

.state-badge--size-sm {
  min-height: 1.5rem;
  min-width: 3rem;
  padding: 0.25rem 0.5rem;
  font-size: 12px;
}

.state-badge--shape-pill {
  border-radius: 999px;
}

.state-badge--shape-rounded {
  border-radius: 6px;
}

.state-badge--bordered {
  border: 1px solid transparent;
}

.state-badge--plain {
  border: 1px solid transparent;
}

.state-badge--tone-success {
  background: rgb(34 197 94 / 0.1);
  color: rgb(4 120 87);
}

.state-badge--bordered.state-badge--tone-success {
  border-color: rgb(16 185 129 / 0.4);
}

.state-badge--tone-danger {
  background: rgb(244 63 94 / 0.1);
  color: rgb(190 18 60);
}

.state-badge--bordered.state-badge--tone-danger {
  border-color: rgb(244 63 94 / 0.36);
}

.state-badge--tone-warning {
  background: rgb(245 158 11 / 0.1);
  color: rgb(180 83 9);
}

.state-badge--bordered.state-badge--tone-warning {
  border-color: rgb(245 158 11 / 0.36);
}

.state-badge--tone-info {
  background: rgb(14 165 233 / 0.1);
  color: rgb(2 132 199);
}

.state-badge--bordered.state-badge--tone-info {
  border-color: rgb(14 165 233 / 0.34);
}

.state-badge--tone-muted {
  background: hsl(var(--muted) / 0.65);
  color: hsl(var(--muted-foreground));
}

.state-badge--bordered.state-badge--tone-muted {
  border-color: hsl(var(--border));
}
</style>
