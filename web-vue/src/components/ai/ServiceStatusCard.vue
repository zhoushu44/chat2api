<template>
  <div class="monitor-card">
    <div class="monitor-card__header">
      <span class="monitor-card__name">{{ service.name }}</span>
      <span class="monitor-card__badge" :class="service.statusClass">
        {{ service.statusLabel }}
      </span>
    </div>

    <div class="monitor-card__stats">
      <span>可用率 <span class="monitor-card__value">{{ service.uptime }}%</span></span>
      <span>请求 <span class="monitor-card__value">{{ service.total }}</span></span>
      <span>成功 <span class="monitor-card__value">{{ service.success }}</span></span>
    </div>

    <div class="monitor-card__beats">
      <div
        v-for="(beat, index) in service.beats"
        :key="index"
        class="monitor-beat"
        :class="beat.className"
      >
        <span v-if="beat.tooltip" class="monitor-beat__tooltip">{{ beat.tooltip }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  service: {
    name: string
    statusLabel: string
    statusClass: string
    uptime: number
    total: number
    success: number
    beats: Array<{ className: string; tooltip: string | null }>
  }
}>()
</script>

<style scoped>
.monitor-badge--up {
  background: #d1fae5;
  color: #065f46;
}

.monitor-badge--warn {
  background: #fef3c7;
  color: #b45309;
}

.monitor-badge--down {
  background: #fee2e2;
  color: #991b1b;
}

.monitor-badge--unknown {
  background: #f3f4f6;
  color: #6b7280;
}

.monitor-card {
  border-radius: 16px;
  padding: 0;
  background: hsl(var(--card));
  box-shadow: none;
}

.monitor-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.monitor-card__name {
  font-size: 14px;
  font-weight: 600;
  color: hsl(var(--foreground));
}

.monitor-card__badge {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.monitor-card__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
  margin-bottom: 12px;
}

.monitor-card__value {
  margin-left: 4px;
  color: hsl(var(--foreground));
  font-weight: 600;
}

.monitor-card__beats {
  display: flex;
  gap: 2px;
  height: 24px;
  align-items: flex-end;
}

.monitor-beat {
  flex: 1;
  min-width: 4px;
  max-width: 8px;
  border-radius: 2px;
  transition: all 0.2s;
  position: relative;
}

.monitor-beat:hover {
  opacity: 0.8;
  transform: scaleY(1.1);
}

.monitor-beat--up {
  background: #34c759;
  height: 100%;
}

.monitor-beat--warn,
.monitor-beat--slow {
  background: #f5c15b;
  height: 100%;
}

.monitor-beat--down {
  background: #ff3b30;
  height: 100%;
}

.monitor-beat--empty {
  background: #e5e5ea;
  height: 40%;
}

.monitor-beat__tooltip {
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  background: #1d1d1f;
  color: #fff;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 11px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
  margin-bottom: 6px;
  z-index: 10;
}

.monitor-beat__tooltip::after {
  content: "";
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: #1d1d1f;
}

.monitor-beat:hover .monitor-beat__tooltip {
  opacity: 1;
}

@media (max-width: 768px) {
  .monitor-beat {
    min-width: 3px;
    max-width: 6px;
  }
}
</style>
