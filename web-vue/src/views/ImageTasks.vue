<template>
  <div class="image-workspace">
    <aside class="image-history-panel">
      <div class="image-history-actions">
        <Button size="sm" variant="primary" root-class="flex-1 justify-center rounded-xl" @click="createConversation">
          <Icon icon="lucide:message-square-plus" class="h-4 w-4" />
          新建对话
        </Button>
        <Button
          size="sm"
          variant="outline"
          icon-only
          root-class="rounded-xl"
          :disabled="!conversations.length && !tasks.length"
          title="清空历史记录"
          @click="confirmClearLocalHistory"
        >
          <Icon icon="lucide:trash-2" class="h-4 w-4" />
        </Button>
      </div>

      <div class="image-history-list">
        <PageLoadingState
          v-if="isFetching && !hasLoadedOnce"
          compact
          title="正在读取历史"
          description="加载本地对话和图片任务。"
        />
        <div
          v-for="conversation in conversations"
          :key="conversation.id"
          class="image-history-item"
          :class="{ 'is-active': conversation.id === activeConversationId }"
        >
          <button type="button" class="image-history-main" @click="selectConversation(conversation.id)">
            <span class="image-history-title">{{ conversation.title || '未命名对话' }}</span>
            <span class="image-history-meta">
              {{ conversation.turns.length }} 轮 · {{ formatShortTime(conversation.updatedAt) }}
            </span>
            <span v-if="conversationRunningCount(conversation)" class="image-history-running">
              处理中 {{ conversationRunningCount(conversation) }}
            </span>
          </button>
          <button
            type="button"
            class="image-history-delete"
            title="删除对话"
            aria-label="删除对话"
            @click.stop="deleteConversation(conversation)"
          >
            <Icon icon="lucide:trash-2" class="h-3.5 w-3.5" />
          </button>
        </div>
        <div v-if="!conversations.length && hasLoadedOnce" class="image-history-empty">
          输入提示词后会在这里显示对话历史。
        </div>
      </div>
    </aside>

    <section class="image-chat-panel">
      <div class="image-mobile-actions">
        <Button size="sm" variant="outline" root-class="rounded-xl" @click="isMobileHistoryOpen = true">
          <Icon icon="lucide:history" class="h-4 w-4" />
          历史记录 {{ conversations.length ? `(${conversations.length})` : '' }}
        </Button>
        <Button size="sm" variant="primary" root-class="rounded-xl" @click="createConversation">
          <Icon icon="lucide:plus" class="h-4 w-4" />
          新建
        </Button>
      </div>

      <div ref="resultsViewportRef" class="image-chat-scroll" @scroll="handleResultsScroll">
        <div v-if="!selectedConversation || selectedConversation.turns.length === 0" class="image-chat-empty">
          <h1>Turn ideas into images</h1>
          <p>在同一窗口里保留本地历史与任务状态，并从已有结果图继续发起新的无状态编辑。</p>
        </div>

        <div v-else class="image-turns">
          <article v-for="(turn, turnIndex) in selectedConversation.turns" :key="turn.id" class="image-turn">
            <div class="image-user-row">
              <div class="image-user-bubble">
                <div class="image-turn-meta">
                  <span>第 {{ turnIndex + 1 }} 轮</span>
                  <span>{{ turn.mode === 'edit' ? '编辑图' : '文生图' }}</span>
                  <span>{{ taskStatusLabel(taskForTurn(turn)?.status) }}</span>
                  <span>{{ formatShortTime(turn.createdAt) }}</span>
                </div>
                <p class="image-user-prompt">{{ turn.prompt }}</p>
                <div class="image-user-actions">
                  <button type="button" @click="retryTurn(turn)">
                    回填提示词
                  </button>
                  <button
                    type="button"
                    class="is-danger"
                    aria-label="删除本轮记录"
                    @click="selectedConversation && deleteTurn(selectedConversation.id, turn.id)"
                  >
                    <Icon icon="lucide:trash-2" class="h-3 w-3" />
                  </button>
                </div>
              </div>
            </div>

            <div class="image-assistant-row">
              <div v-if="turn.sourceImages.length" class="image-turn-references">
                <div class="image-reference-title">本轮参考图</div>
                <div class="image-source-strip">
                  <button
                    v-for="source in turn.sourceImages"
                    :key="source.id"
                    type="button"
                    class="image-source-thumb"
                    :title="source.name"
                    @click="openPreview(sourcePreviewUrl(source), source.name)"
                  >
                    <img v-if="sourcePreviewUrl(source)" :src="sourcePreviewUrl(source)" :alt="source.name" />
                    <Icon v-else icon="lucide:image" class="h-5 w-5" />
                  </button>
                </div>
              </div>

              <div
                v-if="!taskForTurn(turn)"
                class="image-result-card is-loading"
                :style="resultPreviewStyle(turn.size)"
              >
                <Icon icon="lucide:loader-circle" class="h-5 w-5 animate-spin" />
                <p>任务已创建，等待刷新状态。</p>
              </div>

              <template v-else>
                <div
                  v-if="taskForTurn(turn)?.status === 'queued' || taskForTurn(turn)?.status === 'running'"
                  class="image-result-card is-loading"
                  :style="resultPreviewStyle(turn.size)"
                >
                  <span class="image-loading-icon">
                    <Icon
                      :icon="taskForTurn(turn)?.status === 'queued' ? 'lucide:clock-3' : 'lucide:loader-circle'"
                      class="h-5 w-5"
                      :class="{ 'animate-spin': taskForTurn(turn)?.status === 'running' }"
                    />
                  </span>
                  <div>
                    <p>{{ taskForTurn(turn)?.status === 'queued' ? '已加入等待队列' : '正在处理图片' }}</p>
                    <span>{{ stageLabel(taskForTurn(turn)?.stage || taskForTurn(turn)?.progress || taskForTurn(turn)?.status) }} · {{ formatDuration(taskForTurn(turn)?.duration_ms, taskForTurn(turn)?.elapsed_secs) }}</span>
                  </div>
                </div>

                <div
                  v-else-if="taskForTurn(turn)?.status === 'error'"
                  class="image-result-card is-error"
                  :style="resultPreviewStyle(turn.size)"
                >
                  <p class="font-medium">处理失败</p>
                  <p>{{ primaryMessage(taskForTurn(turn)!) || '上游没有返回可用图片。' }}</p>
                  <div class="image-result-actions">
                    <Button
                      v-if="taskForTurn(turn)?.can_resume_poll"
                      size="xs"
                      variant="outline"
                      :disabled="resumingTaskId === turn.taskId"
                      @click="resumeTask(taskForTurn(turn)!)"
                    >
                      <Icon icon="lucide:rotate-cw" class="h-3.5 w-3.5" />
                      {{ resumingTaskId === turn.taskId ? '恢复中' : '继续等待' }}
                    </Button>
                    <Button size="xs" variant="outline" @click="retryTurn(turn)">
                      <Icon icon="lucide:refresh-cw" class="h-3.5 w-3.5" />
                      重试
                    </Button>
                    <Button size="xs" variant="outline" @click="copyTaskError(taskForTurn(turn)!)">
                      <Icon icon="lucide:copy" class="h-3.5 w-3.5" />
                      复制诊断
                    </Button>
                  </div>
                </div>

                <div v-else class="image-result-block">
                  <div class="image-result-grid" :class="{ 'is-single': (taskForTurn(turn)?.data || []).length <= 1 }">
                    <div
                      v-for="(asset, index) in taskForTurn(turn)?.data || []"
                      :key="`${turn.id}-${index}`"
                      class="image-result-item"
                    >
                      <button
                        type="button"
                        class="image-result-media"
                        :class="{ 'has-image': Boolean(assetUrl(asset)) }"
                        @click="openPreview(assetUrl(asset), `结果 ${index + 1}`, String(asset.path || ''))"
                      >
                        <img v-if="assetUrl(asset)" :src="assetUrl(asset)" :alt="`结果 ${index + 1}`" loading="lazy" />
                        <span v-else>无图片 URL</span>
                      </button>
                      <div class="image-result-footer">
                        <div class="image-result-caption">
                          <span>结果 {{ index + 1 }}</span>
                          <span v-if="taskForTurn(turn)?.duration_ms">{{ formatDuration(taskForTurn(turn)?.duration_ms) }}</span>
                        </div>
                        <div class="image-result-actions">
                          <Button size="xs" variant="outline" root-class="rounded-full" @click="seedAssetForEdit(asset, index)">
                            <Icon icon="lucide:sparkles" class="h-3.5 w-3.5" />
                            加入编辑
                          </Button>
                          <button type="button" class="image-download-btn" @click="downloadAsset(asset, turn, index)">
                            <Icon icon="lucide:download" class="h-3.5 w-3.5" />
                            下载
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div class="image-result-tail-actions">
                    <button type="button" @click="retryTurn(turn)">
                      回填提示词
                    </button>
                  </div>
                </div>
              </template>
            </div>
          </article>
        </div>
      </div>

      <button
        v-if="showScrollLatest"
        type="button"
        class="image-scroll-latest"
        aria-label="滚动到最新消息"
        title="滚动到最新消息"
        @click="scrollToBottom"
      >
        <Icon icon="lucide:arrow-down" class="h-5 w-5" />
      </button>

      <div class="image-composer-shell">
        <input
          ref="fileInputRef"
          type="file"
          accept="image/*"
          multiple
          class="hidden"
          @change="handleFileChange"
        />

        <div v-if="composerSources.length" class="image-reference-row">
          <div v-for="(source, index) in composerSources" :key="source.id" class="image-reference-chip">
            <button type="button" class="image-reference-preview" :title="source.name" @click="openPreview(sourcePreviewUrl(source), source.name)">
              <img v-if="sourcePreviewUrl(source)" :src="sourcePreviewUrl(source)" :alt="source.name" />
              <Icon v-else icon="lucide:image" class="h-5 w-5" />
            </button>
            <button type="button" class="image-reference-remove" :aria-label="`移除 ${source.name}`" @click.stop="removeComposerSource(index)">
              <Icon icon="lucide:x" class="h-3 w-3" />
            </button>
          </div>
        </div>

        <div
          class="image-composer"
          :class="{ 'is-dragging': isDraggingImage }"
          @dragenter.prevent="isDraggingImage = true"
          @dragover.prevent="isDraggingImage = true"
          @dragleave="handleDragLeave"
          @drop.prevent="handleDrop"
          @click="textareaRef?.focus()"
        >
          <textarea
            ref="textareaRef"
            v-model="form.prompt"
            class="image-prompt-input"
            :placeholder="composerSources.length ? '描述你想如何修改参考图' : '输入你想生成的画面，也可以粘贴或拖入参考图'"
            rows="3"
            @paste="handlePaste"
            @keydown="handlePromptKeydown"
          ></textarea>

          <div class="image-composer-footer" @click.stop>
            <div class="image-composer-tools">
              <Button size="sm" variant="outline" root-class="rounded-full" :disabled="isSubmitting" @click="openFilePicker">
                <Icon icon="lucide:image-plus" class="h-4 w-4" />
                {{ uploadButtonLabel }}
              </Button>
              <span v-if="composerSources.length" class="image-reference-count">
                {{ referenceCountLabel }}
              </span>
              <div class="image-size-menu-wrap">
                <button ref="sizeMenuButtonRef" type="button" class="image-size-trigger" @click.stop="toggleSizeMenu">
                  <Icon icon="lucide:sliders-horizontal" class="h-4 w-4" />
                  <span>{{ sizeSummaryLabel }}</span>
                  <Icon icon="lucide:chevron-down" class="h-3.5 w-3.5" />
                </button>
                <div v-if="isSizeMenuOpen" class="image-size-popover" :style="sizeMenuStyle" @click.stop>
                  <div class="image-size-section">
                    <div class="image-size-label">模型</div>
                    <div class="image-size-select">
                      <GroupedSelectMenu v-model="form.model" :options="modelSelectOptions" selected-indicator="none" block />
                    </div>
                  </div>
                  <div class="image-size-section">
                    <div class="image-size-label">质量</div>
                    <div class="image-choice-grid is-quality">
                      <button
                        v-for="option in IMAGE_QUALITY_OPTIONS"
                        :key="option.value"
                        type="button"
                        class="image-choice-button"
                        :class="{ 'is-active': form.quality === option.value }"
                        @click="form.quality = option.value"
                      >
                        {{ option.label }}
                      </button>
                    </div>
                  </div>
                  <div class="image-size-section">
                    <div class="image-size-label">数量</div>
                    <div class="image-choice-grid is-count">
                      <button
                        v-for="option in IMAGE_COUNT_OPTIONS"
                        :key="option.value"
                        type="button"
                        class="image-choice-button"
                        :class="{ 'is-active': form.n === option.value }"
                        @click="form.n = option.value"
                      >
                        {{ option.label }}
                      </button>
                    </div>
                  </div>
                  <div class="image-size-section">
                    <div class="image-size-label">比例</div>
                    <div class="image-choice-grid is-ratio">
                      <button
                        v-for="option in availableRatioOptions"
                        :key="option.value"
                        type="button"
                        class="image-choice-button"
                        :class="{ 'is-active': selectedSizeRatio === option.value }"
                        @click="selectImageRatio(option.value)"
                      >
                        {{ option.label }}
                      </button>
                    </div>
                  </div>
                  <div class="image-size-section">
                    <div class="image-size-label">分辨率</div>
                    <div class="image-choice-grid is-resolution">
                      <button
                        v-for="option in availableResolutionOptions"
                        :key="option.value"
                        type="button"
                        class="image-choice-button"
                        :class="{ 'is-active': selectedSizeResolution === option.value }"
                        @click="selectImageResolution(option.value)"
                      >
                        {{ option.label }}
                      </button>
                    </div>
                    <p class="image-size-current">{{ selectedSizeDetailLabel }}</p>
                    <p v-if="isHighRiskImageSize" class="image-size-warning">
                      4K 走 Codex 图片工具，上游更容易返回 server_error；失败时建议先降到 1K 或 2K。
                    </p>
                  </div>
                </div>
              </div>
              <Button
                v-if="referencePreviews.length || imageUrlsInput"
                size="sm"
                variant="outline"
                root-class="rounded-full"
                :disabled="isSubmitting"
                @click="clearSources"
              >
                <Icon icon="lucide:x" class="h-4 w-4" />
                清空参考
              </Button>
              <span v-if="activeTaskCount" class="image-active-chip">
                <Icon icon="lucide:loader-circle" class="h-3.5 w-3.5 animate-spin" />
                {{ activeTaskCount }} 个任务处理中
              </span>
              <span class="image-quota-chip" :class="{ 'is-empty': quotaSummary && !quotaSummary.available }">
                <Icon :icon="quotaSummary?.available ? 'lucide:image' : 'lucide:circle-alert'" class="h-3.5 w-3.5" />
                {{ quotaFooterLabel }}
              </span>
            </div>

            <button
              type="button"
              class="image-send-button"
              :disabled="isSubmitting || !form.prompt.trim()"
              :aria-label="composerSources.length ? '提交图生图任务' : '提交文生图任务'"
              @click="submitTask"
            >
              <Icon v-if="isSubmitting" icon="lucide:loader-circle" class="h-4 w-4 animate-spin" />
              <Icon v-else icon="lucide:arrow-up" class="h-4 w-4" />
            </button>
          </div>

          <div v-if="isDraggingImage" class="image-drop-overlay">
            <Icon icon="lucide:image-plus" class="h-5 w-5" />
            松开以上传参考图
          </div>
        </div>
      </div>
    </section>

    <Teleport to="body">
      <div v-if="isMobileHistoryOpen" class="image-mobile-history-backdrop" @click.self="isMobileHistoryOpen = false">
        <div class="image-mobile-history">
          <div class="image-mobile-history-header">
            <p>历史记录</p>
            <button type="button" @click="isMobileHistoryOpen = false">
              <Icon icon="lucide:x" class="h-5 w-5" />
            </button>
          </div>
          <div class="image-history-list">
            <PageLoadingState
              v-if="isFetching && !hasLoadedOnce"
              compact
              title="正在读取历史"
              description="加载本地对话和图片任务。"
            />
            <div
              v-for="conversation in conversations"
              :key="conversation.id"
              class="image-history-item"
              :class="{ 'is-active': conversation.id === activeConversationId }"
            >
              <button type="button" class="image-history-main" @click="selectConversation(conversation.id); isMobileHistoryOpen = false">
                <span class="image-history-title">{{ conversation.title || '未命名对话' }}</span>
                <span class="image-history-meta">
                  {{ conversation.turns.length }} 轮 · {{ formatShortTime(conversation.updatedAt) }}
                </span>
              </button>
              <button
                type="button"
                class="image-history-delete"
                title="删除对话"
                aria-label="删除对话"
                @click.stop="deleteConversation(conversation)"
              >
                <Icon icon="lucide:trash-2" class="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="previewImage" class="image-lightbox" @click.self="closePreview">
        <button type="button" class="image-lightbox-close" @click="closePreview">
          <Icon icon="lucide:x" class="h-5 w-5" />
        </button>
        <img :src="previewImage.src" :alt="previewImage.name" />
        <div class="image-lightbox-actions">
          <span>{{ previewImage.name }}</span>
          <button type="button" @click="copyText(previewImage.src)">
            <Icon icon="lucide:copy" class="h-3.5 w-3.5" />
            复制链接
          </button>
          <button type="button" @click="downloadPreviewImage">
            <Icon icon="lucide:download" class="h-3.5 w-3.5" />
            下载
          </button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { Icon } from '@iconify/vue'
