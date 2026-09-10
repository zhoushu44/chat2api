<template>
  <div class="gallery-page">
    <PagePanel class="gallery-hero">
      <PanelHeader title="图片管理">
        <template #actions>
          <Button size="sm" variant="outline" :disabled="isLoading" @click="refreshAll">
            {{ isLoading ? '刷新中...' : '刷新' }}
          </Button>
        </template>
      </PanelHeader>
      <MetricStrip
        :items="galleryMetricItems"
        columns-class="grid-cols-1 sm:grid-cols-2 lg:grid-cols-4"
        density="compact"
      />
      <FilterToolbar class="gallery-filter-grid" gap="tight" mobile-mode="stack">
        <Input
          :model-value="searchQuery"
          type="text"
          placeholder="搜索文件名、路径、标签"
          block
          root-class="gallery-filter-search"
          @update:model-value="searchQuery = $event"
        />
        <div class="gallery-filter-field gallery-filter-field--tag">
          <GroupedSelectMenu
            v-model="tagFilter"
            :options="tagOptions"
            placeholder="全部标签"
            selected-indicator="none"
          />
        </div>
        <DateRangeInputs
          v-model:start="startDate"
          v-model:end="endDate"
          class="gallery-date-range"
          input-root-class="gallery-date-input"
        />
      </FilterToolbar>
    </PagePanel>

    <PagePanel flush>
      <div class="gallery-content-toolbar">
        <div class="flex min-w-0 items-center gap-3">
          <Checkbox
            :model-value="allVisibleSelected"
            :disabled="files.length === 0 || isLoading"
            @update:model-value="toggleSelectAllVisible"
          />
          <div class="min-w-0">
            <p class="ui-section-kicker">当前视图</p>
            <p class="mt-1 text-xs text-muted-foreground">{{ paginationSummary }}</p>
          </div>
        </div>

        <ActionRow class="gallery-content-actions" gap="tight" mobile-stretch>
          <Button
            size="xs"
            variant="outline"
            :disabled="selectedCount === 0 || batchBusy"
            @click="handleBatchDownload"
          >
            批量下载
          </Button>
          <Button
            size="xs"
            variant="outline"
            :disabled="selectedCount === 0 || batchBusy"
            @click="handleDeleteSelected"
          >
            批量删除
          </Button>
          <Button
            size="xs"
            variant="ghost"
            :disabled="selectedCount === 0 || batchBusy"
            @click="clearSelection"
          >
            取消选择
          </Button>
        </ActionRow>
      </div>

      <PageLoadingState
        v-if="!hasLoadedOnce && files.length === 0"
        class="gallery-state-block"
        title="正在加载图片"
        description="读取图片记录、标签和分页数据。"
      />

      <StateBlock
        v-else-if="files.length === 0"
        class="gallery-state-block"
        :title="galleryLoadError ? '图片管理加载失败' : '暂无图片'"
        :description="galleryLoadError || '换个筛选条件或刷新后再看。'"
      >
        <template #media>
          <Icon icon="lucide:image-off" class="h-12 w-12 text-muted-foreground/40" />
        </template>
      </StateBlock>

      <div v-else class="space-y-4 p-4 lg:p-5">
        <div class="image-grid">
          <GalleryImageCard
            v-for="file in files"
            :key="file.path"
            :file="file"
            :selected="isSelected(file.path)"
            :previewable="canPreviewFile(file)"
            :copied="copiedFileKey === file.path"
            :image-url="getFileUrl(file.thumbnail_url || file.url)"
            :storage-label="storageLabel(file)"
            :size-label="formatSize(file.size)"
            :dimensions="formatDimensions(file)"
            :time-remaining="file.expires_in_seconds !== null ? formatTimeRemaining(file.expires_in_seconds) : ''"
            @preview="openPreview"
            @select="(item, checked) => toggleSelect(item.path, checked)"
            @image-error="(event, item) => handleImageError(event, item.path)"
            @copy="copyFileLink"
            @edit-tags="openTagEditor"
            @download="downloadFile"
            @delete="handleDelete"
            @tag-click="setTagFilter"
          />
        </div>

        <ListPagination
          v-model:page="currentPage"
          v-model:page-size="pageSize"
          :total-count="totalItems"
          :page-size-options="galleryPageSizeOptions"
          unit="张图片"
          :disabled="isLoading"
        />
      </div>
    </PagePanel>

    <GalleryLightbox
      :file="previewFile"
      :image-url="previewFile ? getFileUrl(previewFile.url) : ''"
      :size-label="previewFile ? formatSize(previewFile.size) : ''"
      :copied="Boolean(previewFile && copiedFileKey === previewFile.path)"
      @close="closePreview"
      @download="downloadFile"
      @copy="copyFileLink"
      @edit-tags="openTagEditor"
    />

    <GalleryTagEditorModal
      :file="tagEditorFile"
      :image-url="tagEditorFile ? getFileUrl(tagEditorFile.thumbnail_url || tagEditorFile.url) : ''"
      :draft="tagDraft"
      :draft-tags="draftTags"
      :all-tags="allTags"
      :is-saving="isTagSaving"
      @close="closeTagEditor"
      @clear="tagDraft = ''"
      @save="saveTagEditor"
      @toggle-tag="toggleDraftTag"
      @update:draft="tagDraft = $event"
    />

    <SelectionBulkBar
      :selected-count="selectedCount"
      :summary-text="`已选择 ${selectedCount} 张图片`"
      density="compact"
    >
      <Button size="xs" variant="outline" :disabled="batchBusy" @click="handleBatchDownload">下载 zip</Button>
      <Button size="xs" variant="outline" :disabled="batchBusy" @click="handleDeleteSelected">删除</Button>
      <Button size="xs" variant="ghost" :disabled="batchBusy" @click="clearSelection">取消</Button>
    </SelectionBulkBar>

    <OperationProgressModal
      :open="operationProgress.open"
      :title="operationProgress.title"
      :subtitle="operationProgress.subtitle"
      :total="operationProgress.total"
      :current="operationProgress.current"
      :status-label="operationProgress.statusLabel"
      :message="operationProgress.message"
      :error="operationProgress.error"
      :busy="operationProgress.busy"
      @close="operationProgress.open = false"
    />

  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import {
  galleryApi,
  resolveGalleryFileUrl,
  type GalleryFile,
  type ImageStorageStats,
} from '@/api/gallery'
import { Button, Checkbox, Input } from 'nanocat-ui'
import { ActionRow, DateRangeInputs, FilterToolbar, GalleryImageCard, GalleryLightbox, GalleryTagEditorModal, ListPagination, MetricStrip, OperationProgressModal, PageLoadingState, PagePanel, PanelHeader, SelectionBulkBar, StateBlock } from '@/components/ai'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'
import { downloadUrlAsFile, saveBlob } from '@/lib/downloads'
import { getNumberPreference, preferenceKeys, setNumberPreference } from '@/lib/preferences'

