<template>
  <div class="space-y-6">
    <PagePanel class="space-y-5">
      <PanelHeader title="代理管理" align="start">
        <template #copy>
          <p class="mt-1 text-xs text-muted-foreground">
            全局代理只作为默认回退；账号和账号组可以覆盖它。
          </p>
        </template>
        <template #actions>
          <Button size="sm" variant="outline" :disabled="loading" @click="loadData">
            {{ loading ? '刷新中...' : '刷新' }}
          </Button>
          <Button size="sm" variant="primary" :disabled="savingGlobal || loading" @click="saveGlobalProxy">
            {{ savingGlobal ? '保存中...' : '保存全局代理' }}
          </Button>
        </template>
      </PanelHeader>

      <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <FormSection density="roomy">
          <label class="block text-xs">
            <span class="ui-field-label">全局代理 URL</span>
            <Input
              v-model.trim="globalProxy"
              block
              root-class="font-mono"
              placeholder="http://127.0.0.1:7890 或 socks5://127.0.0.1:7890"
            />
          </label>
          <ActionRow class="mt-3" gap="tight">
            <Button size="xs" variant="outline" :disabled="testingKey === GLOBAL_TEST_KEY || !globalProxy" @click="testGlobalProxy">
              {{ testingKey === GLOBAL_TEST_KEY ? '测试中...' : '测试全局代理' }}
            </Button>
            <Button size="xs" variant="outline" :disabled="savingGlobal || testingKey === GLOBAL_TEST_KEY" @click="clearGlobalProxy">
              清空
            </Button>
          </ActionRow>
        </FormSection>

        <FormSection density="roomy" surface="background">
          <p class="text-xs text-muted-foreground">全局测试结果</p>
          <div v-if="globalTestResult" class="mt-3 space-y-1 text-xs">
            <p :class="globalTestResult.ok ? 'text-emerald-600' : 'text-rose-600'">
              {{ globalTestResult.ok ? '可用' : '不可用' }}
            </p>
            <p class="text-muted-foreground">HTTP {{ globalTestResult.status || '-' }} · {{ globalTestResult.latency_ms || 0 }}ms</p>
            <p v-if="globalTestResult.error" class="break-all text-rose-600">{{ globalTestResult.error }}</p>
          </div>
          <p v-else class="mt-3 text-xs text-muted-foreground">尚未测试</p>
        </FormSection>
      </div>
    </PagePanel>

    <PagePanel class="space-y-4">
      <PanelHeader title="代理组">
        <template #copy>
          <p class="mt-1 text-xs text-muted-foreground">一个组包含多个节点，用于账号组或 <code>group:代理组ID</code>。</p>
        </template>
        <template #actions>
          <Input
            :model-value="groupKeyword"
            block
            root-class="min-w-[12rem] md:w-80"
            placeholder="搜索代理组 / 节点 / 地址"
            @update:model-value="groupKeyword = $event.trim()"
          />
          <Button size="sm" variant="primary" @click="openCreateGroupModal">新建代理组</Button>
        </template>
      </PanelHeader>
      <PageLoadingState
        v-if="loading && groups.length === 0"
        title="正在加载代理组"
        description="读取代理组、节点和健康状态。"
      />
      <StateBlock v-else-if="filteredGroups.length === 0">
        <EmptyState plain title="暂无代理组" description="新建代理组后，可绑定账号组或在账号代理里引用。" />
      </StateBlock>
      <TableShell v-else>
        <table class="min-w-[1040px] w-full table-fixed text-left text-sm">
          <colgroup>
            <col class="w-[18%]" />
            <col class="w-[8rem]" />
            <col class="w-[34%]" />
            <col class="w-[14%]" />
            <col class="w-[16%]" />
            <col class="w-[12rem]" />
          </colgroup>
          <thead class="text-xs uppercase tracking-[0.16em] text-muted-foreground">
            <tr>
              <th class="py-3 pr-4">代理组</th>
              <th class="py-3 pr-4">状态</th>
              <th class="py-3 pr-4">节点</th>
              <th class="py-3 pr-4">引用</th>
              <th class="py-3 pr-4">健康</th>
              <th class="py-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody class="text-sm text-foreground">
            <tr
              v-for="group in filteredGroups"
              :key="group.id"
              class="border-t border-border transition-colors hover:bg-muted/20"
              :class="group.enabled ? '' : 'bg-muted/30'"
            >
              <td class="py-3 pr-4 align-top">
                <p class="truncate font-medium">{{ group.name || group.id }}</p>
                <p class="mt-1 truncate font-mono text-xs text-muted-foreground">{{ group.id }}</p>
                <p class="mt-1 truncate text-xs text-muted-foreground">{{ groupRotationSummary(group) }}</p>
                <p v-if="group.notes" class="mt-1 truncate text-xs text-muted-foreground" :title="group.notes">{{ group.notes }}</p>
              </td>
              <td class="py-3 pr-4 align-top">
                <StateBadge :tone="group.enabled ? 'success' : 'muted'" size="sm">
                  {{ group.enabled ? '启用' : '停用' }}
                </StateBadge>
              </td>
              <td class="py-3 pr-4 align-top">
                <div class="space-y-2">
                  <ProxyNodeSummaryCard
                    v-for="node in group.nodes"
                    :key="node.id"
                    :node="node"
                  />
                </div>
              </td>
              <td class="py-3 pr-4 align-top">
                <button type="button" class="font-mono text-xs text-primary hover:underline" @click="copyGroupReference(group.id)">
                  group:{{ group.id }}
                </button>
              </td>
              <td class="py-3 pr-4 align-top">
                <div class="space-y-1.5">
                  <p
                    v-for="node in group.nodes"
                    :key="`${group.id}-${node.id}-health`"
                    class="truncate text-xs"
                    :class="nodeTestClass(group, node)"
                    :title="node.last_error || node.last_checked_at || ''"
                  >
                    {{ node.name || node.id }} · {{ nodeTestSummary(group, node) }}
                  </p>
                </div>
              </td>
              <td class="py-3 text-right align-top">
                <div class="inline-flex flex-wrap justify-end gap-1.5">
                  <Button size="xs" variant="outline" root-class="w-16 justify-center" :disabled="testingKey === `group:${group.id}:all` || group.nodes.length === 0" @click="testProxyGroupAll(group)">
                    {{ testingKey === `group:${group.id}:all` ? '中...' : '测全部' }}
                  </Button>
                  <Button size="xs" variant="outline" root-class="w-14 justify-center" @click="openEditGroupModal(group)">
                    编辑
                  </Button>
                  <Button size="xs" variant="outline" root-class="w-14 justify-center" :disabled="savingGroupId === group.id" @click="toggleProxyGroup(group)">
                    {{ group.enabled ? '停用' : '启用' }}
                  </Button>
                  <Button size="xs" variant="outline" root-class="w-14 justify-center text-rose-600" :disabled="deletingGroupId === group.id" @click="deleteProxyGroup(group)">
                    删除
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </TableShell>
    </PagePanel>

    <ModalShell :open="showGroupModal" max-width="56rem" :z-index="120">
      <ModalHeader
        :title="editingGroupId ? '编辑代理组' : '新建代理组'"
        :close-disabled="savingGroupId === FORM_TEST_KEY"
        :bordered="false"
        compact
        @close="closeGroupModal"
      />

      <ModalBody class="space-y-4">
        <FormSection title="基础信息" surface="plain">
              <div class="grid grid-cols-1 gap-2.5 md:grid-cols-2">
                <label class="text-xs">
                  <span class="ui-field-label">代理组 ID</span>
                  <Input
                    :model-value="groupForm.id"
                    :disabled="Boolean(editingGroupId)"
                    block
                    placeholder="hk-pool / us-west"
                    @update:model-value="groupForm.id = normalizeGroupId($event)"
                  />
                </label>
                <label class="text-xs">
                  <span class="ui-field-label">显示名称</span>
                  <Input
                    :model-value="groupForm.name"
                    block
                    placeholder="香港代理池"
                    @update:model-value="groupForm.name = $event.trim()"
                  />
                </label>
              </div>

              <div class="grid grid-cols-1 gap-2.5 md:grid-cols-[minmax(0,1fr)_10rem_auto]">
                <label class="text-xs">
                  <span class="ui-field-label">备注</span>
                  <Input
                    :model-value="groupForm.notes"
                    block
                    placeholder="可选"
                    @update:model-value="groupForm.notes = $event.trim()"
                  />
                </label>
                <label class="text-xs">
                  <span class="ui-field-label">轮换间隔</span>
                  <Input
                    :model-value="String(groupForm.rotation_interval_minutes)"
                    block
                    type="number"
                    min="0"
                    step="1"
                    @update:model-value="groupForm.rotation_interval_minutes = normalizeRotationMinutes($event)"
                  />
                </label>
                <div class="flex items-end">
                  <Checkbox v-model="groupForm.enabled">启用代理组</Checkbox>
                </div>
              </div>
        </FormSection>

              <div class="space-y-3">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <p class="text-xs font-medium text-foreground">代理节点</p>
                  <Button size="xs" variant="outline" @click="addGroupNode">添加节点</Button>
                </div>
                <div class="space-y-3">
                  <FormSection
                    v-for="(node, index) in groupForm.nodes"
                    :key="`${node.id}-${index}`"
                    surface="muted"
                  >
                    <div class="grid grid-cols-1 gap-2 md:grid-cols-[8rem_9rem_minmax(0,1fr)_auto]">
                      <label class="text-xs">
                        <span class="ui-field-label">节点 ID</span>
                        <Input
                          :model-value="node.id"
                          block
                          @update:model-value="node.id = normalizeGroupId($event)"
                        />
                      </label>
                      <label class="text-xs">
                        <span class="ui-field-label">名称</span>
                        <Input
                          :model-value="node.name"
                          block
                          @update:model-value="node.name = $event.trim()"
                        />
                      </label>
                      <label class="text-xs">
                        <span class="ui-field-label">代理 URL</span>
                        <Input
                          :model-value="node.url"
                          block
                          root-class="font-mono"
                          placeholder="http://user:password@host:port"
                          @update:model-value="node.url = $event.trim()"
                        />
                      </label>
                      <div class="flex items-end gap-2">
                        <Checkbox v-model="node.enabled">启用</Checkbox>
                      </div>
                    </div>
                    <div class="mt-2 flex flex-wrap items-center justify-between gap-2">
                      <label class="min-w-[12rem] flex-1 text-xs">
                        <span class="ui-field-label">备注</span>
                        <Input
                          :model-value="node.notes || ''"
                          block
                          placeholder="可选"
                          @update:model-value="node.notes = $event.trim()"
                        />
                      </label>
                      <div class="flex items-end gap-2 pt-5">
                        <Button
                          size="xs"
                          variant="outline"
                          :disabled="!editingGroupId || !node.url || testingKey === `group:${editingGroupId}:${node.id}`"
                          @click="testProxyGroupNode({ id: editingGroupId, name: groupForm.name, strategy: 'time_window', rotation_interval_minutes: groupForm.rotation_interval_minutes, enabled: groupForm.enabled, notes: groupForm.notes, nodes: groupForm.nodes }, node)"
                        >
                          {{ testingKey === `group:${editingGroupId}:${node.id}` ? '检测中...' : '检测' }}
                        </Button>
                        <Button size="xs" variant="outline" root-class="text-rose-600" @click="removeGroupNode(index)">
                          删除
                        </Button>
                      </div>
                    </div>
                  </FormSection>
                </div>
              </div>
      </ModalBody>

      <ModalFooter :bordered="false">
        <Button size="xs" variant="outline" root-class="min-w-14 justify-center" :disabled="savingGroupId === FORM_TEST_KEY" @click="closeGroupModal">
          取消
        </Button>
        <Button size="xs" variant="primary" root-class="min-w-14 justify-center" :disabled="savingGroupId === FORM_TEST_KEY" @click="saveProxyGroup">
          {{ savingGroupId === FORM_TEST_KEY ? '保存中...' : editingGroupId ? '更新' : '保存' }}
        </Button>
      </ModalFooter>
    </ModalShell>

  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Button, Checkbox, EmptyState, Input } from 'nanocat-ui'
