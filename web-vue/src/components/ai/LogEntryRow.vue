<template>
  <div class="cv-auto flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-xs">
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-muted-foreground">{{ time }}</span>
      <span v-if="badgeText" :class="badgeClass">{{ badgeText }}</span>
      <span
        v-for="tag in tags"
        :key="tag.key ?? tag.text"
        :class="tag.class"
        :style="tag.style"
      >
        {{ tag.text }}
      </span>
      <span
        v-if="accountText"
        class="text-[11px] font-semibold"
        :style="accountStyle"
      >
        {{ accountText }}
      </span>
    </div>
    <div class="w-full break-words whitespace-pre-wrap text-foreground md:w-auto md:flex-1">
      {{ text }}
    </div>
  </div>
</template>

<script setup lang="ts">
type RowTag = {
  text: string
  class?: string
  key?: string
  style?: Record<string, string>
}

withDefaults(
  defineProps<{
    time: string
    text: string
    badgeText?: string
    badgeClass?: string
    tags?: RowTag[]
    accountText?: string
    accountStyle?: Record<string, string>
  }>(),
  {
    badgeText: '',
    badgeClass: '',
    tags: () => [],
    accountText: '',
    accountStyle: () => ({}),
  }
)
</script>