const toast = useToast()
const confirmDialog = useConfirmDialog()

const files = ref<GalleryFile[]>([])
const totalSize = ref(0)
const totalItems = ref(0)
const lastLoadedAt = ref(0)
const isLoading = ref(true)
const hasLoadedOnce = ref(false)
const galleryLoadError = ref('')
const batchBusy = ref(false)
const isTagSaving = ref(false)
const previewFile = ref<GalleryFile | null>(null)
const tagEditorFile = ref<GalleryFile | null>(null)
const tagDraft = ref('')
const copiedFileKey = ref('')
const tagFilter = ref('all')
const searchQuery = ref('')
const startDate = ref('')
const endDate = ref('')
const galleryPageSizeOptions = [24, 48, 96] as const
const pageSize = ref(getNumberPreference(preferenceKeys.galleryPageSize, 24, { allowed: galleryPageSizeOptions }))
const currentPage = ref(1)
const pageCount = ref(1)
const counts = ref({ all: 0, image: 0, video: 0, music: 0 })
const allTags = ref<string[]>([])
const selectedPaths = ref<Set<string>>(new Set())
const brokenImagePaths = ref<Set<string>>(new Set())
const storageStats = ref<ImageStorageStats | null>(null)
const operationProgress = reactive({
  open: false,
  title: '',
  subtitle: '',
  total: 0,
  current: 0,
  statusLabel: '已处理',
  message: '',
  error: '',
  busy: false,
})

const tagOptions = computed(() => [
  { label: '全部标签', value: 'all' },
  ...allTags.value.map((tag) => ({ label: tag, value: tag })),
])

const paginationSummary = computed(() => `第 ${currentPage.value} / ${pageCount.value} 页，共 ${totalItems.value} 张`)
const selectedCount = computed(() => selectedPaths.value.size)
const allVisibleSelected = computed(() => files.value.length > 0 && files.value.every((file) => selectedPaths.value.has(file.path)))
const draftTags = computed(() => parseTags(tagDraft.value))
let latestLoadToken = 0
let copyResetTimer: number | null = null
let searchTimer: number | null = null

function getFileUrl(url: string) {
  return resolveGalleryFileUrl(url)
}