import { prepareSettingsForEdit, proxyApi, settingsApi } from '@/api'
import type { ProxyGroup, ProxyNode, ProxyTestResult } from '@/api/proxy'
import { ActionRow, FormSection, ModalBody, ModalFooter, ModalHeader, ModalShell, PageLoadingState, PagePanel, PanelHeader, ProxyNodeSummaryCard, StateBadge, StateBlock, TableShell } from '@/components/ai'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import type { Settings } from '@/types/api'

type ProxyGroupForm = {
  id: string
  name: string
  rotation_interval_minutes: number
  enabled: boolean
  notes: string
  nodes: ProxyNode[]
}

const GLOBAL_TEST_KEY = '__global__'
const FORM_TEST_KEY = '__form__'

const settingsStore = useSettingsStore()
const toast = useToast()
const confirmDialog = useConfirmDialog()

const loading = ref(false)
const savingGlobal = ref(false)
const savingGroupId = ref('')
const deletingGroupId = ref('')
const testingKey = ref('')
const groupKeyword = ref('')
const showGroupModal = ref(false)
const editingGroupId = ref('')
const globalProxy = ref('')
const currentSettings = ref<Settings | null>(null)
const globalTestResult = ref<ProxyTestResult | null>(null)
const groups = ref<ProxyGroup[]>([])
const testResults = reactive<Record<string, ProxyTestResult>>({})
const groupForm = reactive<ProxyGroupForm>(createDefaultGroupForm())