import { Button } from 'nanocat-ui'
import { PageLoadingState } from '@/components/ai'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import {
  DEFAULT_IMAGE_MODEL,
  DEFAULT_IMAGE_QUALITY,
  DEFAULT_IMAGE_SIZE,
  IMAGE_COUNT_OPTIONS,
  IMAGE_QUALITY_OPTIONS,
  imageAssetUrl,
  imageTasksApi,
  isImageSizeSupportedByModel,
  isImageTaskTerminal,
  normalizeImageCount,
  parseImageSize,
  resolveImageSizePresets,
  taskPrimaryMessage,
  type ImageQuotaSummary,
  type ImageSizePreset,
  type ImageSizeResolution,
  type ImageTask,
  type ImageTaskAsset,
  type ImageTaskMode,
  type ImageTaskStatus,
} from '@/api/imageTasks'
import { useSettingsStore } from '@/stores/settings'
import { useModelCatalog } from '@/composables/useModelCatalog'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'
import {
  getJsonPreference,
  getStringPreference,
  preferenceKeys,
  removePreference,
  setJsonPreference,
  setStringPreference,
} from '@/lib/preferences'
import { downloadUrlAsFile } from '@/lib/downloads'
import { dataUrlToFile } from '@/lib/files'

type SubmitMode = 'generate' | 'edit'