async function loadGallery() {
  const loadToken = ++latestLoadToken
  isLoading.value = true
  galleryLoadError.value = ''
  try {
    const [data, tags] = await Promise.all([
      galleryApi.getFiles({
        page: Number(pageSize.value) ? currentPage.value : 1,
        page_size: Number(pageSize.value),
        media_type: 'all',
        tag: tagFilter.value,
        search: searchQuery.value,
        start_date: startDate.value,
        end_date: endDate.value,
      }),
      galleryApi.getTags().catch(() => allTags.value),
    ])
    if (loadToken !== latestLoadToken) return
    files.value = data.files
    totalSize.value = data.total_size
    totalItems.value = data.total
    counts.value = data.counts
    currentPage.value = data.page
    pageCount.value = Math.max(1, data.page_count)
    allTags.value = tags || []
    brokenImagePaths.value = new Set()
    lastLoadedAt.value = Date.now()
    pruneSelection()
    void galleryApi.getStorage()
      .then((storage) => {
        if (loadToken === latestLoadToken) storageStats.value = storage || null
      })
      .catch(() => undefined)
  } catch (error: any) {
    if (loadToken !== latestLoadToken) return
    galleryLoadError.value = error?.message || '加载图片管理失败'
    toast.error(galleryLoadError.value, '加载失败')
  } finally {
    if (loadToken === latestLoadToken) {
      isLoading.value = false
      hasLoadedOnce.value = true
    }
  }
}

async function refreshAll() {
  await loadGallery()
}

function resetAndLoad() {
  if (currentPage.value !== 1) {
    currentPage.value = 1
    return
  }
  void loadGallery()
}

async function handleDelete(file: GalleryFile) {
  const confirmed = await confirmDialog.ask({
    title: '确认删除',
    message: `确定要删除 ${file.filename} 吗？此操作不可恢复。`,
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!confirmed) return

  batchBusy.value = true
  operationProgress.open = true
  operationProgress.title = '删除图片'
  operationProgress.subtitle = file.filename
  operationProgress.total = 1
  operationProgress.current = 0
  operationProgress.statusLabel = '已提交'
  operationProgress.message = '正在提交删除请求...'
  operationProgress.error = ''
  operationProgress.busy = true
  try {
    await galleryApi.deleteFile(file.path)
    operationProgress.current = 1
    operationProgress.statusLabel = '已处理'
    operationProgress.message = '删除完成，正在刷新列表...'
    selectedPaths.value.delete(file.path)
    selectedPaths.value = new Set(selectedPaths.value)
    if (previewFile.value?.path === file.path) closePreview()
    if (tagEditorFile.value?.path === file.path) closeTagEditor()
    if (files.value.length === 1 && currentPage.value > 1) {
      currentPage.value -= 1
    } else {
      await loadGallery()
    }
    toast.success(`已删除 ${file.filename}`, '删除成功')
    operationProgress.message = '图片已删除'
  } catch (error: any) {
    operationProgress.error = error?.message || '删除图片失败'
    toast.error(operationProgress.error, '删除失败')
  } finally {
    batchBusy.value = false
    operationProgress.busy = false
  }
}

async function handleDeleteSelected() {
  const paths = Array.from(selectedPaths.value)
  if (!paths.length) return
  const confirmed = await confirmDialog.ask({
    title: '批量删除',
    message: `确定要删除已选择的 ${paths.length} 张图片吗？此操作不可恢复。`,
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!confirmed) return

  batchBusy.value = true
  operationProgress.open = true
  operationProgress.title = '批量删除图片'
  operationProgress.subtitle = `已选择 ${paths.length} 张`
  operationProgress.total = paths.length
  operationProgress.current = 0
  operationProgress.statusLabel = '已提交'
  operationProgress.message = '正在提交批量删除请求...'
  operationProgress.error = ''
  operationProgress.busy = true
  try {
    const result = await galleryApi.deleteFiles(paths)
    operationProgress.current = Number(result.removed || 0)
    operationProgress.statusLabel = '已处理'
    operationProgress.message = '删除完成，正在刷新列表...'
    clearSelection()
    await loadGallery()
    toast.success(`已删除 ${Number(result.removed || 0)} 张图片。`, '删除成功')
    operationProgress.message = `已删除 ${Number(result.removed || 0)} 张图片`
  } catch (error: any) {
    operationProgress.error = error?.message || '批量删除失败'
    toast.error(operationProgress.error, '删除失败')
  } finally {
    batchBusy.value = false
    operationProgress.busy = false
  }
}

async function handleBatchDownload() {
  const paths = Array.from(selectedPaths.value)
  if (!paths.length) return
  batchBusy.value = true
  operationProgress.open = true
  operationProgress.title = '批量下载图片'
  operationProgress.subtitle = `已选择 ${paths.length} 张`
  operationProgress.total = paths.length
  operationProgress.current = 0
  operationProgress.statusLabel = '已提交'
  operationProgress.message = '正在打包 ZIP...'
  operationProgress.error = ''
  operationProgress.busy = true
  try {
    const blob = await galleryApi.downloadZip(paths)
    operationProgress.current = paths.length
    operationProgress.statusLabel = '已处理'
    operationProgress.message = 'ZIP 已生成，正在启动下载...'
    saveBlob(blob, `images_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.zip`)
    toast.success(`已打包 ${paths.length} 张图片。`, '下载已开始')
    operationProgress.message = `已打包 ${paths.length} 张图片`
  } catch (error: any) {
    operationProgress.error = error?.message || '批量下载失败'
    toast.error(operationProgress.error, '下载失败')
  } finally {
    batchBusy.value = false
    operationProgress.busy = false
  }
}

async function downloadFile(file: GalleryFile) {
  try {
    await downloadUrlAsFile(getFileUrl(file.url), file.filename, { localPath: file.path })
    toast.success(`已开始下载 ${file.filename}`)
  } catch (error: any) {
    toast.error(error?.message || '无法读取图片文件', '下载失败')
  }
}

async function copyFileLink(file: GalleryFile | null) {
  if (!file) return
  const url = getFileUrl(file.url)
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url)
    } else {
      const input = document.createElement('input')
      input.value = url
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      document.body.removeChild(input)
    }
    copiedFileKey.value = file.path
    if (copyResetTimer !== null) {
      window.clearTimeout(copyResetTimer)
    }
    copyResetTimer = window.setTimeout(() => {
      copiedFileKey.value = ''
      copyResetTimer = null
    }, 1800)
    toast.success('图片链接已复制。', '复制成功')
  } catch {
    copiedFileKey.value = ''
    toast.error('复制链接失败。', '复制失败')
  }
}