const filteredGroups = computed(() => {
  const query = groupKeyword.value.trim().toLowerCase()
  const rows = [...groups.value].sort((left, right) => (
    (left.name || left.id).localeCompare(right.name || right.id, 'zh-Hans-CN')
  ))
  if (!query) return rows
  return rows.filter((item) => [
    item.id,
    item.name,
    item.notes,
    ...item.nodes.flatMap((node) => [node.id, node.name, node.url, node.notes]),
  ].some((value) => String(value || '').toLowerCase().includes(query)))
})

function createDefaultNode(index = 0): ProxyNode {
  return {
    id: `node-${index + 1}`,
    name: `节点 ${index + 1}`,
    url: '',
    enabled: true,
    notes: '',
  }
}

function createDefaultGroupForm(): ProxyGroupForm {
  return {
    id: '',
    name: '',
    rotation_interval_minutes: 5,
    enabled: true,
    notes: '',
    nodes: [createDefaultNode(0)],
  }
}

function normalizeReferenceId(value: string) {
  return value
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/^[-._]+|[-._]+$/g, '')
    .slice(0, 64)
}

function normalizeGroupId(value: string) {
  return normalizeReferenceId(value)
}

function normalizeRotationMinutes(value: unknown) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 5
  return Math.max(0, Math.min(1440, Math.round(parsed * 100) / 100))
}