interface ReferencePreview {
  id: string
  name: string
  type: string
  size: number
  dataUrl?: string
  url?: string
}

interface ImageConversationTurn {
  id: string
  taskId: string
  prompt: string
  mode: ImageTaskMode
  model: string
  n: number
  size: string
  quality: string
  sourceImages: ReferencePreview[]
  createdAt: string
}

interface ImageConversation {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  turns: ImageConversationTurn[]
}

const settingsStore = useSettingsStore()
const { settings } = storeToRefs(settingsStore)
const {
  imageModels,
  loadModelCatalog,
} = useModelCatalog(() => settings.value)
const toast = useToast()
const confirmDialog = useConfirmDialog()

const form = reactive({
  prompt: '',
  model: DEFAULT_IMAGE_MODEL,
  n: 1,
  size: DEFAULT_IMAGE_SIZE,
  quality: DEFAULT_IMAGE_QUALITY,
})

const IMAGE_RATIO_OPTIONS = [
  { label: '自动', value: 'auto' },
  { label: '1:1', value: '1:1' },
  { label: '2:3', value: '2:3' },
  { label: '3:2', value: '3:2' },
  { label: '3:4', value: '3:4' },
  { label: '4:3', value: '4:3' },
  { label: '16:9', value: '16:9' },
  { label: '9:16', value: '9:16' },
]

const IMAGE_RESOLUTION_OPTIONS: Array<{ label: string; value: ImageSizeResolution }> = [
  { label: '自动', value: 'auto' },
  { label: '1K', value: '1K' },
  { label: '2K', value: '2K' },
  { label: '4K', value: '4K' },
]

const AUTO_IMAGE_SIZE_PRESET: ImageSizePreset = {
  label: '自动',
  value: DEFAULT_IMAGE_SIZE,
  ratio: 'auto',
  resolution: 'auto',
}
const imageUrlsInput = ref('')
const selectedFiles = ref<File[]>([])
const referencePreviews = ref<ReferencePreview[]>([])
const fileInputRef = ref<HTMLInputElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const resultsViewportRef = ref<HTMLElement | null>(null)
const sizeMenuButtonRef = ref<HTMLButtonElement | null>(null)

const tasks = ref<ImageTask[]>([])
const conversations = ref<ImageConversation[]>([])
const activeConversationId = ref('')
const isSubmitting = ref(false)
const isFetching = ref(false)
const hasLoadedOnce = ref(false)
const autoPoll = ref(true)
const resumingTaskId = ref('')
const isDraggingImage = ref(false)
const isMobileHistoryOpen = ref(false)
const isSizeMenuOpen = ref(false)
const showScrollLatest = ref(false)
const sizeMenuPosition = reactive({ top: 0, left: 0 })
const previewImage = ref<{ src: string; name: string; localPath?: string } | null>(null)
const quotaSummary = ref<ImageQuotaSummary | null>(null)
const isQuotaLoading = ref(false)

let pollTimer: number | null = null

const parsedImageUrls = computed(() => parseImageUrls())