function openPreview(file: GalleryFile) {
  previewFile.value = file
}

function closePreview() {
  previewFile.value = null
}

function openTagEditor(file: GalleryFile) {
  tagEditorFile.value = file
  tagDraft.value = file.tags.join(', ')
}

function closeTagEditor() {
  if (isTagSaving.value) return
  tagEditorFile.value = null
  tagDraft.value = ''
}

async function saveTagEditor() {
  const file = tagEditorFile.value
  if (!file) return
  const tags = draftTags.value
  isTagSaving.value = true
  try {
    const result = await galleryApi.updateTags(file.path, tags)
    applyFileTags(file.path, result.tags || tags)
    allTags.value = await galleryApi.getTags()
    if (tagFilter.value !== 'all' && !(result.tags || tags).includes(tagFilter.value)) {
      await loadGallery()
    }
    toast.success('标签已保存。', '保存成功')
    closeTagEditor()
  } catch (error: any) {
    toast.error(error?.message || '保存标签失败', '保存失败')
  } finally {
    isTagSaving.value = false
  }
}

function applyFileTags(path: string, tags: string[]) {
  files.value = files.value.map((file) => (file.path === path ? { ...file, tags } : file))
  if (previewFile.value?.path === path) previewFile.value = { ...previewFile.value, tags }
  if (tagEditorFile.value?.path === path) tagEditorFile.value = { ...tagEditorFile.value, tags }
}

function parseTags(value: string) {
  return Array.from(new Set(value.split(/[,\s，、]+/).map((tag) => tag.trim()).filter(Boolean)))
}

function toggleDraftTag(tag: string) {
  const next = new Set(draftTags.value)
  if (next.has(tag)) {
    next.delete(tag)
  } else {
    next.add(tag)
  }
  tagDraft.value = Array.from(next).join(', ')
}

function setTagFilter(tag: string) {
  tagFilter.value = tag
  resetAndLoad()
}

function toggleSelect(path: string, checked?: boolean) {
  const next = new Set(selectedPaths.value)
  const shouldSelect = typeof checked === 'boolean' ? checked : !next.has(path)
  if (shouldSelect) {
    next.add(path)
  } else {
    next.delete(path)
  }
  selectedPaths.value = next
}

function toggleSelectAllVisible(checked?: boolean) {
  const next = new Set(selectedPaths.value)
  const shouldSelect = typeof checked === 'boolean' ? checked : !allVisibleSelected.value
  for (const file of files.value) {
    if (shouldSelect) next.add(file.path)
    else next.delete(file.path)
  }
  selectedPaths.value = next
}