function normalizeGroupNode(item: ProxyNode, index: number): ProxyNode {
  const id = normalizeGroupId(item.id || item.name || `node-${index + 1}`) || `node-${index + 1}`
  return {
    id,
    name: String(item.name || id).trim(),
    url: String(item.url || '').trim(),
    enabled: item.enabled !== false,
    last_latency_ms: Number(item.last_latency_ms || 0),
    fail_count: Number(item.fail_count || 0),
    last_error: String(item.last_error || '').trim(),
    last_checked_at: String(item.last_checked_at || '').trim(),
    last_error_at: String(item.last_error_at || '').trim(),
    cooldown_until: String(item.cooldown_until || '').trim(),
    notes: String(item.notes || '').trim(),
  }
}

function normalizeGroup(item: ProxyGroup): ProxyGroup {
  const id = normalizeGroupId(item.id || item.name || '')
  return {
    id,
    name: String(item.name || item.id || '').trim(),
    strategy: item.strategy || 'time_window',
    rotation_interval_minutes: normalizeRotationMinutes(item.rotation_interval_minutes ?? 5),
    enabled: item.enabled !== false,
    notes: String(item.notes || '').trim(),
    nodes: Array.isArray(item.nodes)
      ? item.nodes.map(normalizeGroupNode).filter((node) => node.id)
      : [],
  }
}

function updateGroups(items: ProxyGroup[]) {
  groups.value = Array.isArray(items) ? items.map(normalizeGroup).filter((item) => item.id) : []
}

async function loadData() {
  loading.value = true
  try {
    const [settings, groupResponse] = await Promise.all([
      settingsApi.get(),
      proxyApi.listGroups(),
    ])
    currentSettings.value = prepareSettingsForEdit(settings)
    settingsStore.$patch({ settings })
    globalProxy.value = String(settings.basic?.proxy || settings.proxy || '').trim()
    globalTestResult.value = null
    updateGroups(groupResponse.groups || [])
  } catch (error: any) {
    toast.error(error.message || '加载代理配置失败')
  } finally {
    loading.value = false
  }
}

async function saveGlobalProxy() {
  if (!currentSettings.value) {
    toast.warning('配置尚未加载完成')
    return
  }
  const confirmed = await confirmDialog.ask({
    title: '确认保存全局代理',
    message: '即将保存全局代理配置。未单独指定代理的账号后续请求会受到影响，是否继续？',
    confirmText: '保存',
    cancelText: '取消',
  })
  if (!confirmed) return

  savingGlobal.value = true
  try {
    const next = prepareSettingsForEdit(currentSettings.value)
    next.proxy = globalProxy.value.trim()
    const response = await settingsStore.updateSettings(next)
    currentSettings.value = prepareSettingsForEdit(response.config || next)
    toast.success('全局代理已保存')
  } catch (error: any) {
    toast.error(error.message || '保存全局代理失败')
  } finally {
    savingGlobal.value = false
  }
}