const composerSources = computed<ReferencePreview[]>(() => [
  ...referencePreviews.value,
  ...parsedImageUrls.value.map((url, index) => ({
    id: `url-${index}-${url}`,
    name: url.replace(/^https?:\/\//, '').slice(0, 48) || `参考图 ${index + 1}`,
    type: 'remote',
    size: 0,
    url,
  })),
])

const modelSelectOptions = computed(() => {
  return imageModels.value.map((model) => ({ label: model, value: model }))
})
const availableSizePresets = computed(() => resolveImageSizePresets(form.model))
const currentSizePreset = computed<ImageSizePreset>(() => {
  return availableSizePresets.value.find((preset) => preset.value === form.size)
    || availableSizePresets.value.find((preset) => preset.value === DEFAULT_IMAGE_SIZE)
    || availableSizePresets.value[0]
    || AUTO_IMAGE_SIZE_PRESET
})
const selectedSizeRatio = computed(() => currentSizePreset.value?.ratio || 'auto')
const selectedSizeResolution = computed<ImageSizeResolution>(() => currentSizePreset.value?.resolution || 'auto')
const availableRatioOptions = computed(() => {
  const ratios = new Set(availableSizePresets.value.map((preset) => preset.ratio))
  return IMAGE_RATIO_OPTIONS.filter((option) => ratios.has(option.value))
})
const availableResolutionOptions = computed(() => {
  const resolutions = new Set(availableSizePresets.value.map((preset) => preset.resolution))
  return IMAGE_RESOLUTION_OPTIONS.filter((option) => resolutions.has(option.value))
})

const selectedConversation = computed(() => conversations.value.find((item) => item.id === activeConversationId.value) || null)
const taskById = computed(() => new Map(tasks.value.map((task) => [task.id, task])))
const unfinishedTasks = computed(() => tasks.value.filter((task) => !isImageTaskTerminal(task)))
const activeTaskCount = computed(() => unfinishedTasks.value.length)

const pollingLabel = computed(() => {
  if (!autoPoll.value) return '轮询暂停'
  if (!unfinishedTasks.value.length) return '没有运行中的任务'
  return `${unfinishedTasks.value.length} 个任务轮询中`
})

const sizeSummaryLabel = computed(() => {
  const model = form.model || DEFAULT_IMAGE_MODEL
  const quality = optionLabel(IMAGE_QUALITY_OPTIONS, form.quality)
  const size = selectedSizeSummaryLabel.value
  const count = IMAGE_COUNT_OPTIONS.find((option) => option.value === form.n)?.label || `${normalizeImageCount(form.n)} 张`
  return `${model} · ${quality} · ${size} · ${count}`
})

const selectedSizeSummaryLabel = computed(() => {
  const preset = currentSizePreset.value
  if (!preset || preset.value === DEFAULT_IMAGE_SIZE) return '自动尺寸'
  return `${preset.ratio} · ${preset.resolution}`
})

const selectedSizeDetailLabel = computed(() => {
  const preset = currentSizePreset.value
  if (!preset || preset.value === DEFAULT_IMAGE_SIZE) return '尺寸由模型自动判断'
  if (!preset.width || !preset.height) return preset.label
  return `${preset.ratio} · ${preset.resolution} · ${preset.width}x${preset.height}`
})

const isHighRiskImageSize = computed(() => currentSizePreset.value?.resolution === '4K')

const quotaFooterLabel = computed(() => {
  if (!quotaSummary.value) return isQuotaLoading.value ? '额度读取中' : '额度读取失败'
  const total = Math.max(0, Number(quotaSummary.value.total_quota || 0))
  const unlimited = Math.max(0, Number(quotaSummary.value.unlimited_quota_count || 0))
  const unknown = Math.max(0, Number(quotaSummary.value.unknown_quota_count || 0))
  const parts: string[] = []
  if (total > 0) parts.push(`剩余 ${total} 张`)
  if (unlimited > 0) parts.push(`无限额度账号 ${unlimited} 个`)
  if (unknown > 0) parts.push(`未知额度账号 ${unknown} 个`)
  if (!parts.length) parts.push(quotaSummary.value.available ? '额度可用' : '剩余 0 张')
  return parts.join(' · ')
})

const referenceCountLabel = computed(() => {
  const count = composerSources.value.length
  return count > 1 ? `${count} 张参考图` : '1 张参考图'
})

const uploadButtonLabel = computed(() => {
  return composerSources.value.length ? '继续添加' : '上传参考图'
})

const sizeMenuStyle = computed(() => ({
  top: `${sizeMenuPosition.top}px`,
  left: `${sizeMenuPosition.left}px`,
}))

function optionLabel(options: Array<{ label: string; value: string }>, value: string) {
  return options.find((option) => option.value === value)?.label || value || '自动'
}

function ensureAvailableImageModel() {
  const firstModel = modelSelectOptions.value[0]?.value
  if (!firstModel) return
  if (!modelSelectOptions.value.some((option) => option.value === form.model)) {
    form.model = firstModel
  }
}

function ensureAvailableImageSize() {
  if (!isImageSizeSupportedByModel(form.size, form.model)) {
    form.size = DEFAULT_IMAGE_SIZE
  }
}

function selectImageRatio(ratio: string) {
  const presets = availableSizePresets.value
  const auto = presets.find((preset) => preset.value === DEFAULT_IMAGE_SIZE)
  if (ratio === 'auto') {
    form.size = auto?.value || DEFAULT_IMAGE_SIZE
    return
  }
  const exact = selectedSizeResolution.value !== 'auto'
    ? presets.find((preset) => preset.ratio === ratio && preset.resolution === selectedSizeResolution.value)
    : undefined
  const next = exact || presets.find((preset) => preset.ratio === ratio) || auto
  form.size = next?.value || DEFAULT_IMAGE_SIZE
}

function selectImageResolution(resolution: ImageSizeResolution) {
  const presets = availableSizePresets.value
  const auto = presets.find((preset) => preset.value === DEFAULT_IMAGE_SIZE)
  if (resolution === 'auto') {
    form.size = auto?.value || DEFAULT_IMAGE_SIZE
    return
  }
  const exact = selectedSizeRatio.value !== 'auto'
    ? presets.find((preset) => preset.ratio === selectedSizeRatio.value && preset.resolution === resolution)
    : undefined
  const next = exact || presets.find((preset) => preset.resolution === resolution) || auto
  form.size = next?.value || DEFAULT_IMAGE_SIZE
}

function resultPreviewStyle(size: string) {
  const parsed = parseImageSize(size)
  if (!parsed) {
    return {
      '--image-result-preview-ratio': '1 / 1',
      '--image-result-preview-width': '22rem',
    }
  }
  const ratio = parsed.width / parsed.height
  const width = ratio > 1.25 ? '26rem' : ratio < 0.8 ? '18rem' : '22rem'
  return {
    '--image-result-preview-ratio': `${parsed.width} / ${parsed.height}`,
    '--image-result-preview-width': width,
  }
}

async function loadQuotaSummary() {
  if (isQuotaLoading.value) return
  isQuotaLoading.value = true
  try {
    quotaSummary.value = await imageTasksApi.quota()
  } catch (error) {
    console.error('[image-tasks] quota load failed', error)
    quotaSummary.value = null
  } finally {
    isQuotaLoading.value = false
  }
}

function applyQuotaSummary(summary: ImageQuotaSummary | undefined) {
  if (summary) quotaSummary.value = summary
}

function updateSizeMenuPosition() {
  const button = sizeMenuButtonRef.value
  if (!button || typeof window === 'undefined') return
  const rect = button.getBoundingClientRect()
  const menuWidth = Math.min(448, window.innerWidth - 32)
  sizeMenuPosition.top = Math.max(16, rect.top - 8)
  sizeMenuPosition.left = Math.max(16, Math.min(rect.left, window.innerWidth - menuWidth - 16))
}

function toggleSizeMenu() {
  if (!isSizeMenuOpen.value) {
    updateSizeMenuPosition()
  }
  isSizeMenuOpen.value = !isSizeMenuOpen.value
}

function createId(prefix = 'local') {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function normalizeConversation(raw: any): ImageConversation | null {
  if (!raw || typeof raw !== 'object') return null
  const id = String(raw.id || '').trim()
  if (!id) return null
  const turns = Array.isArray(raw.turns)
    ? raw.turns.map((turn: any) => ({
      id: String(turn.id || createId('turn')),
      taskId: String(turn.taskId || ''),
      prompt: String(turn.prompt || ''),
      mode: String(turn.mode || 'generate') === 'edit' ? 'edit' : 'generate',
      model: String(turn.model || DEFAULT_IMAGE_MODEL),
      n: normalizeImageCount(turn.n),
      size: String(turn.size || DEFAULT_IMAGE_SIZE),
      quality: String(turn.quality || DEFAULT_IMAGE_QUALITY),
      sourceImages: Array.isArray(turn.sourceImages)
        ? turn.sourceImages.map((source: any) => ({
          id: String(source.id || createId('source')),
          name: String(source.name || '参考图'),
          type: String(source.type || ''),
          size: Number(source.size || 0),
          dataUrl: String(source.dataUrl || ''),
          url: String(source.url || ''),
        }))
        : [],
      createdAt: String(turn.createdAt || raw.createdAt || new Date().toISOString()),
    })).filter((turn: ImageConversationTurn) => turn.taskId || turn.prompt)
    : []
  return {
    id,
    title: String(raw.title || '未命名对话'),
    createdAt: String(raw.createdAt || new Date().toISOString()),
    updatedAt: String(raw.updatedAt || raw.createdAt || new Date().toISOString()),
    turns,
  }
}

function loadConversations() {
  const stored = getJsonPreference<unknown[]>(preferenceKeys.imageTaskConversations, [])
  conversations.value = Array.isArray(stored)
    ? stored.map(normalizeConversation).filter((item): item is ImageConversation => Boolean(item))
    : []
  activeConversationId.value = getStringPreference(preferenceKeys.imageTaskActiveConversationId, '')
  if (activeConversationId.value && !conversations.value.some((item) => item.id === activeConversationId.value)) {
    activeConversationId.value = ''
  }
}

function persistConversations() {
  const payload = conversations.value.slice(0, 80).map((conversation) => ({
    ...conversation,
    turns: conversation.turns.slice(-80).map((turn) => ({
      ...turn,
      sourceImages: turn.sourceImages.map((source) => ({
        ...source,
        dataUrl: source.dataUrl && source.dataUrl.length < 240_000 ? source.dataUrl : '',
      })),
    })),
  }))
  setJsonPreference(preferenceKeys.imageTaskConversations, payload)
  setStringPreference(preferenceKeys.imageTaskActiveConversationId, activeConversationId.value)
}

function buildConversationTitle(prompt: string) {
  const trimmed = prompt.trim().replace(/\s+/g, ' ')
  return trimmed.length > 14 ? `${trimmed.slice(0, 14)}...` : trimmed || '新对话'
}

function createConversation() {
  const now = new Date().toISOString()
  const conversation: ImageConversation = {
    id: createId('conversation'),
    title: '新对话',
    createdAt: now,
    updatedAt: now,
    turns: [],
  }
  conversations.value = [conversation, ...conversations.value]
  activeConversationId.value = conversation.id
  persistConversations()
  void nextTick(() => textareaRef.value?.focus())
}

function selectConversation(id: string) {
  activeConversationId.value = id
  persistConversations()
  void nextTick(scrollToBottom)
}

function activeOrCreateConversation(prompt: string) {
  let conversation = selectedConversation.value
  if (!conversation) {
    const now = new Date().toISOString()
    conversation = {
      id: createId('conversation'),
      title: buildConversationTitle(prompt),
      createdAt: now,
      updatedAt: now,
      turns: [],
    }
    conversations.value = [conversation, ...conversations.value]
    activeConversationId.value = conversation.id
  }
  if (!conversation.turns.length && conversation.title === '新对话') {
    conversation.title = buildConversationTitle(prompt)
  }
  return conversation
}

function conversationRunningCount(conversation: ImageConversation) {
  return conversation.turns.filter((turn) => {
    const task = taskForTurn(turn)
    return task && !isImageTaskTerminal(task)
  }).length
}

function taskForTurn(turn: ImageConversationTurn) {
  return taskById.value.get(turn.taskId)
}

function storedTaskIds() {
  const ids = getJsonPreference<unknown[]>(preferenceKeys.imageTaskLocalIds, [])
  return Array.isArray(ids)
    ? ids.map((id) => String(id)).filter(Boolean)
    : []
}

function saveTaskIds() {
  const ids = Array.from(new Set([
    ...tasks.value.map((task) => task.id).filter(Boolean),
    ...conversations.value.flatMap((conversation) => conversation.turns.map((turn) => turn.taskId).filter(Boolean)),
  ])).slice(0, 160)
  setJsonPreference(preferenceKeys.imageTaskLocalIds, ids)
}

function sortTasks(items: ImageTask[]) {
  return [...items].sort((a, b) => String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || '')))
}