function isSelected(path: string) {
  return selectedPaths.value.has(path)
}

function clearSelection() {
  selectedPaths.value = new Set()
}

function pruneSelection() {
  if (selectedPaths.value.size === 0) return
  const loadedPaths = new Set(files.value.map((file) => file.path))
  const next = new Set(Array.from(selectedPaths.value).filter((path) => loadedPaths.has(path)))
  selectedPaths.value = next
}

function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function formatTimeRemaining(seconds: number): string {
  if (seconds <= 0) return '已过期'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}天 ${h}小时`
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

function formatDimensions(file: GalleryFile): string {
  return file.width && file.height ? `${file.width}x${file.height}` : ''
}

function storageLabel(file: GalleryFile): string {
  if (file.storage === 'both') return '本地+云'
  if (file.storage === 'webdav') return '云端'
  return '本地'
}

function canPreviewFile(file: GalleryFile): boolean {
  return file.size > 128 && !brokenImagePaths.value.has(file.path)
}

function handleImageError(event: Event, path: string) {
  const img = event.target as HTMLImageElement
  img.style.opacity = '0'
  brokenImagePaths.value = new Set([...brokenImagePaths.value, path])
}

watch([tagFilter, startDate, endDate, pageSize], () => {
  resetAndLoad()
})
const galleryMetricItems = computed(() => [
  { label: '当前视图', value: totalItems.value, icon: 'lucide:image', iconClass: 'text-cyan-600', iconBgClass: 'bg-transparent' },
  { label: '图库总量', value: storageStats.value ? storageStats.value.image_count : counts.value.all, icon: 'lucide:archive', iconClass: 'text-violet-600', iconBgClass: 'bg-transparent' },
  { label: '当前占用', value: formatSize(totalSize.value), icon: 'lucide:database', iconClass: 'text-emerald-600', iconBgClass: 'bg-transparent' },
  { label: '磁盘剩余', value: storageStats.value ? `${storageStats.value.disk_free_mb} MB` : '-', icon: 'lucide:hard-drive', iconClass: 'text-amber-600', iconBgClass: 'bg-transparent' },
])

watch(pageSize, (value) => {
  setNumberPreference(preferenceKeys.galleryPageSize, value)
})

watch(searchQuery, () => {
  if (searchTimer !== null) {
    window.clearTimeout(searchTimer)
  }
  searchTimer = window.setTimeout(() => {
    searchTimer = null
    resetAndLoad()
  }, 250)
})

watch(currentPage, () => {
  void loadGallery()
})

onMounted(() => {
  void loadGallery()
})

onActivated(() => {
  if (!lastLoadedAt.value || Date.now() - lastLoadedAt.value > 30000) {
    void loadGallery()
  }
})

onBeforeUnmount(() => {
  if (copyResetTimer !== null) {
    window.clearTimeout(copyResetTimer)
    copyResetTimer = null
  }
  if (searchTimer !== null) {
    window.clearTimeout(searchTimer)
    searchTimer = null
  }
})
</script>

<style scoped>
.gallery-page {
  --gallery-radius: 16px;

  display: flex;
  flex-direction: column;
  gap: 16px;
}

.gallery-hero {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 20px;
}

:deep(.gallery-filter-search) {
  flex: 1 1 15rem;
  min-width: min(100%, 14rem);
}

.gallery-filter-field {
  flex: 0 0 9rem;
  min-width: 8rem;
}

.gallery-filter-field--tag {
  flex-basis: 9rem;
}

.gallery-date-range {
  --date-range-flex: 0 1 17rem;
  --date-range-min-width: min(100%, 16rem);
  --date-range-input-min-width: 7.25rem;
}

@media (max-width: 640px) {
  .gallery-hero {
    padding: 14px;
  }

  :deep(.gallery-filter-search),
  .gallery-date-range,
  .gallery-filter-field {
    flex: 1 1 auto;
    min-width: 0;
    width: 100%;
  }
}

.gallery-content-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid hsl(var(--border));
  background: hsl(var(--card));
}

.gallery-state-block {
  min-height: 320px;
  border: 0;
  border-radius: 0;
}

.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 12px;
}

@media (min-width: 1280px) {
  .image-grid {
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  }
}

@media (max-width: 640px) {
  .gallery-content-toolbar {
    align-items: stretch;
    border-radius: var(--gallery-radius);
  }

}

@media (max-width: 420px) {
  .image-grid {
    grid-template-columns: repeat(auto-fill, minmax(136px, 1fr));
  }
}
</style>