function clearGlobalProxy() {
  globalProxy.value = ''
  globalTestResult.value = null
}

async function testGlobalProxy() {
  const url = globalProxy.value.trim()
  if (!url) {
    toast.warning('请先填写全局代理 URL')
    return
  }
  const confirmed = await confirmDialog.ask({
    title: '确认测试全局代理',
    message: '即将使用全局代理地址发起外部网络测试请求。请确认当前允许测试该代理连接。',
    confirmText: '开始测试',
    cancelText: '取消',
  })
  if (!confirmed) return

  testingKey.value = GLOBAL_TEST_KEY
  try {
    const response = await proxyApi.test(url)
    globalTestResult.value = response.result
    if (response.result.ok) toast.success(`全局代理可用，耗时 ${response.result.latency_ms}ms`)
    else toast.warning(response.result.error || '全局代理测试失败')
  } catch (error: any) {
    globalTestResult.value = {
      ok: false,
      status: 0,
      latency_ms: 0,
      error: error.message || '全局代理测试失败',
    }
    toast.error(error.message || '全局代理测试失败')
  } finally {
    testingKey.value = ''
  }
}

function resetGroupForm() {
  editingGroupId.value = ''
  Object.assign(groupForm, createDefaultGroupForm())
}

function openCreateGroupModal() {
  resetGroupForm()
  showGroupModal.value = true
}

function openEditGroupModal(group: ProxyGroup) {
  editingGroupId.value = group.id
  Object.assign(groupForm, {
    id: group.id,
    name: group.name || group.id,
    rotation_interval_minutes: normalizeRotationMinutes(group.rotation_interval_minutes ?? 5),
    enabled: group.enabled !== false,
    notes: group.notes || '',
    nodes: group.nodes.length ? group.nodes.map((node, index) => normalizeGroupNode(node, index)) : [createDefaultNode(0)],
  })
  showGroupModal.value = true
}

function closeGroupModal() {
  if (savingGroupId.value === FORM_TEST_KEY) return
  showGroupModal.value = false
  resetGroupForm()
}

function addGroupNode() {
  groupForm.nodes.push(createDefaultNode(groupForm.nodes.length))
}

function removeGroupNode(index: number) {
  if (groupForm.nodes.length <= 1) {
    groupForm.nodes = [createDefaultNode(0)]
    return
  }
  groupForm.nodes.splice(index, 1)
}

async function saveProxyGroup() {
  const id = normalizeGroupId(groupForm.id || groupForm.name)
  if (!id) {
    toast.warning('请填写代理组 ID 或显示名称')
    return
  }
  const nodes = groupForm.nodes
    .map((node, index) => normalizeGroupNode(node, index))
    .filter((node) => node.url)
  if (!nodes.length) {
    toast.warning('请至少填写一个代理节点地址')
    return
  }

  savingGroupId.value = FORM_TEST_KEY
  try {
    const wasEditing = Boolean(editingGroupId.value)
    const response = await proxyApi.saveGroup({
      id,
      name: groupForm.name.trim() || id,
      strategy: 'time_window',
      rotation_interval_minutes: normalizeRotationMinutes(groupForm.rotation_interval_minutes),
      enabled: groupForm.enabled,
      notes: groupForm.notes.trim(),
      nodes,
      create_only: !editingGroupId.value,
    })
    updateGroups(response.groups || [])
    savingGroupId.value = ''
    closeGroupModal()
    toast.success(wasEditing ? '代理组已更新' : '代理组已创建')
  } catch (error: any) {
    toast.error(error.message || '保存代理组失败')
  } finally {
    savingGroupId.value = ''
  }
}

async function toggleProxyGroup(group: ProxyGroup) {
  const nextEnabled = !group.enabled
  const confirmed = await confirmDialog.ask({
    title: nextEnabled ? '确认启用代理组' : '确认停用代理组',
    message: `即将${nextEnabled ? '启用' : '停用'}代理组 ${group.name || group.id}。绑定到该组的账号组会受到影响，是否继续？`,
    confirmText: nextEnabled ? '启用' : '停用',
    cancelText: '取消',
  })
  if (!confirmed) return

  savingGroupId.value = group.id
  try {
    const response = await proxyApi.saveGroup({
      ...group,
      enabled: nextEnabled,
    })
    updateGroups(response.groups || [])
    toast.success(`代理组 ${group.name || group.id} 已${group.enabled ? '停用' : '启用'}`)
  } catch (error: any) {
    toast.error(error.message || '切换代理组失败')
  } finally {
    savingGroupId.value = ''
  }
}