function sortConversations() {
  conversations.value = [...conversations.value].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
}

function mergeTasks(nextTasks: ImageTask[]) {
  const map = new Map(tasks.value.map((task) => [task.id, task]))
  nextTasks.filter((task) => task.id).forEach((task) => {
    if (task.id) map.set(task.id, task)
  })
  tasks.value = sortTasks(Array.from(map.values()))
  saveTaskIds()
}

async function refreshTasks() {
  if (isFetching.value) return
  isFetching.value = true
  try {
    const ids = storedTaskIds()
    if (ids.length) {
        const stored = await imageTasksApi.list(ids)
        applyQuotaSummary(stored.quota_summary)
        tasks.value = sortTasks(stored.items.filter((task) => task.id && ids.includes(task.id)))
      } else {
        const stored = await imageTasksApi.list()
        applyQuotaSummary(stored.quota_summary)
        tasks.value = []
      }
      saveTaskIds()
    } catch (error: any) {
    toast.error(error.message || '刷新图片任务失败')
  } finally {
    isFetching.value = false
    hasLoadedOnce.value = true
    schedulePoll()
  }
}

async function pollUnfinishedTasks() {
  if (!autoPoll.value || !unfinishedTasks.value.length || isFetching.value) return
  isFetching.value = true
  try {
    const previousStatus = new Map(tasks.value.map((task) => [task.id, task.status]))
    const response = await imageTasksApi.list(unfinishedTasks.value.map((task) => task.id))
    applyQuotaSummary(response.quota_summary)
    mergeTasks(response.items)
    const hasNewSuccess = response.items.some((task) => task.status === 'success' && previousStatus.get(task.id) !== 'success')
    if (hasNewSuccess) void loadQuotaSummary()
  } catch (error: any) {
    toast.error(error.message || '轮询图片任务失败')
  } finally {
    isFetching.value = false
    schedulePoll()
  }
}

function schedulePoll() {
  if (pollTimer) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
  if (!autoPoll.value || !unfinishedTasks.value.length) return
  pollTimer = window.setTimeout(() => {
    void pollUnfinishedTasks()
  }, 3000)
}

function parseImageUrls() {
  return imageUrlsInput.value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function openFilePicker() {
  fileInputRef.value?.click()
}

function isImageFile(file: File) {
  return file.type.startsWith('image/') || /\.(avif|bmp|gif|heic|heif|ico|jpe?g|png|svg|tiff?|webp)$/i.test(file.name)
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('读取参考图失败'))
    reader.readAsDataURL(file)
  })
}

async function appendFiles(files: File[]) {
  const imageFiles = files.filter(isImageFile)
  if (!imageFiles.length) return
  for (const file of imageFiles) {
    selectedFiles.value.push(file)
    referencePreviews.value.push({
      id: createId('source'),
      name: file.name || '参考图',
      type: file.type || 'image/png',
      size: file.size,
      dataUrl: await readFileAsDataUrl(file),
    })
  }
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  void appendFiles(Array.from(input.files || []))
  input.value = ''
}

function handlePaste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files || []).filter(isImageFile)
  if (!files.length) return
  event.preventDefault()
  void appendFiles(files)
}

function handleDrop(event: DragEvent) {
  isDraggingImage.value = false
  const files = Array.from(event.dataTransfer?.files || []).filter(isImageFile)
  void appendFiles(files)
}

function handleDragLeave(event: DragEvent) {
  const current = event.currentTarget as HTMLElement
  if (event.relatedTarget instanceof Node && current.contains(event.relatedTarget)) return
  isDraggingImage.value = false
}

function closeSizeMenu() {
  isSizeMenuOpen.value = false
}

function removeComposerSource(index: number) {
  if (index < referencePreviews.value.length) {
    referencePreviews.value = referencePreviews.value.filter((_item, itemIndex) => itemIndex !== index)
    selectedFiles.value = selectedFiles.value.filter((_item, itemIndex) => itemIndex !== index)
    return
  }
  const urlIndex = index - referencePreviews.value.length
  const urls = parsedImageUrls.value.filter((_item, itemIndex) => itemIndex !== urlIndex)
  imageUrlsInput.value = urls.join('\n')
}

function clearSources() {
  selectedFiles.value = []
  referencePreviews.value = []
  imageUrlsInput.value = ''
  if (fileInputRef.value) fileInputRef.value.value = ''
}

function clearComposerInputs() {
  form.prompt = ''
  clearSources()
}

function handlePromptKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  void submitTask()
}

async function submitTask() {
  const prompt = form.prompt.trim()
  if (!prompt || isSubmitting.value) return

  const imageUrls = parseImageUrls()
  const effectiveMode: SubmitMode = selectedFiles.value.length || imageUrls.length ? 'edit' : 'generate'
  if (isHighRiskImageSize.value) {
    toast.warning('当前选择 4K，Codex 上游可能返回 server_error；失败时建议先用 1K 或 2K。')
  }

  isSubmitting.value = true
  try {
    const baseInput = {
      prompt,
      model: form.model || DEFAULT_IMAGE_MODEL,
      n: normalizeImageCount(form.n),
      size: form.size,
      quality: form.quality,
    }
    const task = effectiveMode === 'edit'
      ? await imageTasksApi.createEdit({ ...baseInput, files: selectedFiles.value, imageUrls })
      : await imageTasksApi.createGeneration(baseInput)

    const conversation = activeOrCreateConversation(prompt)
    const now = new Date().toISOString()
    conversation.turns.push({
      id: createId('turn'),
      taskId: task.id,
      prompt,
      mode: effectiveMode,
      model: task.model || baseInput.model,
      n: normalizeImageCount(task.n || baseInput.n),
      size: task.size || baseInput.size,
      quality: task.quality || baseInput.quality,
      sourceImages: composerSources.value.map((source) => ({ ...source })),
      createdAt: now,
    })
    conversation.updatedAt = now
    sortConversations()
    mergeTasks([task])
    if (task.status === 'success') void loadQuotaSummary()
    persistConversations()
    clearComposerInputs()
    toast.success('已发送到当前对话')
    schedulePoll()
    await nextTick()
    scrollToBottom()
  } catch (error: any) {
    toast.error(error.message || '提交图片任务失败')
  } finally {
    isSubmitting.value = false
  }
}

async function retryTurn(turn: ImageConversationTurn) {
  if (isSubmitting.value) return
  form.prompt = turn.prompt
  imageUrlsInput.value = turn.sourceImages.map((source) => source.url || '').filter(Boolean).join('\n')
  toast.info('已回填提示词和参考图，参数保持当前选择')
  await nextTick()
  textareaRef.value?.focus()
}

async function resumeTask(task: ImageTask) {
  if (resumingTaskId.value) return
  resumingTaskId.value = task.id
  try {
    const next = await imageTasksApi.resumePoll(task.id, 30)
    mergeTasks([next])
    toast.success('已恢复轮询')
  } catch (error: any) {
    toast.error(error.message || '恢复轮询失败')
  } finally {
    resumingTaskId.value = ''
    schedulePoll()
  }
}

async function seedAssetForEdit(asset: ImageTaskAsset, index: number) {
  const url = assetUrl(asset)
  if (!url) return
  if (url.startsWith('data:')) {
    try {
      const file = await dataUrlToFile(url, `result-${index + 1}.png`, 'image/png')
      await appendFiles([file])
    } catch {
      imageUrlsInput.value = [imageUrlsInput.value, url].filter(Boolean).join('\n')
    }
  } else {
    const urls = new Set(parsedImageUrls.value)
    urls.add(url)
    imageUrlsInput.value = Array.from(urls).join('\n')
  }
  await nextTick()
  textareaRef.value?.focus()
}

function fallbackConversationId() {
  const running = conversations.value.find((conversation) => conversationRunningCount(conversation) > 0)
  return running?.id || conversations.value[0]?.id || ''
}