async function deleteProxyGroup(group: ProxyGroup) {
  const confirmed = await confirmDialog.ask({
    title: '删除代理组',
    message: `确认删除代理组 ${group.name || group.id}？账号组里已有的绑定不会自动清空。`,
    confirmText: '确认删除',
    cancelText: '取消',
  })
  if (!confirmed) return

  deletingGroupId.value = group.id
  try {
    const response = await proxyApi.deleteGroup(group.id)
    updateGroups(response.groups || [])
    toast.success('代理组已删除')
  } catch (error: any) {
    toast.error(error.message || '删除代理组失败')
  } finally {
    deletingGroupId.value = ''
  }
}

async function testProxyGroupNode(group: ProxyGroup, node: ProxyNode) {
  const confirmed = await confirmDialog.ask({
    title: '确认测试代理节点',
    message: `即将使用代理组 ${group.name || group.id} 的节点 ${node.name || node.id} 发起外部网络测试请求。请确认当前允许测试该代理连接。`,
    confirmText: '开始测试',
    cancelText: '取消',
  })
  if (!confirmed) return

  const key = `group:${group.id}:${node.id}`
  testingKey.value = key
  try {
    const response = await proxyApi.testGroup({ id: group.id, node_id: node.id })
    if (response.groups) updateGroups(response.groups)
    const result = response.result || response.results?.[0]?.result
    if (result) testResults[key] = result
    if (result?.ok) toast.success(`节点检测通过，耗时 ${result.latency_ms}ms`)
    else toast.warning(result?.error || '节点检测失败')
  } catch (error: any) {
    testResults[key] = {
      ok: false,
      status: 0,
      latency_ms: 0,
      error: error.message || '节点检测失败',
    }
    toast.error(error.message || '节点检测失败')
  } finally {
    testingKey.value = ''
  }
}

async function testProxyGroupAll(group: ProxyGroup) {
  const confirmed = await confirmDialog.ask({
    title: '确认测试代理组',
    message: `即将测试代理组 ${group.name || group.id} 内的 ${group.nodes.length} 个节点。每个节点都会发起外部网络测试请求，是否继续？`,
    confirmText: '开始测试',
    cancelText: '取消',
  })
  if (!confirmed) return

  const key = `group:${group.id}:all`
  testingKey.value = key
  try {
    const response = await proxyApi.testGroup({ id: group.id })
    if (response.groups) updateGroups(response.groups)
    const failed = (response.results || []).filter((item) => !item.result.ok)
    if (failed.length) toast.warning(`代理组检测完成，失败 ${failed.length} 个节点`)
    else toast.success(`代理组检测通过，共 ${response.results?.length || 0} 个节点`)
  } catch (error: any) {
    toast.error(error.message || '代理组检测失败')
  } finally {
    testingKey.value = ''
  }
}

function nodeTestSummary(group: ProxyGroup, node: ProxyNode) {
  const result = testResults[`group:${group.id}:${node.id}`]
  if (result?.ok) return `HTTP ${result.status || '-'} · ${result.latency_ms || 0}ms`
  if (result && !result.ok) return result.error || '检测失败'
  if (node.last_error) return node.last_error
  if (node.last_checked_at) return `${node.last_latency_ms || 0}ms`
  return '尚未测试'
}

function nodeTestClass(group: ProxyGroup, node: ProxyNode) {
  const result = testResults[`group:${group.id}:${node.id}`]
  if (result) return result.ok ? 'text-emerald-600' : 'text-rose-600'
  if (node.last_error) return 'text-rose-600'
  if (node.last_checked_at) return 'text-emerald-600'
  return 'text-muted-foreground'
}

function groupRotationSummary(group: ProxyGroup) {
  const minutes = normalizeRotationMinutes(group.rotation_interval_minutes ?? 5)
  if (minutes <= 0) return '每次新请求轮询'
  return `每 ${minutes} 分钟轮换`
}

async function copyGroupReference(id: string) {
  try {
    await navigator.clipboard.writeText(`group:${id}`)
    toast.success('代理组引用已复制')
  } catch {
    toast.warning('复制失败，请手动复制')
  }
}

onMounted(() => {
  void loadData()
})
</script>