async function deleteConversation(conversation: ImageConversation) {
  const confirmed = await confirmDialog.ask({
    title: '删除对话',
    message: `确认删除当前浏览器里的「${conversation.title || '未命名对话'}」历史吗？不会删除服务器任务或图片。`,
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!confirmed) return

  const ids = conversation.turns.map((turn) => turn.taskId).filter(Boolean)
  conversations.value = conversations.value.filter((item) => item.id !== conversation.id)
  tasks.value = tasks.value.filter((task) => !ids.includes(task.id))
  if (activeConversationId.value === conversation.id) {
    activeConversationId.value = fallbackConversationId()
  }
  saveTaskIds()
  persistConversations()
  schedulePoll()
  toast.success('已删除对话')
}

async function deleteTurn(conversationId: string, turnId: string) {
  const conversation = conversations.value.find((item) => item.id === conversationId)
  const turn = conversation?.turns.find((item) => item.id === turnId)
  if (!conversation || !turn) return
  const confirmed = await confirmDialog.ask({
    title: '删除本轮记录',
    message: '确认删除当前浏览器里的这一轮提示词和生成结果记录吗？不会删除服务器任务或图片。',
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!confirmed) return

  if (turn.taskId) {
    tasks.value = tasks.value.filter((task) => task.id !== turn.taskId)
  }
  conversation.turns = conversation.turns.filter((item) => item.id !== turnId)
  conversation.updatedAt = new Date().toISOString()
  if (!conversation.turns.length) {
    conversations.value = conversations.value.filter((item) => item.id !== conversationId)
    if (activeConversationId.value === conversationId) activeConversationId.value = fallbackConversationId()
  } else {
    sortConversations()
  }
  saveTaskIds()
  persistConversations()
  schedulePoll()
  toast.success('已删除本轮记录')
}

async function confirmClearLocalHistory() {
  const confirmed = await confirmDialog.ask({
    title: '清空历史记录',
    message: '确认清空当前浏览器里的画图历史吗？不会删除服务器任务或图片。',
    confirmText: '清空',
    cancelText: '取消',
  })
  if (!confirmed) return
  clearLocalHistory()
}

function clearLocalHistory() {
  tasks.value = []
  conversations.value = []
  activeConversationId.value = ''
  removePreference(preferenceKeys.imageTaskLocalIds)
  removePreference(preferenceKeys.imageTaskConversations)
  removePreference(preferenceKeys.imageTaskActiveConversationId)
  schedulePoll()
  toast.success('已清空历史记录')
}

function sourcePreviewUrl(source: ReferencePreview) {
  return source.dataUrl || source.url || ''
}

function assetUrl(asset: ImageTaskAsset) {
  return imageAssetUrl(asset)
}

function primaryMessage(task: ImageTask) {
  return taskPrimaryMessage(task)
}

function stageLabel(stage: string | undefined) {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '运行中',
    account_acquire: '获取账号',
    upstream_sse: '等待上游',
    result_download: '下载结果',
    upload: '上传存储',
    completed: '已完成',
    success: '已完成',
    error: '失败',
  }
  const key = String(stage || '').trim()
  return labels[key] || key || '-'
}

function taskStatusLabel(status: ImageTaskStatus | undefined) {
  const labels: Record<ImageTaskStatus, string> = {
    queued: '排队中',
    running: '处理中',
    success: '已完成',
    error: '失败',
  }
  return status ? labels[status] : '等待中'
}

function formatDuration(durationMs?: number, elapsedSecs?: number) {
  if (Number.isFinite(durationMs) && Number(durationMs) > 0) {
    return `${(Number(durationMs) / 1000).toFixed(1)}s`
  }
  if (Number.isFinite(elapsedSecs) && Number(elapsedSecs) >= 0) {
    return `${Number(elapsedSecs).toFixed(1)}s`
  }
  return '-'
}

function formatShortTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function downloadName(turn: ImageConversationTurn, index: number) {
  const safeIndex = String(index + 1).padStart(2, '0')
  return `chatgpt-image-${turn.id.slice(0, 8)}-${safeIndex}.png`
}

async function downloadAsset(asset: ImageTaskAsset, turn: ImageConversationTurn, index: number) {
  const url = assetUrl(asset)
  if (!url) {
    toast.error('没有可下载的图片地址')
    return
  }

  const filename = downloadName(turn, index)
  try {
    await downloadUrlAsFile(url, filename, { localPath: String(asset.path || '') })
    toast.success('已开始下载')
  } catch (error: any) {
    toast.error(`下载失败：${error.message || '无法读取图片文件'}`)
  }
}

async function copyText(value: string) {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
    toast.success('已复制')
  } catch {
    toast.error('复制失败')
  }
}

async function copyTaskError(task: ImageTask) {
  const payload = {
    id: task.id,
    status: task.status,
    stage: task.stage,
    error_code: task.error_code,
    reason: task.reason,
    error: task.error,
    conversation_id: task.conversation_id,
    raw_upstream_message: task.raw_upstream_message,
    diagnosis: task.diagnosis,
  }
  await copyText(JSON.stringify(payload, null, 2))
}

function openPreview(src: string, name: string, localPath = '') {
  if (!src) return
  previewImage.value = { src, name, localPath }
}

function closePreview() {
  previewImage.value = null
}

async function downloadPreviewImage() {
  if (!previewImage.value) return
  try {
    await downloadUrlAsFile(previewImage.value.src, previewImage.value.name || 'image.png', {
      localPath: previewImage.value.localPath || '',
    })
    toast.success('已开始下载')
  } catch (error: any) {
    toast.error(`下载失败：${error.message || '无法读取图片文件'}`)
  }
}

function scrollToBottom() {
  const element = resultsViewportRef.value
  if (!element) return
  showScrollLatest.value = false
  element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' })
}

function handleResultsScroll() {
  const element = resultsViewportRef.value
  if (!element) return
  showScrollLatest.value = element.scrollHeight - element.scrollTop - element.clientHeight > 160
}

watch(unfinishedTasks, schedulePoll)
watch(modelSelectOptions, ensureAvailableImageModel, { immediate: true })
watch(() => form.model, ensureAvailableImageSize, { immediate: true })

onMounted(() => {
  loadConversations()
  if (!settings.value && !settingsStore.isLoading) {
    void settingsStore.loadSettings()
  }
  void loadModelCatalog().finally(ensureAvailableImageModel)
  void loadQuotaSummary()
  window.addEventListener('click', closeSizeMenu)
  void refreshTasks()
})

onBeforeUnmount(() => {
  window.removeEventListener('click', closeSizeMenu)
  if (pollTimer) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped>
.image-workspace {
  --image-content-width: min(100%, 66rem);
  --image-history-width: clamp(12rem, 18%, 15rem);
  display: grid;
  box-sizing: border-box;
  height: calc(100dvh - 11rem);
  min-height: 32rem;
  max-width: 92rem;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.875rem;
  margin: 0 auto;
  overflow: hidden;
  padding: 0;
}

@media (min-width: 1024px) {
  .image-workspace {
    grid-template-columns: var(--image-history-width) minmax(0, 1fr);
  }
}

.image-history-panel {
  display: none;
  min-height: 0;
  flex-direction: column;
  gap: 0.75rem;
  border: 1px solid hsl(var(--border));
  border-radius: 1rem;
  background: hsl(var(--card));
  padding: 0.75rem;
  box-shadow: 0 16px 44px -36px rgba(15, 23, 42, 0.45);
}

@media (min-width: 1024px) {
  .image-history-panel {
    display: flex;
  }
}

.image-history-actions,
.image-mobile-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.image-mobile-actions {
  flex: 0 0 auto;
}

@media (min-width: 1024px) {
  .image-mobile-actions {
    display: none;
  }
}

.image-history-list {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  padding-right: 0.125rem;
}

.image-history-item {
  position: relative;
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: 0.25rem;
  border: 1px solid transparent;
  border-radius: 0.875rem;
  padding: 0.7rem 0.75rem;
  text-align: left;
  color: hsl(var(--foreground));
  transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
}

.image-history-main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.25rem;
  padding-right: 1.85rem;
  text-align: left;
}

.image-history-delete {
  position: absolute;
  top: 0.5rem;
  right: 0.45rem;
  display: inline-flex;
  width: 1.75rem;
  height: 1.75rem;
  align-items: center;
  justify-content: center;
  border-radius: 0.5rem;
  color: hsl(var(--muted-foreground));
  opacity: 0;
  transition: background 0.15s, color 0.15s, opacity 0.15s;
}

.image-history-item:hover .image-history-delete,
.image-history-delete:focus-visible {
  opacity: 1;
}

.image-history-delete:hover {
  background: rgb(254 242 242);
  color: rgb(225 29 72);
}

.image-history-item:hover {
  border-color: hsl(var(--border));
  background: hsl(var(--secondary) / 0.55);
}

.image-history-item.is-active {
  border-color: hsl(var(--primary) / 0.28);
  background: hsl(var(--primary) / 0.08);
  box-shadow: inset 0 0 0 1px hsl(var(--primary) / 0.08);
}

.image-history-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.875rem;
  font-weight: 650;
}

.image-history-meta,
.image-history-running,
.image-history-empty {
  font-size: 0.75rem;
  color: hsl(var(--muted-foreground));
}

.image-history-running {
  width: fit-content;
  border-radius: 999px;
  background: #eff6ff;
  padding: 0.125rem 0.5rem;
  color: #1d4ed8;
}

.image-history-empty {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.875rem;
  line-height: 1.6;
}

.image-chat-panel {
  position: relative;
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 0.75rem;
}

.image-chat-scroll {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0.5rem clamp(0.25rem, 2vw, 1.5rem) 1rem;
  scrollbar-width: none;
  contain: layout style paint;
}

.image-chat-scroll::-webkit-scrollbar {
  display: none;
}

.image-scroll-latest {
  position: absolute;
  left: 50%;
  bottom: 11.25rem;
  z-index: 30;
  display: inline-flex;
  width: 2.75rem;
  height: 2.75rem;
  transform: translateX(-50%);
  align-items: center;
  justify-content: center;
  border: 1px solid hsl(var(--border));
  border-radius: 999px;
  background: hsl(var(--card) / 0.95);
  color: hsl(var(--foreground));
  box-shadow: 0 18px 42px -24px rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(10px);
  transition: transform 0.15s, background 0.15s;
}

.image-scroll-latest:hover {
  transform: translate(-50%, -2px);
  background: hsl(var(--card));
}

.image-chat-empty {
  display: flex;
  min-height: 100%;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}

.image-chat-empty h1 {
  color: hsl(var(--foreground));
  font-family: "Palatino Linotype", "Book Antiqua", "Times New Roman", serif;
  font-size: clamp(1.8rem, 5vw, 3.4rem);
  font-weight: 650;
  letter-spacing: 0;
}

.image-chat-empty p {
  margin-top: 0.875rem;
  max-width: 34rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.875rem;
  line-height: 1.8;
}

.image-turns {
  margin: 0 auto;
  display: flex;
  width: var(--image-content-width);
  flex-direction: column;
  gap: 1.75rem;
  padding-bottom: 0.5rem;
}

.image-turn {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.image-user-row {
  display: flex;
  justify-content: flex-end;
}

.image-user-bubble {
  display: flex;
  max-width: min(50rem, 86%);
  flex-direction: column;
  align-items: flex-end;
  gap: 0.45rem;
}

.image-turn-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.5rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.6875rem;
}

.image-user-prompt {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  padding: 0.25rem 0.125rem;
  text-align: right;
  color: hsl(var(--foreground));
  font-size: 0.9375rem;
  line-height: 1.75;
}

.image-user-actions,
.image-result-tail-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.6875rem;
}

.image-user-actions button,
.image-result-tail-actions button {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  border-radius: 999px;
  background: hsl(var(--secondary));
  padding: 0.25rem 0.625rem;
  color: hsl(var(--muted-foreground));
  font-weight: 650;
  transition: background 0.15s, color 0.15s;
}

.image-user-actions button:hover,
.image-result-tail-actions button:hover {
  background: hsl(var(--secondary) / 0.8);
  color: hsl(var(--foreground));
}

.image-user-actions button.is-danger {
  width: 1.5rem;
  height: 1.5rem;
  justify-content: center;
  padding: 0;
  color: hsl(var(--muted-foreground));
}

.image-user-actions button.is-danger:hover {
  background: rgb(254 242 242);
  color: rgb(225 29 72);
}

.image-turn-references {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.65rem;
}

.image-reference-title {
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
  font-weight: 650;
}

.image-source-strip,
.image-reference-row {
  display: flex;
  max-width: 100%;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.5rem;
}

.image-source-thumb {
  display: flex;
  width: 4.25rem;
  height: 4.25rem;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 1px solid hsl(var(--border));
  border-radius: 16px;
  background: hsl(var(--card));
  color: hsl(var(--muted-foreground));
}

.image-source-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.image-assistant-row {
  display: flex;
  flex-direction: column;
  gap: 0.875rem;
  align-items: flex-start;
}

.image-result-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.image-result-block {
  width: fit-content;
  max-width: 100%;
}

.image-result-grid {
  display: flex;
  width: fit-content;
  max-width: min(100%, 44rem);
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 0.625rem;
}

.image-result-grid.is-single {
  max-width: min(100%, 30rem);
}

.image-result-card {
  overflow: hidden;
  border: 1px solid hsl(var(--border));
  border-radius: 0.75rem;
  background: hsl(var(--card));
}

.image-result-item {
  flex: 0 1 min(18rem, 100%);
  overflow: visible;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.image-result-grid.is-single .image-result-item {
  width: fit-content;
  max-width: 100%;
  flex-basis: auto;
}

.image-result-card.is-loading,
.image-result-card.is-error {
  display: flex;
  width: min(100%, var(--image-result-preview-width, 32rem));
  min-height: 10rem;
  max-height: 24rem;
  aspect-ratio: var(--image-result-preview-ratio, 1 / 1);
  flex-direction: column;
  justify-content: center;
  gap: 0.75rem;
  padding: 1.5rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.875rem;
  line-height: 1.7;
}

.image-result-card.is-loading {
  align-items: center;
  text-align: center;
  background: hsl(var(--secondary) / 0.45);
}

.image-result-card.is-error {
  border-color: rgb(254 202 202);
  background: rgb(254 242 242);
  color: rgb(185 28 28);
}

.image-loading-icon {
  display: inline-flex;
  width: 2.8rem;
  height: 2.8rem;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: white;
  color: hsl(var(--foreground));
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.08);
}

.image-result-media {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 0;
  border-radius: 0.75rem;
  background: hsl(var(--secondary) / 0.35);
  padding: 0;
  color: inherit;
  cursor: zoom-in;
}

.image-result-media.has-image {
  display: block;
  width: fit-content;
  max-width: 100%;
  overflow: visible;
  background: transparent;
}

.image-result-media img {
  display: block;
  width: auto;
  max-width: min(100%, 30rem);
  height: auto;
  max-height: 62vh;
  border-radius: 16px;
  object-fit: contain;
}

.image-result-grid:not(.is-single) .image-result-media.has-image img {
  max-width: min(100%, 18rem);
  max-height: 24rem;
}

.image-result-media span {
  padding: 3rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.8125rem;
}

.image-result-footer {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.35rem 0.125rem 0;
}

.image-result-caption {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
}

.image-result-tail-actions {
  margin-top: 0.35rem;
}

.image-download-btn {
  display: inline-flex;
  min-height: 1.75rem;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  border: 1px solid hsl(var(--border));
  border-radius: 999px;
  background: hsl(var(--card));
  padding: 0.25rem 0.6rem;
  color: hsl(var(--foreground));
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.image-download-btn:hover {
  background: hsl(var(--secondary));
}

.image-composer-shell {
  position: relative;
  z-index: 20;
  flex: 0 0 auto;
  width: var(--image-content-width);
  margin: 0 auto;
}

.image-composer {
  position: relative;
  width: 100%;
  overflow: hidden;
  border: 1px solid hsl(var(--border));
  border-radius: 32px;
  background: hsl(var(--card));
  box-shadow: 0 14px 60px -42px rgba(15, 23, 42, 0.45);
  transition: border-color 0.15s, background 0.15s;
}

@media (min-width: 640px) {
  .image-composer {
    box-shadow: none;
  }
}

.image-composer.is-dragging {
  border-color: hsl(var(--foreground));
  background: hsl(var(--secondary) / 0.7);
}

.image-quota-chip,
.image-active-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border-radius: 999px;
  background: hsl(var(--secondary));
  padding: 0.5rem 0.75rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
  font-weight: 600;
}

.image-active-chip {
  background: #eff6ff;
  color: #1d4ed8;
}

.image-quota-chip {
  background: #f0fdf4;
  color: #15803d;
}

.image-quota-chip.is-empty {
  background: #fff7ed;
  color: #c2410c;
}

.image-reference-count {
  display: inline-flex;
  min-height: 2rem;
  align-items: center;
  border-radius: 999px;
  background: hsl(var(--muted) / 0.62);
  padding: 0 10px;
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
}

.image-reference-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
  justify-content: flex-start;
  margin-bottom: 0.75rem;
  padding: 0 0.25rem;
}

.image-reference-chip {
  position: relative;
  width: 4rem;
  height: 4rem;
  flex: 0 0 auto;
}

.image-reference-preview {
  display: flex;
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 1px solid hsl(var(--border));
  border-radius: 1rem;
  background: hsl(var(--secondary) / 0.65);
  color: hsl(var(--muted-foreground));
  transition: border-color 0.15s, transform 0.15s;
}

.image-reference-preview:hover {
  border-color: hsl(var(--foreground) / 0.35);
  transform: translateY(-1px);
}

.image-reference-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.image-reference-remove {
  position: absolute;
  top: -0.35rem;
  right: -0.35rem;
  display: inline-flex;
  width: 1.25rem;
  height: 1.25rem;
  align-items: center;
  justify-content: center;
  border: 1px solid hsl(var(--border));
  border-radius: 999px;
  background: hsl(var(--card));
  color: hsl(var(--muted-foreground));
  box-shadow: 0 8px 20px -14px rgba(15, 23, 42, 0.6);
  transition: color 0.15s, border-color 0.15s;
}

.image-reference-remove:hover {
  border-color: hsl(var(--destructive) / 0.35);
  color: hsl(var(--destructive));
}

.image-prompt-input {
  width: 100%;
  resize: none;
  border: 0;
  background: transparent;
  color: hsl(var(--foreground));
  outline: none;
}

.image-prompt-input {
  display: block;
  min-height: 9.25rem;
  max-height: 13rem;
  border-radius: 32px;
  padding: 1.45rem 1.5rem 5.1rem;
  font-size: 0.9375rem;
  line-height: 1.7;
}

.image-prompt-input::placeholder {
  color: hsl(var(--muted-foreground));
}

.image-composer-footer {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.75rem;
  background: linear-gradient(to top, hsl(var(--card)) 68%, hsl(var(--card) / 0));
  padding: 1.6rem 1.5rem 1rem;
}

.image-composer-tools {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.image-size-menu-wrap {
  position: relative;
  flex: 0 0 auto;
}

.image-size-trigger {
  display: inline-flex;
  min-height: 2.25rem;
  max-width: 18rem;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  border-radius: 999px;
  background: hsl(var(--secondary));
  padding: 0.45rem 0.8rem;
  color: hsl(var(--foreground));
  font-size: 0.8125rem;
  font-weight: 700;
  transition: background 0.15s;
}

.image-size-trigger:hover {
  background: hsl(var(--secondary) / 0.8);
}

.image-size-trigger span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.image-size-popover {
  position: fixed;
  z-index: 220;
  width: min(28rem, calc(100vw - 3rem));
  max-height: min(34rem, calc(100dvh - 8rem));
  overflow-y: auto;
  border: 1px solid hsl(var(--border));
  border-radius: 1.5rem;
  background: hsl(var(--card));
  padding: 1rem;
  box-shadow: 0 28px 90px -42px rgba(15, 23, 42, 0.5);
  transform: translateY(-100%);
}

.image-size-section + .image-size-section {
  margin-top: 0.85rem;
}

.image-size-label {
  margin-bottom: 0.45rem;
  color: hsl(var(--foreground));
  font-size: 0.8125rem;
  font-weight: 700;
}

.image-size-select {
  width: 100%;
}

.image-choice-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.45rem;
}

.image-choice-grid.is-quality {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.image-choice-grid.is-count {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.image-choice-grid.is-ratio {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.image-choice-grid.is-resolution {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.image-choice-button {
  min-height: 2.25rem;
  border: 1px solid hsl(var(--border));
  border-radius: 999px;
  background: hsl(var(--card));
  padding: 0.35rem 0.7rem;
  color: hsl(var(--foreground));
  font-size: 0.8125rem;
  font-weight: 500;
  transition: border-color 0.15s, background 0.15s;
}

.image-choice-button:hover {
  border-color: hsl(var(--foreground) / 0.25);
  background: hsl(var(--secondary) / 0.55);
}

.image-choice-button.is-active {
  border-color: hsl(var(--primary) / 0.45);
  background: hsl(var(--primary) / 0.08);
  color: hsl(var(--foreground));
}

.image-size-current {
  margin-top: 0.55rem;
  border-radius: 999px;
  background: hsl(var(--secondary) / 0.55);
  padding: 0.35rem 0.7rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
  line-height: 1.4;
}

.image-size-warning {
  margin-top: 0.5rem;
  border-radius: 0.75rem;
  border: 1px solid hsl(var(--destructive) / 0.22);
  background: hsl(var(--destructive) / 0.06);
  padding: 0.5rem 0.65rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
  line-height: 1.45;
}

.image-send-button {
  display: inline-flex;
  width: 2.55rem;
  height: 2.55rem;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: hsl(var(--foreground));
  color: hsl(var(--background));
  transition: opacity 0.15s, transform 0.15s;
}

.image-send-button:hover:not(:disabled) {
  transform: translateY(-1px);
}

.image-send-button:disabled {
  opacity: 0.35;
}

.image-drop-overlay {
  position: absolute;
  inset: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  border: 2px dashed hsl(var(--foreground));
  border-radius: inherit;
  background: hsl(var(--card) / 0.88);
  color: hsl(var(--foreground));
  font-size: 0.875rem;
  font-weight: 700;
  backdrop-filter: blur(3px);
}

.image-mobile-history-backdrop,
.image-lightbox {
  position: fixed;
  inset: 0;
  z-index: 150;
}

.image-mobile-history-backdrop {
  display: flex;
  align-items: flex-end;
  background: rgba(0, 0, 0, 0.35);
}

.image-mobile-history {
  width: 100%;
  max-height: 78vh;
  overflow: hidden;
  border-radius: 28px 28px 0 0;
  background: hsl(var(--card));
  padding: 1rem;
}

.image-mobile-history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 0.75rem;
  font-weight: 700;
}

.image-lightbox {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(10px);
}

.image-lightbox img {
  max-width: 92vw;
  max-height: 82vh;
  border-radius: 16px;
  object-fit: contain;
}

.image-lightbox-close {
  position: absolute;
  top: 1.25rem;
  right: 1.25rem;
  display: inline-flex;
  width: 2.4rem;
  height: 2.4rem;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(255, 255, 255, 0.22);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  color: white;
}

.image-lightbox-actions {
  position: absolute;
  right: 1.5rem;
  bottom: 1.25rem;
  left: 1.5rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.625rem;
  color: rgba(255, 255, 255, 0.82);
  font-size: 0.75rem;
}

.image-lightbox-actions button {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 999px;
  padding: 0.35rem 0.7rem;
  color: white;
}

@media (max-width: 720px) {
  .image-workspace {
    height: calc(100dvh - 9.5rem);
    min-height: 28rem;
  }

  .image-chat-scroll {
    padding-inline: 0;
  }

  .image-user-bubble {
    max-width: 94%;
  }

  .image-result-grid {
    gap: 0.5rem;
    max-width: 100%;
  }

  .image-result-grid.is-single {
    max-width: 100%;
  }

  .image-result-grid:not(.is-single) .image-result-item {
    flex-basis: calc((100% - 0.5rem) / 2);
  }

  .image-result-grid:not(.is-single) .image-result-media.has-image img {
    width: 100%;
    max-width: 100%;
    max-height: 48vh;
  }

  .image-result-grid.is-single .image-result-media.has-image img {
    max-width: 100%;
    max-height: 52vh;
  }

  .image-scroll-latest {
    bottom: 9rem;
  }

  .image-composer-shell {
    width: 100%;
  }

  .image-composer {
    border-radius: 24px;
  }

  .image-prompt-input {
    min-height: 6rem;
    padding-inline: 1rem;
    padding-bottom: 0.75rem;
    border-radius: 24px;
  }

  .image-composer-footer {
    position: static;
    align-items: center;
    border-top: 1px solid hsl(var(--border) / 0.7);
    background: hsl(var(--card));
    padding-inline: 0.85rem;
    padding-block: 0.65rem 0.85rem;
  }

  .image-composer-tools {
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 0.2rem;
  }

  .image-size-popover {
    width: min(22rem, calc(100vw - 2rem));
  }

  .image-choice-grid,
  .image-choice-grid.is-ratio,
  .image-choice-grid.is-resolution,
  .image-choice-grid.is-count,
  .image-choice-grid.is-quality {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
