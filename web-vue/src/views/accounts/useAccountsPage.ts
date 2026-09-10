import { computed, onActivated, onMounted, reactive, ref, watch } from 'vue'
import { accountImportsApi, accountsApi, proxyApi } from '@/api'
import { normalizeAccountBackendStatus } from '@/api/accounts'
import { parseProxyReference, serializeProxyReference } from '@/api/proxy'
import type {
  CPAImportJob,
  CPAPool,
  CPARemoteFile,
  Sub2APIRemoteAccount,
  Sub2APIServer,
} from '@/api/accountImports'
import type { ProxyGroup, ProxyTestResult } from '@/api/proxy'
import type {
  AccountGroup,
  AccountBackendStatus,
  AccountListParams,
  AccountRefreshProgress,
  Account,
} from '@/api/accounts'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'
import { saveBlob } from '@/lib/downloads'
import {
  getNumberPreference,
  getStringPreference,
  preferenceKeys,
  setNumberPreference,
  setStringPreference,
} from '@/lib/preferences'
import { statusCategory, type AccountStatusFilter } from './viewUtils'

type AccountsViewMode = 'list' | 'cards'
type BulkAction = 'refresh' | 'reset' | 'enable' | 'disable' | 'delete'
type BulkProgressKind = 'refresh' | 'mutation'
type AccountProxyMode = 'global' | 'direct' | 'group' | 'custom'
export type AccountImportMode = 'access_token' | 'session_json' | 'cpa_json' | 'remote_cpa' | 'sub2api'

type AccountGroupForm = {
  id: string
  name: string
  proxy: string
  proxy_group_id: string
  enabled: boolean
  notes: string
}

type AccountForm = {
  id: string
  access_token: string
  type: string
  source_type: string
  group_id: string
  proxy: string
  quota: string
  status: AccountBackendStatus
}

const ACCOUNT_PAGE_SIZE_OPTIONS = [20, 50, 100]
const DEFAULT_PAGE_SIZE = 20
const REFRESH_BATCH_SIZE = 20
const IMPORT_BATCH_SIZE = 20

function createDefaultForm(): AccountForm {
  return {
    id: '',
    access_token: '',
    type: 'free',
    source_type: 'web',
    group_id: '',
    proxy: '',
    quota: '',
    status: '正常',
  }
}

function createDefaultAccountGroupForm(): AccountGroupForm {
  return {
    id: '',
    name: '',
    proxy: '',
    proxy_group_id: '',
    enabled: true,
    notes: '',
  }
}

function stableGroupNameHash(value: string) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}

function createAccountGroupId(name: string) {
  const hash = stableGroupNameHash(name).slice(0, 6)
  const slug = name
    .trim()
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/[-._]+/g, '-')
    .replace(/^-+|-+$/g, '')
  const base = slug ? `${slug}-${hash}` : `group-${hash}`
  return base.slice(0, 64).replace(/-+$/g, '') || `group-${hash}`
}

function normalizeAccountGroupName(name: unknown) {
  return String(name || '').trim().replace(/\s+/g, ' ').toLowerCase()
}

function normalizeErrorMessage(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error)
  const duplicateMatch = raw.match(
    /duplicate cookie principal:\s*same\s+(__Secure-[^\s]+)\s+as\s+account\s+([a-z0-9_-]+)/i
  )
  if (!duplicateMatch) return raw
  const [, principal, accountId] = duplicateMatch
  return `账号主身份重复：${principal}（已存在于账号 ${accountId}）`
}

function normalizeQuota(value: unknown): number | undefined {
  const raw = String(value ?? '').trim()
  if (!raw) return undefined
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? Math.max(0, Math.trunc(parsed)) : undefined
}

function createExportFilename(extension = 'json') {
  const now = new Date()
  const parts = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
    '-',
    String(now.getHours()).padStart(2, '0'),
    String(now.getMinutes()).padStart(2, '0'),
    String(now.getSeconds()).padStart(2, '0'),
  ]
  return `accounts-export-${parts.join('')}.${extension}`
}

function uniqueTokens(tokens: string[]) {
  return Array.from(new Set(tokens.map((token) => token.trim()).filter(Boolean)))
}

function parseTokenLines(text: string) {
  return uniqueTokens(
    text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith('#')),
  )
}

function parseSessionJsonTokens(rawText: string) {
  const text = rawText.trim()
  if (!text) throw new Error('请先粘贴 Session JSON')
  const parsed = JSON.parse(text)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Session JSON 格式不正确')
  }
  const source = parsed as Record<string, unknown>
  const token = String(source.accessToken || source.access_token || '').trim()
  if (!token) throw new Error('Session JSON 中没有找到 accessToken')
  return [token]
}

function tokenFromCPAAccount(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  const source = value as Record<string, unknown>
  return String(source.access_token || source.accessToken || '').trim()
}

function parseCPAJsonTokens(rawText: string, label: string) {
  const text = rawText.trim()
  if (!text) throw new Error(`${label} 是空文件`)
  const parsed = JSON.parse(text)
  const candidates: unknown[] = []

  if (Array.isArray(parsed)) {
    candidates.push(...parsed)
  } else if (parsed && typeof parsed === 'object') {
    if (tokenFromCPAAccount(parsed)) {
      candidates.push(parsed)
    } else {
      const source = parsed as Record<string, unknown>
      for (const key of ['accounts', 'items', 'data', 'results']) {
        const rows = source[key]
        if (Array.isArray(rows)) candidates.push(...rows)
      }
    }
  }

  const tokens = uniqueTokens(candidates.map(tokenFromCPAAccount).filter(Boolean))
  if (!tokens.length) throw new Error(`${label} 中没有找到 access_token`)
  return tokens
}

export function useAccountsPage() {
  const loading = ref(false)
  const saving = ref(false)
  const showModal = ref(false)
  const keyword = ref('')
  const statusFilter = ref<AccountStatusFilter>('all')
  const groupFilter = ref('all')
  const currentPage = ref(1)
  const pageSize = ref(DEFAULT_PAGE_SIZE)
  const editingId = ref<string | null>(null)
  const accounts = ref<Account[]>([])
  const accountListTotal = ref(0)
  const accountAllTotal = ref(0)
  const selectedIds = ref<string[]>([])
  const batchBusy = ref(false)
  const batchActionLabel = ref('')
  const viewMode = ref<AccountsViewMode>('list')
  const refreshingAccountId = ref('')
  const resettingAccountId = ref('')
  const importBusy = ref(false)
  const exportBusy = ref(false)
  const showImportModal = ref(false)
  const importMode = ref<AccountImportMode>('access_token')
  const manualTokenText = ref('')
  const sessionJsonText = ref('')
  const remoteCPAPools = ref<CPAPool[]>([])
  const remoteCPAFiles = ref<CPARemoteFile[]>([])
  const selectedCPAPoolId = ref('')
  const selectedCPAFileNames = ref<string[]>([])
  const cpaImportJob = ref<CPAImportJob | null>(null)
  const sub2apiServers = ref<Sub2APIServer[]>([])
  const sub2apiAccounts = ref<Sub2APIRemoteAccount[]>([])
  const selectedSub2APIServerId = ref('')
  const selectedSub2APIAccountIds = ref<string[]>([])
  const sub2apiImportJob = ref<CPAImportJob | null>(null)
  const accountGroups = ref<AccountGroup[]>([])
  const proxyGroups = ref<ProxyGroup[]>([])
  const accountGroupsLoading = ref(false)
  const showAccountGroupsModal = ref(false)
  const accountGroupSaving = ref(false)
  const editingAccountGroupId = ref('')
  const selectedBindGroupId = ref('')
  const proxyTesting = ref(false)
  const proxyMode = ref<AccountProxyMode>('global')
  const selectedProxyGroupId = ref('')
  const customProxyInput = ref('')
  const accountGroupProxyMode = ref<AccountProxyMode>('global')
  const selectedAccountGroupProxyGroupId = ref('')
  const accountGroupCustomProxyInput = ref('')
  const showRefreshProgress = ref(false)
  const refreshProgressTitle = ref('')
  const refreshProgress = ref<AccountRefreshProgress | null>(null)
  const refreshProgressKind = ref<BulkProgressKind>('refresh')
  const bulkStopRequested = ref(false)
  const lastLoadedAt = ref(0)
  const toast = useToast()
  const confirmDialog = useConfirmDialog()
  const form = reactive(createDefaultForm())
  const accountGroupForm = reactive(createDefaultAccountGroupForm())
  const accountStatusOptions = [
    { label: '正常', value: '正常' },
    { label: '限流', value: '限流' },
    { label: '异常', value: '异常' },
    { label: '禁用', value: '禁用' },
  ] as const

  let listReloadTimer: number | undefined
  let listWatchReady = false

  const filteredAccounts = computed(() => accounts.value)

  const pageCount = computed(() => Math.max(1, Math.ceil(accountListTotal.value / pageSize.value)))

  const pagedAccounts = computed(() => accounts.value)

  const statusFilterOptions = [
    { label: '全部状态', value: 'all' },
    { label: '正常', value: 'normal' },
    { label: '受限', value: 'limited' },
    { label: '异常', value: 'abnormal' },
    { label: '禁用', value: 'disabled' },
  ] as const

  const groupFilterOptions = computed(() => [
    { label: '全部账号组', value: 'all' },
    { label: '未分组', value: '__ungrouped__' },
    ...accountGroups.value.map((group) => ({
      label: `${group.enabled === false ? '停用 · ' : ''}${group.name || group.id}`,
      value: group.id,
    })),
  ])

  const importModeOptions = [
    { label: '导入 Access Token', value: 'access_token' },
    { label: '导入 Session JSON', value: 'session_json' },
    { label: '导入 CPA JSON 文件', value: 'cpa_json' },
    { label: '从远程 CPA 服务器导入', value: 'remote_cpa' },
    { label: '从 Sub2API 服务器导入', value: 'sub2api' },
  ] as const

  const accountProxyModeOptions = [
    { label: '使用全局代理', value: 'global' },
    { label: '强制直连', value: 'direct' },
    { label: '代理组（多节点）', value: 'group' },
    { label: '自定义代理', value: 'custom' },
  ] as const

  const selectedSet = computed(() => new Set(selectedIds.value))

  const selectedCount = computed(() => selectedIds.value.length)

  const abnormalAccountIds = computed(() => (
    accounts.value
      .filter((item) => statusCategory(item) === 'abnormal')
      .map((item) => item.id)
  ))

  const abnormalAccountCount = computed(() => abnormalAccountIds.value.length)
  const allVisibleSelected = computed(() => {
    const visible = pagedAccounts.value
      .filter((item) => !item.is_demo)
      .map((item) => item.id)
    if (!visible.length) return false
    return visible.every((id) => selectedSet.value.has(id))
  })

  const refreshProgressPercent = computed(() => {
    const progress = refreshProgress.value
    const total = Math.max(0, Number(progress?.total || 0))
    if (total <= 0) return 0
    return Math.min(100, Math.round((Math.max(0, Number(progress?.processed || 0)) / total) * 100))
  })

  const refreshProgressMetricLabel = computed(() => (
    refreshProgressKind.value === 'refresh' ? '图片总额度' : '处理账号'
  ))

  const refreshProgressMetricValue = computed(() => {
    const progress = refreshProgress.value
    if (refreshProgressKind.value === 'refresh') return progress?.total_quota ?? '-'
    return `${progress?.processed || 0} 个`
  })

  const refreshProgressStatusText = computed(() => {
    const progress = refreshProgress.value
    if (progress?.error) return '失败'
    if (progress?.done) return bulkStopRequested.value ? '已停止' : '已完成'
    if (bulkStopRequested.value) return '停止中'
    if (refreshProgressKind.value === 'refresh') return '刷新中'
    return '处理中'
  })

  const canStopRefreshProgress = computed(() => (
    showRefreshProgress.value && batchBusy.value && !refreshProgress.value?.done
  ))

  const cpaPoolOptions = computed(() => [
    { label: '选择 CPA 服务器', value: '' },
    ...remoteCPAPools.value.map((pool) => ({ label: pool.name || pool.base_url || pool.id, value: pool.id })),
  ])

  const sub2apiServerOptions = computed(() => [
    { label: '选择 Sub2API 服务器', value: '' },
    ...sub2apiServers.value.map((server) => ({ label: server.name || server.base_url || server.id, value: server.id })),
  ])

  const proxyGroupOptions = computed(() => {
    const rows = proxyGroups.value.map((group) => ({
      label: `${group.enabled === false ? '停用 · ' : ''}${group.name || group.id}${Array.isArray(group.nodes) ? ` · ${group.nodes.length} 个节点` : ''}`,
      value: group.id,
    }))
    const selectedId = selectedProxyGroupId.value
    if (selectedId && !rows.some((item) => item.value === selectedId)) {
      rows.unshift({ label: `未知代理组 · ${selectedId}`, value: selectedId })
    }
    return [
      { label: '选择代理组', value: '' },
      ...rows,
    ]
  })

  const accountGroupOptions = computed(() => [
    { label: '不绑定账号组', value: '' },
    ...accountGroups.value.map((group) => ({
      label: `${group.enabled === false ? '停用 · ' : ''}${group.name || group.id}`,
      value: group.id,
    })),
  ])

  const accountGroupProxyOptions = computed(() => {
    const rows = proxyGroups.value.map((group) => ({
      label: `${group.enabled === false ? '停用 · ' : ''}${group.name || group.id}${Array.isArray(group.nodes) ? ` · ${group.nodes.length} 个节点` : ''}`,
      value: group.id,
    }))
    const selectedId = selectedAccountGroupProxyGroupId.value
    if (selectedId && !rows.some((item) => item.value === selectedId)) {
      rows.unshift({ label: `未知代理组 · ${selectedId}`, value: selectedId })
    }
    return [
      { label: '选择代理组', value: '' },
      ...rows,
    ]
  })

  const bindAccountGroupOptions = computed(() => [
    { label: '选择账号组', value: '' },
    ...accountGroupOptions.value.slice(1),
    { label: '取消分组', value: '__ungrouped__' },
  ])

  const accountProxyPreview = computed(() => {
    const reference = parseProxyReference(form.proxy)
    if (reference.mode === 'global') return '使用全局代理'
    if (reference.mode === 'direct') return '强制直连'
    if (reference.mode === 'profile') {
      return `历史兼容引用：profile:${reference.value || '-'}`
    }
    if (reference.mode === 'group') {
      const group = proxyGroups.value.find((item) => item.id === reference.value)
      return `代理组：${group?.name || reference.value}`
    }
    return reference.value
  })

  const accountGroupProxyPreview = computed(() => {
    const reference = parseProxyReference(accountGroupForm.proxy)
    if (reference.mode === 'global') return '使用全局代理'
    if (reference.mode === 'direct') return '强制直连'
    if (reference.mode === 'profile') {
      return `历史兼容引用：profile:${reference.value || '-'}`
    }
    if (reference.mode === 'group') {
      const group = proxyGroups.value.find((item) => item.id === reference.value)
      return `代理组：${group?.name || reference.value || '-'}`
    }
    return reference.value || '自定义代理'
  })

  function setError(prefix: string, error: unknown, notify = true) {
    const message = normalizeErrorMessage(error)
    if (notify) toast.error(`${prefix}: ${message}`)
  }

  function openBulkProgress(title: string, total: number, kind: BulkProgressKind) {
    bulkStopRequested.value = false
    showRefreshProgress.value = true
    refreshProgressTitle.value = title
    refreshProgressKind.value = kind
    refreshProgress.value = {
      total,
      processed: 0,
      done: false,
      error: null,
      total_quota: kind === 'refresh' ? 0 : undefined,
      result: null,
    }
  }

  function requestStopRefreshProgress() {
    if (!canStopRefreshProgress.value) return
    bulkStopRequested.value = true
    toast.info('已请求停止，当前批次完成后会停止后续批次')
  }

  async function copyAccountToken(item: Account) {
    const token = String(item.access_token || item.cookie || '').trim()
    if (!token) {
      toast.warning('当前账号没有可复制的 Token')
      return
    }

    try {
      await navigator.clipboard.writeText(token)
      toast.success('Token 已复制')
    } catch (error) {
      setError('复制 Token 失败', error)
    }
  }

  function resetForm() {
    editingId.value = null
    Object.assign(form, createDefaultForm())
    syncProxyControlsFromValue(form.proxy)
  }

  function syncProxyControlsFromValue(value: unknown) {
    const reference = parseProxyReference(value)
    customProxyInput.value = ''
    selectedProxyGroupId.value = ''
    proxyMode.value = reference.mode === 'profile' ? 'custom' : reference.mode
    if (reference.mode === 'profile') {
      customProxyInput.value = String(value || '').trim()
      return
    }
    if (reference.mode === 'group') {
      selectedProxyGroupId.value = reference.value
      return
    }
    if (reference.mode === 'custom') {
      customProxyInput.value = reference.value
    }
  }

  function setProxyMode(mode: string) {
    const nextMode = ['global', 'direct', 'group', 'custom'].includes(mode)
      ? mode as AccountProxyMode
      : 'global'
    proxyMode.value = nextMode
    if (nextMode === 'global') {
      form.proxy = serializeProxyReference('global')
    } else if (nextMode === 'direct') {
      form.proxy = serializeProxyReference('direct')
    } else if (nextMode === 'group') {
      form.proxy = serializeProxyReference('group', selectedProxyGroupId.value)
    } else {
      form.proxy = serializeProxyReference('custom', customProxyInput.value)
    }
  }

  function selectProxyGroup(groupId: string) {
    selectedProxyGroupId.value = groupId.trim()
    proxyMode.value = 'group'
    form.proxy = serializeProxyReference('group', selectedProxyGroupId.value)
  }

  function setCustomProxyInput(value: string) {
    customProxyInput.value = value.trim()
    proxyMode.value = 'custom'
    form.proxy = serializeProxyReference('custom', customProxyInput.value)
  }

  function syncAccountGroupProxyControlsFromValue(value: unknown, legacyProxyGroupId = '') {
    const fallback = legacyProxyGroupId ? serializeProxyReference('group', legacyProxyGroupId) : ''
    const raw = String(value || '').trim() || fallback
    const reference = parseProxyReference(raw)
    accountGroupCustomProxyInput.value = ''
    selectedAccountGroupProxyGroupId.value = ''
    accountGroupProxyMode.value = reference.mode === 'profile' ? 'custom' : reference.mode
    accountGroupForm.proxy = raw
    accountGroupForm.proxy_group_id = ''
    if (reference.mode === 'profile') {
      accountGroupCustomProxyInput.value = raw
      return
    }
    if (reference.mode === 'group') {
      selectedAccountGroupProxyGroupId.value = reference.value
      accountGroupForm.proxy_group_id = reference.value
      return
    }
    if (reference.mode === 'custom') {
      accountGroupCustomProxyInput.value = reference.value
    }
  }

  function setAccountGroupProxyMode(mode: string) {
    const nextMode = ['global', 'direct', 'group', 'custom'].includes(mode)
      ? mode as AccountProxyMode
      : 'global'
    accountGroupProxyMode.value = nextMode
    accountGroupForm.proxy_group_id = ''
    if (nextMode === 'global') {
      accountGroupForm.proxy = serializeProxyReference('global')
    } else if (nextMode === 'direct') {
      accountGroupForm.proxy = serializeProxyReference('direct')
    } else if (nextMode === 'group') {
      accountGroupForm.proxy_group_id = selectedAccountGroupProxyGroupId.value
      accountGroupForm.proxy = serializeProxyReference('group', selectedAccountGroupProxyGroupId.value)
    } else {
      accountGroupForm.proxy = serializeProxyReference('custom', accountGroupCustomProxyInput.value)
    }
  }

  function selectAccountGroupProxyGroup(groupId: string) {
    selectedAccountGroupProxyGroupId.value = groupId.trim()
    accountGroupProxyMode.value = 'group'
    accountGroupForm.proxy_group_id = selectedAccountGroupProxyGroupId.value
    accountGroupForm.proxy = serializeProxyReference('group', selectedAccountGroupProxyGroupId.value)
  }

  function setAccountGroupCustomProxyInput(value: string) {
    accountGroupCustomProxyInput.value = value.trim()
    accountGroupProxyMode.value = 'custom'
    accountGroupForm.proxy_group_id = ''
    accountGroupForm.proxy = serializeProxyReference('custom', accountGroupCustomProxyInput.value)
  }

  function accountListParams(): AccountListParams {
    return {
      page: currentPage.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim(),
      status: statusFilter.value,
      group_id: groupFilter.value,
    }
  }

  function scheduleListReload(delay = 0) {
    if (!listWatchReady) return
    if (listReloadTimer !== undefined) {
      window.clearTimeout(listReloadTimer)
    }
    listReloadTimer = window.setTimeout(() => {
      listReloadTimer = undefined
      void loadData({ silentErrorToast: true })
    }, delay)
  }

  async function loadData(options?: { silentErrorToast?: boolean }) {
    loading.value = true
    try {
      const res = await accountsApi.list(accountListParams())
      accountListTotal.value = Number(res.total ?? res.accounts?.length ?? 0)
      accountAllTotal.value = Number(res.all_total ?? 0)
      accounts.value = (res.accounts || []).map((item) => ({
        ...item,
        lanes: Array.isArray(item.lanes) ? item.lanes : [],
        model_ids: {
          fast: item.model_ids?.fast || '',
          thinking: item.model_ids?.thinking || '',
          pro: item.model_ids?.pro || '',
        },
      }))
      const existingIds = new Set(accounts.value.map((item) => item.id))
      selectedIds.value = selectedIds.value.filter((id) => existingIds.has(id))
      lastLoadedAt.value = Date.now()
    } catch (error) {
      setError('加载失败', error, !options?.silentErrorToast)
    } finally {
      loading.value = false
    }
  }

  function applyAccountGroupsPayload(response: { groups?: AccountGroup[]; proxy_groups?: ProxyGroup[] }) {
    accountGroups.value = Array.isArray(response.groups)
      ? response.groups.filter((group) => group.id)
      : []
    proxyGroups.value = Array.isArray(response.proxy_groups)
      ? response.proxy_groups.filter((group) => String(group?.id || '').trim())
      : []
    if (groupFilter.value !== 'all' && groupFilter.value !== '__ungrouped__' && !accountGroups.value.some((group) => group.id === groupFilter.value)) {
      groupFilter.value = 'all'
    }
    if (selectedBindGroupId.value && !accountGroups.value.some((group) => group.id === selectedBindGroupId.value)) {
      selectedBindGroupId.value = ''
    }
  }

  async function loadAccountGroups(options?: { silentErrorToast?: boolean }) {
    accountGroupsLoading.value = true
    try {
      const response = await accountsApi.listGroups()
      applyAccountGroupsPayload(response)
    } catch (error) {
      if (!options?.silentErrorToast) {
        setError('加载账号组失败', error)
      }
    } finally {
      accountGroupsLoading.value = false
    }
  }

  function resetAccountGroupForm() {
    Object.assign(accountGroupForm, createDefaultAccountGroupForm())
    editingAccountGroupId.value = ''
    syncAccountGroupProxyControlsFromValue(accountGroupForm.proxy)
  }

  function openAccountGroupsModal() {
    showAccountGroupsModal.value = true
    resetAccountGroupForm()
    void loadAccountGroups({ silentErrorToast: true })
  }

  function closeAccountGroupsModal() {
    if (accountGroupSaving.value) return
    showAccountGroupsModal.value = false
    resetAccountGroupForm()
  }

  function editAccountGroup(group: AccountGroup) {
    const proxy = group.proxy || (group.proxy_group_id ? serializeProxyReference('group', group.proxy_group_id) : '')
    editingAccountGroupId.value = group.id
    Object.assign(accountGroupForm, {
      id: group.id,
      name: group.name || group.id,
      proxy,
      proxy_group_id: group.proxy_group_id || '',
      enabled: group.enabled !== false,
      notes: group.notes || '',
    })
    syncAccountGroupProxyControlsFromValue(proxy, group.proxy_group_id || '')
  }

  async function saveAccountGroup() {
    if (accountGroupSaving.value) return
    const name = accountGroupForm.name.trim()
    const id = (accountGroupForm.id || editingAccountGroupId.value || createAccountGroupId(name)).trim()
    if (!name) {
      toast.warning('请填写账号组名称')
      return
    }
    const normalizedName = normalizeAccountGroupName(name)
    const duplicatedName = accountGroups.value.some((group) => (
      group.id !== id &&
      normalizeAccountGroupName(group.name || group.id) === normalizedName
    ))
    if (duplicatedName) {
      toast.warning('账号组名称已存在，请换一个名称')
      return
    }
    if (accountGroupProxyMode.value === 'group' && !selectedAccountGroupProxyGroupId.value.trim()) {
      toast.warning('请选择账号组默认代理组')
      return
    }
    if (accountGroupProxyMode.value === 'custom' && !accountGroupCustomProxyInput.value.trim()) {
      toast.warning('请填写账号组自定义代理地址')
      return
    }

    accountGroupSaving.value = true
    const wasEditing = Boolean(editingAccountGroupId.value)
    try {
      const response = await accountsApi.saveGroup({
        id,
        name,
        proxy: accountGroupForm.proxy.trim(),
        proxy_group_id: accountGroupForm.proxy_group_id.trim(),
        enabled: accountGroupForm.enabled,
        notes: accountGroupForm.notes.trim(),
        create_only: !editingAccountGroupId.value,
      })
      applyAccountGroupsPayload(response)
      selectedBindGroupId.value = response.group?.id || selectedBindGroupId.value
      resetAccountGroupForm()
      toast.success(wasEditing ? '账号组已更新' : '账号组已创建')
    } catch (error) {
      setError(wasEditing ? '更新账号组失败' : '创建账号组失败', error)
    } finally {
      accountGroupSaving.value = false
    }
  }

  async function deleteAccountGroup(group: AccountGroup) {
    if (accountGroupSaving.value) return
    const accountCount = Number(group.account_count || 0)
    const confirmed = await confirmDialog.ask({
      title: '删除账号组',
      message: `确认删除账号组「${group.name || group.id}」吗？${accountCount ? `当前 ${accountCount} 个账号会变为未分组。` : '不会删除任何账号。'}`,
      confirmText: '确认删除',
      cancelText: '取消',
    })
    if (!confirmed) return

    accountGroupSaving.value = true
    try {
      const response = await accountsApi.deleteGroup(group.id)
      applyAccountGroupsPayload(response)
      await loadData({ silentErrorToast: true })
      if (editingAccountGroupId.value === group.id) resetAccountGroupForm()
      toast.success('账号组已删除')
    } catch (error) {
      setError('删除账号组失败', error)
    } finally {
      accountGroupSaving.value = false
    }
  }

  async function testAccountProxy() {
    if (proxyTesting.value) return

    const reference = parseProxyReference(form.proxy)
    if (reference.mode === 'direct') {
      toast.info('当前账号强制直连，不需要测试代理')
      return
    }

    if (proxyMode.value === 'group' && !selectedProxyGroupId.value) {
      toast.warning('请先选择代理组')
      return
    }

    if (proxyMode.value === 'custom' && !customProxyInput.value.trim()) {
      toast.warning('请先填写自定义代理地址')
      return
    }

    const confirmed = await confirmDialog.ask({
      title: '确认测试账号代理',
      message: '即将通过当前账号代理配置发起外部网络测试请求。请确认当前允许测试该代理连接。',
      confirmText: '开始测试',
      cancelText: '取消',
    })
    if (!confirmed) return

    proxyTesting.value = true
    try {
      const response: { result?: ProxyTestResult | null; results?: Array<{ result: ProxyTestResult }> } = proxyMode.value === 'group'
          ? await proxyApi.testGroup({ id: selectedProxyGroupId.value })
          : await proxyApi.test(proxyMode.value === 'custom' ? customProxyInput.value.trim() : '')
      const result = response.result || response.results?.[0]?.result
      if (!result) {
        toast.error('代理测试没有返回结果')
        return
      }
      if (result.ok) {
        toast.success(`代理可用：${result.latency_ms} ms，HTTP ${result.status}`)
      } else {
        toast.error(`代理不可用：${result.error || '未知错误'}`)
      }
    } catch (error) {
      setError('测试代理失败', error)
    } finally {
      proxyTesting.value = false
    }
  }

  function setViewMode(mode: AccountsViewMode) {
    viewMode.value = mode
    setStringPreference(preferenceKeys.accountsViewMode, mode)
  }

  function isSelected(accountId: string) {
    return selectedSet.value.has(accountId)
  }

  function toggleSelect(accountId: string, checked?: boolean) {
    const next = new Set(selectedIds.value)
    const shouldSelect = typeof checked === 'boolean' ? checked : !next.has(accountId)
    if (shouldSelect) {
      next.add(accountId)
    } else {
      next.delete(accountId)
    }
    selectedIds.value = Array.from(next)
  }

  function clearSelection() {
    selectedIds.value = []
  }

  function toggleSelectAllVisible(checked?: boolean) {
    const ids = pagedAccounts.value
      .filter((item) => !item.is_demo)
      .map((item) => item.id)
    const next = new Set(selectedIds.value)
    const shouldSelect = typeof checked === 'boolean' ? checked : !allVisibleSelected.value
    for (const id of ids) {
      if (shouldSelect) next.add(id)
      else next.delete(id)
    }
    selectedIds.value = Array.from(next)
  }

  async function setImportMode(mode: AccountImportMode) {
    importMode.value = mode
    if (mode === 'remote_cpa' && remoteCPAPools.value.length === 0) {
      await loadCPAPools()
    }
    if (mode === 'sub2api' && sub2apiServers.value.length === 0) {
      await loadSub2APIServers()
    }
  }

  async function openImportModal(mode: AccountImportMode = 'access_token') {
    showImportModal.value = true
    await setImportMode(mode)
  }

  function closeImportModal() {
    if (importBusy.value) return
    showImportModal.value = false
  }

  async function promptRemoveImportedAbnormalAccounts(importedTokens: string[], errorCount: number) {
    if (errorCount <= 0 || bulkStopRequested.value) return

    let preview: Awaited<ReturnType<typeof accountsApi.cleanupImportedAbnormalAccounts>>
    try {
      preview = await accountsApi.cleanupImportedAbnormalAccounts(importedTokens, false)
    } catch (error) {
      setError('检查本次异常账号失败，已先保留', error)
      return
    }

    if (!preview.abnormal) {
      toast.info('本次导入有刷新异常，但没有找到可清理的异常账号，可能未写入本地或状态已变化')
      return
    }

    const confirmed = await confirmDialog.ask({
      title: '移除本次异常账号？',
      message: `本次导入刷新返回 ${errorCount} 条异常。\n后端确认 ${preview.abnormal} 个本次导入账号当前状态为异常，是否直接删除？\n\n只会删除本次导入且状态为异常的账号，正常、限流和历史账号会保留。`,
      confirmText: `删除 ${preview.abnormal} 个`,
      cancelText: '先保留',
    })

    if (!confirmed) return

    try {
      const result = await accountsApi.cleanupImportedAbnormalAccounts(importedTokens, true)
      toast.success(`已移除 ${result.removed || 0} 个本次异常账号`)
    } catch (error) {
      setError('移除本次异常账号失败', error)
    } finally {
      await loadData({ silentErrorToast: true })
    }
  }

  async function importTokenBatch(tokens: string[], sourceType: string, title: string) {
    const normalizedTokens = uniqueTokens(tokens)
    if (!normalizedTokens.length) {
      toast.warning('没有可导入的 access token')
      return
    }

    const confirmed = await confirmDialog.ask({
      title,
      message: `即将导入 ${normalizedTokens.length} 个账号，已存在账号会刷新远端信息。是否继续？`,
      confirmText: '确认导入',
      cancelText: '取消',
    })
    if (!confirmed) return

    importBusy.value = true
    batchBusy.value = true
    batchActionLabel.value = title
    openBulkProgress(title, normalizedTokens.length, 'mutation')
    let addedCount = 0
    let skippedCount = 0
    let refreshedCount = 0
    let processed = 0
    const errors: string[] = []
    try {
      for (let index = 0; index < normalizedTokens.length; index += IMPORT_BATCH_SIZE) {
        if (bulkStopRequested.value) break
        const batch = normalizedTokens.slice(index, index + IMPORT_BATCH_SIZE)
        try {
          const result = await accountsApi.importAccounts(
            batch.map((accessToken) => ({
              access_token: accessToken,
              type: 'free',
              source_type: sourceType,
            })),
            sourceType,
            { refresh: true, returnItems: false },
          )
          addedCount += Number(result.added || 0)
          skippedCount += Number(result.skipped || 0)
          refreshedCount += Number(result.refreshed || 0)
          errors.push(...(Array.isArray(result.errors) ? result.errors.filter(Boolean) : []))
        } catch (error) {
          errors.push(`${batch[0]?.slice(0, 6) || '-'}... 等 ${batch.length} 个账号：${normalizeErrorMessage(error)}`)
        } finally {
          processed = Math.min(normalizedTokens.length, processed + batch.length)
          refreshProgress.value = {
            ...(refreshProgress.value || { total: normalizedTokens.length }),
            total: normalizedTokens.length,
            processed,
            done: processed >= normalizedTokens.length,
            total_quota: 0,
          }
        }
      }

      await loadData({ silentErrorToast: true })
      const stopped = bulkStopRequested.value && processed < normalizedTokens.length
      refreshProgress.value = {
        ...(refreshProgress.value || { total: normalizedTokens.length, processed }),
        total: normalizedTokens.length,
        processed,
        done: true,
        total_quota: 0,
      }
      if (stopped) {
        toast.warning(`${title}已停止：已处理 ${processed}/${normalizedTokens.length} 个`)
      } else if (errors.length > 0) {
        toast.warning(`${title}完成：新增 ${addedCount}，跳过 ${skippedCount}，刷新 ${refreshedCount}，失败 ${errors.length}`)
      } else {
        toast.success(`${title}完成：新增 ${addedCount}，跳过 ${skippedCount}，刷新 ${refreshedCount}`)
      }
      if (addedCount + skippedCount + refreshedCount > 0) {
        manualTokenText.value = ''
        sessionJsonText.value = ''
      }
      if (!stopped && errors.length > 0) {
        await promptRemoveImportedAbnormalAccounts(normalizedTokens, errors.length)
      }
    } catch (error) {
      refreshProgress.value = {
        ...(refreshProgress.value || { total: normalizedTokens.length, processed }),
        total: normalizedTokens.length,
        processed,
        done: true,
        error: normalizeErrorMessage(error),
        total_quota: 0,
      }
      setError(`${title}失败`, error)
    } finally {
      importBusy.value = false
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  async function importManualTokenText() {
    await importTokenBatch(parseTokenLines(manualTokenText.value), 'manual', '导入 Access Token')
  }

  async function importTokenTextFile(file: File | null | undefined) {
    if (!file) return
    const text = await file.text()
    manualTokenText.value = text
    await importManualTokenText()
  }

  async function importSessionJson() {
    await importTokenBatch(parseSessionJsonTokens(sessionJsonText.value), 'session_json', '导入 Session JSON')
  }

  async function importLocalCPAFiles(files: FileList | File[] | null | undefined) {
    const fileList = Array.from(files || [])
    if (!fileList.length) return
    importBusy.value = true
    try {
      const tokens: string[] = []
      for (const file of fileList) {
        const text = await file.text()
        tokens.push(...parseCPAJsonTokens(text, file.name))
      }
      importBusy.value = false
      await importTokenBatch(tokens, 'cpa_json', '导入 CPA JSON 文件')
    } catch (error) {
      setError('导入 CPA JSON 文件失败', error)
    } finally {
      importBusy.value = false
    }
  }

  async function loadCPAPools() {
    importBusy.value = true
    try {
      const response = await accountImportsApi.listCPAPools()
      remoteCPAPools.value = response.pools || []
      if (!selectedCPAPoolId.value && remoteCPAPools.value.length > 0) {
        selectedCPAPoolId.value = remoteCPAPools.value[0].id
      }
    } catch (error) {
      setError('加载 CPA 服务器失败', error)
    } finally {
      importBusy.value = false
    }
  }

  async function loadCPAFiles() {
    const poolId = selectedCPAPoolId.value
    if (!poolId) {
      toast.warning('请先选择 CPA 服务器')
      return
    }
    const confirmed = await confirmDialog.ask({
      title: '加载远程 CPA 文件',
      message: '即将访问已配置的远程 CPA 服务器并读取文件列表。请确认当前允许连接该外部服务。',
      confirmText: '确认加载',
      cancelText: '取消',
    })
    if (!confirmed) return

    importBusy.value = true
    try {
      const response = await accountImportsApi.listCPAPoolFiles(poolId)
      remoteCPAFiles.value = response.files || []
      selectedCPAFileNames.value = []
    } catch (error) {
      setError('加载 CPA 文件失败', error)
    } finally {
      importBusy.value = false
    }
  }

  function toggleCPAFile(name: string, checked?: boolean) {
    const next = new Set(selectedCPAFileNames.value)
    const shouldSelect = typeof checked === 'boolean' ? checked : !next.has(name)
    if (shouldSelect) next.add(name)
    else next.delete(name)
    selectedCPAFileNames.value = Array.from(next)
  }

  async function pollCPAImportJob(poolId: string) {
    for (let index = 0; index < 180; index += 1) {
      const response = await accountImportsApi.getCPAImportJob(poolId)
      cpaImportJob.value = response.import_job || null
      const status = cpaImportJob.value?.status
      if (status === 'completed' || status === 'failed') return cpaImportJob.value
      await new Promise((resolve) => window.setTimeout(resolve, 1000))
    }
    throw new Error('CPA 导入进度超时')
  }

  async function startRemoteCPAImport() {
    const poolId = selectedCPAPoolId.value
    const names = selectedCPAFileNames.value
    if (!poolId) {
      toast.warning('请先选择 CPA 服务器')
      return
    }
    if (!names.length) {
      toast.warning('请先选择要导入的 CPA 文件')
      return
    }

    const confirmed = await confirmDialog.ask({
      title: '确认远程 CPA 导入',
      message: `即将从远程 CPA 服务器导入 ${names.length} 个文件里的账号，并写入本地账号池。请确认远程来源可信且当前不在生产压测窗口。`,
      confirmText: '开始导入',
      cancelText: '取消',
    })
    if (!confirmed) return

    importBusy.value = true
    try {
      const start = await accountImportsApi.startCPAImport(poolId, names)
      cpaImportJob.value = start.import_job || null
      const job = await pollCPAImportJob(poolId)
      const failed = Number(job?.failed || 0)
      toast[failed > 0 ? 'warning' : 'success'](
        `远程 CPA 导入完成：新增 ${job?.added || 0}，跳过 ${job?.skipped || 0}，刷新 ${job?.refreshed || 0}，失败 ${failed}`,
      )
      await loadData({ silentErrorToast: true })
    } catch (error) {
      setError('远程 CPA 导入失败', error)
    } finally {
      importBusy.value = false
    }
  }

  async function loadSub2APIServers() {
    importBusy.value = true
    try {
      const response = await accountImportsApi.listSub2APIServers()
      sub2apiServers.value = response.servers || []
      if (!selectedSub2APIServerId.value && sub2apiServers.value.length > 0) {
        selectedSub2APIServerId.value = sub2apiServers.value[0].id
      }
    } catch (error) {
      setError('加载 Sub2API 服务器失败', error)
    } finally {
      importBusy.value = false
    }
  }

  async function loadSub2APIAccounts() {
    const serverId = selectedSub2APIServerId.value
    if (!serverId) {
      toast.warning('请先选择 Sub2API 服务器')
      return
    }
    const confirmed = await confirmDialog.ask({
      title: '加载 Sub2API 账号',
      message: '即将访问已配置的 Sub2API 服务器并读取远程 OpenAI 账号列表。请确认当前允许连接该外部服务。',
      confirmText: '确认加载',
      cancelText: '取消',
    })
    if (!confirmed) return

    importBusy.value = true
    try {
      const response = await accountImportsApi.listSub2APIServerAccounts(serverId)
      sub2apiAccounts.value = response.accounts || []
      selectedSub2APIAccountIds.value = []
    } catch (error) {
      setError('加载 Sub2API 账号失败', error)
    } finally {
      importBusy.value = false
    }
  }

  function toggleSub2APIAccount(accountId: string, checked?: boolean) {
    const next = new Set(selectedSub2APIAccountIds.value)
    const shouldSelect = typeof checked === 'boolean' ? checked : !next.has(accountId)
    if (shouldSelect) next.add(accountId)
    else next.delete(accountId)
    selectedSub2APIAccountIds.value = Array.from(next)
  }

  async function pollSub2APIImportJob(serverId: string) {
    for (let index = 0; index < 180; index += 1) {
      const response = await accountImportsApi.getSub2APIImportJob(serverId)
      sub2apiImportJob.value = response.import_job || null
      const status = sub2apiImportJob.value?.status
      if (status === 'completed' || status === 'failed') return sub2apiImportJob.value
      await new Promise((resolve) => window.setTimeout(resolve, 1000))
    }
    throw new Error('Sub2API 导入进度超时')
  }

  async function startSub2APIImport() {
    const serverId = selectedSub2APIServerId.value
    const accountIds = selectedSub2APIAccountIds.value
    if (!serverId) {
      toast.warning('请先选择 Sub2API 服务器')
      return
    }
    if (!accountIds.length) {
      toast.warning('请先选择要导入的 Sub2API 账号')
      return
    }

    const confirmed = await confirmDialog.ask({
      title: '确认 Sub2API 导入',
      message: `即将从 Sub2API 服务器导入 ${accountIds.length} 个账号，并写入本地账号池。请确认远程来源可信且当前不在生产压测窗口。`,
      confirmText: '开始导入',
      cancelText: '取消',
    })
    if (!confirmed) return

    importBusy.value = true
    try {
      const start = await accountImportsApi.startSub2APIImport(serverId, accountIds)
      sub2apiImportJob.value = start.import_job || null
      const job = await pollSub2APIImportJob(serverId)
      const failed = Number(job?.failed || 0)
      toast[failed > 0 ? 'warning' : 'success'](
        `Sub2API 导入完成：新增 ${job?.added || 0}，跳过 ${job?.skipped || 0}，刷新 ${job?.refreshed || 0}，失败 ${failed}`,
      )
      await loadData({ silentErrorToast: true })
    } catch (error) {
      setError('Sub2API 导入失败', error)
    } finally {
      importBusy.value = false
    }
  }

  async function refreshAccountsWithProgress(accountIds: string[], title: string) {
    const targetIds = Array.from(new Set(accountIds.filter(Boolean)))
    if (!targetIds.length) {
      toast.warning('没有可刷新的账号')
      return
    }

    const confirmed = await confirmDialog.ask({
      title,
      message: `即将按每批 ${REFRESH_BATCH_SIZE} 个刷新 ${targetIds.length} 个账号的信息和额度，是否继续？`,
      confirmText: '开始刷新',
      cancelText: '取消',
    })
    if (!confirmed) return

    openBulkProgress(title, targetIds.length, 'refresh')
    batchBusy.value = true
    batchActionLabel.value = title
    let processedOffset = 0
    let failedCount = 0
    const errors: string[] = []

    try {
      for (let index = 0; index < targetIds.length; index += REFRESH_BATCH_SIZE) {
        if (bulkStopRequested.value) break
        const batch = targetIds.slice(index, index + REFRESH_BATCH_SIZE)
        const result = await accountsApi.refreshAccountsWithProgress(batch, (progress) => {
          refreshProgress.value = {
            ...progress,
            total: targetIds.length,
            processed: Math.min(targetIds.length, processedOffset + Number(progress.processed || 0)),
            done: false,
          }
        })

        const batchProgress = result.progress
        const batchErrors = Array.isArray(batchProgress?.result?.errors)
          ? batchProgress.result.errors
          : []
        failedCount += batchErrors.length
        errors.push(...batchErrors.map((entry) => (
          typeof entry === 'string'
            ? entry
            : [entry.token, entry.error].filter(Boolean).join(': ')
        )).filter(Boolean))
        processedOffset += batch.length
        refreshProgress.value = {
          ...(batchProgress || refreshProgress.value || {}),
          total: targetIds.length,
          processed: Math.min(targetIds.length, processedOffset),
          done: processedOffset >= targetIds.length,
        }
        if (bulkStopRequested.value) break
      }

      await loadData({ silentErrorToast: true })
      const stopped = bulkStopRequested.value && processedOffset < targetIds.length
      refreshProgress.value = {
        ...(refreshProgress.value || { total: targetIds.length, processed: processedOffset }),
        total: targetIds.length,
        processed: stopped ? Math.min(targetIds.length, processedOffset) : targetIds.length,
        done: true,
      }
      if (stopped) {
        toast.warning(`${title}已停止，已处理 ${processedOffset}/${targetIds.length} 个账号`)
      } else if (failedCount > 0) {
        toast.warning(`${title}完成，失败 ${failedCount} 个${errors[0] ? `：${errors[0]}` : ''}`)
      } else {
        toast.success(`${title}完成，共刷新 ${targetIds.length} 个账号`)
      }
    } catch (error) {
      refreshProgress.value = {
        ...(refreshProgress.value || { total: targetIds.length, processed: processedOffset }),
        total: targetIds.length,
        processed: Math.min(targetIds.length, processedOffset),
        done: true,
        error: normalizeErrorMessage(error),
      }
      setError(`${title}失败`, error)
      await loadData({ silentErrorToast: true })
    } finally {
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  async function refreshAllAccounts() {
    await refreshAllAccountsServerPageSafe()
  }

  async function refreshSelectedAccounts() {
    await refreshAccountsWithProgress(selectedIds.value, '刷新选中账号信息和额度')
  }

  async function refreshAllAccountsServerPageSafe() {
    const title = '刷新所有账号信息和额度'
    const totalHint = accountAllTotal.value || accountListTotal.value || accounts.value.length
    if (!totalHint) {
      toast.warning('没有可刷新的账号')
      return
    }

    const confirmed = await confirmDialog.ask({
      title,
      message: `即将刷新全部 ${totalHint} 个账号的信息和额度，可能触发大量外部 ChatGPT 请求。是否继续？`,
      confirmText: '开始刷新',
      cancelText: '取消',
    })
    if (!confirmed) return

    openBulkProgress(title, totalHint, 'refresh')
    batchBusy.value = true
    batchActionLabel.value = title
    try {
      const result = await accountsApi.refreshAllAccountsWithProgress((progress) => {
        refreshProgress.value = {
          ...progress,
          total: Number(progress.total || totalHint),
          processed: Number(progress.processed || 0),
          done: false,
        }
      })
      const progress = result.progress
      const errors = Array.isArray(progress?.result?.errors) ? progress.result.errors : []
      refreshProgress.value = {
        ...(progress || refreshProgress.value || { total: totalHint }),
        total: Number(progress?.total || totalHint),
        processed: Number(progress?.processed || progress?.total || totalHint),
        done: true,
      }
      await loadData({ silentErrorToast: true })
      if (errors.length > 0) {
        toast.warning(`${title}完成，失败 ${errors.length} 个`)
      } else {
        toast.success(`${title}完成`)
      }
    } catch (error) {
      refreshProgress.value = {
        ...(refreshProgress.value || { total: totalHint, processed: 0 }),
        done: true,
        error: normalizeErrorMessage(error),
      }
      setError(`${title}失败`, error)
      await loadData({ silentErrorToast: true })
    } finally {
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  function closeRefreshProgress() {
    if (!refreshProgress.value?.done && batchBusy.value) return
    showRefreshProgress.value = false
  }

  function openCreateModal() {
    resetForm()
    void loadAccountGroups({ silentErrorToast: true })
    showModal.value = true
  }

  function openEditModal(item: Account) {
    editingId.value = item.id
    form.id = item.id
    form.access_token = item.access_token || ''
    form.type = item.type || 'free'
    form.source_type = item.source_type || 'web'
    form.group_id = item.group_id || ''
    form.proxy = item.proxy || ''
    form.quota = item.image_quota_unknown ? '' : String(item.quota ?? '')
    form.status = normalizeAccountBackendStatus(item.backend_status, item.enabled ? '正常' : '禁用')
    syncProxyControlsFromValue(form.proxy)
    void loadAccountGroups({ silentErrorToast: true })
    showModal.value = true
  }

  function closeModal() {
    showModal.value = false
    resetForm()
  }

  async function saveAccount() {
    if (!form.access_token.trim()) {
      toast.warning('Access token 不能为空')
      return
    }

    saving.value = true
    const accountIdForNotice = editingId.value || form.id || ''
    const isEditing = Boolean(editingId.value)

    try {
      const payloadId = editingId.value || form.id || undefined
      await accountsApi.upsert({
        id: payloadId,
        access_token: form.access_token.trim(),
        type: form.type.trim() || undefined,
        source_type: form.source_type.trim() || undefined,
        group_id: form.group_id.trim(),
        proxy: form.proxy.trim(),
        quota: normalizeQuota(form.quota),
        backend_status: form.status,
        enabled: form.status !== '禁用',
      })
      toast.success(isEditing ? `账号 ${accountIdForNotice} 已更新` : '账号已添加')
      closeModal()
      await loadData({ silentErrorToast: true })
    } catch (error) {
      setError('保存失败', error)
    } finally {
      saving.value = false
    }
  }

  async function toggleEnabled(item: Account) {
    const nextEnabled = !item.enabled
    const confirmed = await confirmDialog.ask({
      title: nextEnabled ? '确认启用账号' : '确认禁用账号',
      message: `即将${nextEnabled ? '启用' : '禁用'}账号 ${item.id}。这会影响该账号是否参与后续请求分配，是否继续？`,
      confirmText: nextEnabled ? '启用' : '禁用',
      cancelText: '取消',
    })
    if (!confirmed) return

    try {
      if (item.enabled) {
        await accountsApi.disable(item.id)
      } else {
        await accountsApi.enable(item.id)
      }
      toast.success(`账号 ${item.id} 已${item.enabled ? '禁用' : '启用'}`)
      await loadData({ silentErrorToast: true })
    } catch (error) {
      setError('切换状态失败', error)
    }
  }

  async function refreshToken(accountId: string) {
    const confirmed = await confirmDialog.ask({
      title: '确认刷新账号',
      message: `即将刷新账号 ${accountId} 的远端信息和额度，可能触发外部 ChatGPT 请求。是否继续？`,
      confirmText: '开始刷新',
      cancelText: '取消',
    })
    if (!confirmed) return

    refreshingAccountId.value = accountId
    toast.info(`正在刷新账号 ${accountId} 的远端信息...`)
    try {
      await accountsApi.refreshToken(accountId)
      toast.success(`账号 ${accountId} 刷新成功`)
      await loadData({ silentErrorToast: true })
    } catch (error) {
      toast.error(`账号 ${accountId} 刷新失败：${normalizeErrorMessage(error)}`)
      await loadData({ silentErrorToast: true })
    } finally {
      refreshingAccountId.value = ''
    }
  }

  async function resetAccountState(accountId: string) {
    const confirmed = await confirmDialog.ask({
      title: '重置账号状态',
      message: `是否重置账号 ${accountId} 的配额和冷却？此操作会清空本地计数并移除冷却状态。`,
      confirmText: '确认重置',
      cancelText: '取消',
    })
    if (!confirmed) return

    resettingAccountId.value = accountId
    try {
      await accountsApi.resetAccountState(accountId)
      toast.success(`账号 ${accountId} 已重置`)
      await loadData({ silentErrorToast: true })
    } catch (error) {
      toast.error(`账号 ${accountId} 重置失败：${normalizeErrorMessage(error)}`)
      await loadData({ silentErrorToast: true })
    } finally {
      resettingAccountId.value = ''
    }
  }

  async function removeAccount(accountId: string) {
    const confirmed = await confirmDialog.ask({
      title: '删除账号',
      message: `确认删除账号 ${accountId} 吗？此操作不可恢复。`,
      confirmText: '确认删除',
      cancelText: '取消',
    })
    if (!confirmed) return

    try {
      await accountsApi.delete(accountId)
      toast.success(`账号 ${accountId} 已删除`)
      await loadData({ silentErrorToast: true })
    } catch (error) {
      setError('删除失败', error)
    }
  }

  async function runBulkMutationWithProgress(
    title: string,
    targetIds: string[],
    mutateAccounts: (accountIds: string[]) => Promise<{ success_count?: number; updated?: number; removed?: number; errors?: string[] }>,
  ) {
    openBulkProgress(title, targetIds.length, 'mutation')
    batchBusy.value = true
    batchActionLabel.value = title
    let successCount = 0
    const errors: string[] = []
    const processedIds: string[] = []

    try {
      for (let index = 0; index < targetIds.length; index += REFRESH_BATCH_SIZE) {
        if (bulkStopRequested.value) break
        const batch = targetIds.slice(index, index + REFRESH_BATCH_SIZE)
        try {
          const result = await mutateAccounts(batch)
          const batchErrors = Array.isArray(result?.errors) ? result.errors.filter(Boolean) : []
          const batchSuccess = Number(result?.success_count ?? result?.updated ?? result?.removed ?? (batch.length - batchErrors.length))
          successCount += Math.max(0, Math.min(batch.length, batchSuccess || 0))
          errors.push(...batchErrors)
        } catch (error) {
          errors.push(`${batch[0]} 等 ${batch.length} 个账号：${normalizeErrorMessage(error)}`)
        } finally {
          processedIds.push(...batch)
          const processed = Math.min(targetIds.length, processedIds.length)
          refreshProgress.value = {
            ...(refreshProgress.value || { total: targetIds.length }),
            total: targetIds.length,
            processed,
            done: processed >= targetIds.length,
            total_quota: 0,
          }
        }
      }

      const processed = Math.min(targetIds.length, processedIds.length)
      const stopped = bulkStopRequested.value && processed < targetIds.length
      refreshProgress.value = {
        ...(refreshProgress.value || { total: targetIds.length, processed }),
        total: targetIds.length,
        processed,
        done: true,
        total_quota: 0,
      }
      return { success_count: successCount, errors, stopped, processed, processed_ids: processedIds }
    } finally {
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  async function runBulkAction(
    action: BulkAction,
    ids?: string[]
  ) {
    const targetIds = (ids || selectedIds.value).filter(Boolean)
    if (!targetIds.length) {
      toast.warning('请先选择账号')
      return
    }

    if (action === 'refresh') {
      await refreshAccountsWithProgress(targetIds, '批量刷新账号信息和额度')
      return
    }

    const actionMeta = {
      refresh: { title: '批量刷新账号信息', confirmText: '确认刷新', successText: '批量刷新完成' },
      reset: { title: '批量重置账号状态', confirmText: '确认重置', successText: '批量重置完成' },
      enable: { title: '批量启用账号', confirmText: '确认启用', successText: '批量启用完成' },
      disable: { title: '批量禁用账号', confirmText: '确认禁用', successText: '批量禁用完成' },
      delete: { title: '批量删除账号', confirmText: '确认删除', successText: '批量删除完成' },
    }[action]

    const confirmed = await confirmDialog.ask({
      title: actionMeta.title,
      message: `确认对选中的 ${targetIds.length} 个账号执行该操作吗？`,
      confirmText: actionMeta.confirmText,
      cancelText: '取消',
    })
    if (!confirmed) return

    try {
      let res: { success_count: number; errors: string[]; stopped?: boolean; processed?: number; processed_ids?: string[] }
      if (action === 'enable') {
        res = await runBulkMutationWithProgress(actionMeta.title, targetIds, accountsApi.bulkEnable)
      } else if (action === 'disable') {
        res = await runBulkMutationWithProgress(actionMeta.title, targetIds, accountsApi.bulkDisable)
      } else if (action === 'delete') {
        res = await runBulkMutationWithProgress(actionMeta.title, targetIds, accountsApi.bulkDelete)
      } else {
        res = await runBulkMutationWithProgress(actionMeta.title, targetIds, accountsApi.bulkEnable)
      }

      const errors = Array.isArray(res.errors) ? res.errors.filter(Boolean) : []
      if (res.stopped) {
        toast.warning(`${actionMeta.title}已停止，已处理 ${res.processed || 0}/${targetIds.length} 个账号`)
      } else if (errors.length > 0) {
        toast.warning(`${actionMeta.successText}，成功 ${res.success_count} 个，失败 ${errors.length} 个`)
      } else {
        toast.success(`${actionMeta.successText}，共 ${res.success_count} 个`)
      }
      if (action === 'delete') {
        const deletedIds = res.stopped ? (res.processed_ids || []) : targetIds
        selectedIds.value = selectedIds.value.filter((id) => !deletedIds.includes(id))
      }
      await loadData({ silentErrorToast: true })
      if (action !== 'delete' && res.stopped) {
        const processedIds = new Set(res.processed_ids || [])
        selectedIds.value = selectedIds.value.filter((id) => !processedIds.has(id))
      } else if (action !== 'delete') {
        clearSelection()
      }
    } catch (error) {
      setError(`${actionMeta.title}失败`, error)
    }
  }

  async function bindSelectedAccountsToGroup() {
    const targetIds = selectedIds.value.filter(Boolean)
    if (!targetIds.length) {
      toast.warning('请先选择账号')
      return
    }
    const nextGroupId = selectedBindGroupId.value === '__ungrouped__' ? '' : selectedBindGroupId.value.trim()
    if (selectedBindGroupId.value !== '__ungrouped__' && !nextGroupId) {
      toast.warning('请先选择要绑定的账号组')
      return
    }
    const groupName = nextGroupId
      ? accountGroups.value.find((group) => group.id === nextGroupId)?.name || nextGroupId
      : '未分组'
    const confirmed = await confirmDialog.ask({
      title: '批量绑定账号组',
      message: `确认把选中的 ${targetIds.length} 个账号绑定到 ${groupName} 吗？`,
      confirmText: '确认绑定',
      cancelText: '取消',
    })
    if (!confirmed) return

    openBulkProgress('批量绑定账号组', targetIds.length, 'mutation')
    batchBusy.value = true
    batchActionLabel.value = '批量绑定账号组'
    try {
      const result = await accountsApi.bindGroup(targetIds, nextGroupId)
      refreshProgress.value = {
        ...(refreshProgress.value || { total: targetIds.length }),
        total: targetIds.length,
        processed: targetIds.length,
        done: true,
        total_quota: 0,
      }
      toast.success(`已绑定 ${result.updated || 0} 个账号`)
      applyAccountGroupsPayload({ groups: result.groups, proxy_groups: proxyGroups.value })
      clearSelection()
      await loadData({ silentErrorToast: true })
    } catch (error) {
      refreshProgress.value = {
        ...(refreshProgress.value || { total: targetIds.length, processed: 0 }),
        total: targetIds.length,
        done: true,
        error: normalizeErrorMessage(error),
        total_quota: 0,
      }
      setError('批量绑定账号组失败', error)
    } finally {
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  async function exportAccounts(scope: 'selected' | 'all' | 'auto' = 'auto') {
    const targetIds = new Set(scope === 'all' ? [] : selectedIds.value)
    if (scope === 'all' || (scope === 'auto' && targetIds.size === 0)) {
      const totalHint = accountAllTotal.value || accountListTotal.value || accounts.value.length
      if (!totalHint) {
        toast.warning('暂无可导出的账号')
        return
      }
      const confirmed = await confirmDialog.ask({
        title: '导出全部账号认证',
        message: `即将导出全部 ${totalHint} 个账号。导出文件可能包含 refresh_token、id_token 或 access token，请只在可信环境保存。是否继续？`,
        confirmText: '确认导出',
        cancelText: '取消',
      })
      if (!confirmed) return

      exportBusy.value = true
      try {
        const blob = await accountsApi.exportAccounts([], 'json')
        saveBlob(blob, createExportFilename('json'))
        toast.success('已导出全部账号认证')
      } catch (error) {
        setError('导出失败', error)
      } finally {
        exportBusy.value = false
      }
      return
    }
    if (scope === 'selected' && targetIds.size === 0) {
      toast.warning('请先选择要导出的账号')
      return
    }

    const targetAccounts = (targetIds.size
      ? accounts.value.filter((item) => targetIds.has(item.id))
      : accounts.value
    )

    if (!targetAccounts.length) {
      toast.warning('暂无可导出的账号')
      return
    }

    const exportScopeLabel = targetIds.size === 0 ? '全部' : '选中'
    const confirmed = await confirmDialog.ask({
      title: '导出账号认证',
      message: `即将导出${exportScopeLabel} ${targetAccounts.length} 个账号。导出文件可能包含 refresh_token、id_token 或 access token，请只在可信环境保存。是否继续？`,
      confirmText: '确认导出',
      cancelText: '取消',
    })
    if (!confirmed) return

    exportBusy.value = true
    try {
      const blob = await accountsApi.exportAccounts(targetAccounts.map((item) => item.id), 'json')
      saveBlob(blob, createExportFilename('json'))
      toast.success(`已导出 ${targetAccounts.length} 个完整认证账号`)
    } catch (error) {
      const status = (error as { status?: number }).status
      if (status !== 400) {
        setError('导出失败', error)
        return
      }

      const tokens = uniqueTokens(targetAccounts.map((item) => item.access_token || ''))
      if (!tokens.length) {
        setError('导出失败', error)
        return
      }

      saveBlob(new Blob([`${tokens.join('\n')}\n`], { type: 'text/plain;charset=utf-8' }), createExportFilename('txt'))
      toast.warning(`没有可导出的完整认证 JSON，已改为导出 ${tokens.length} 个 Access Token`)
    } finally {
      exportBusy.value = false
    }
  }

  watch(
    [keyword, statusFilter, groupFilter],
    () => {
      clearSelection()
      if (currentPage.value !== 1) {
        currentPage.value = 1
        return
      }
      scheduleListReload(200)
    },
  )

  watch(pageSize, () => {
    setNumberPreference(preferenceKeys.accountsPageSize, pageSize.value)
    clearSelection()
    if (currentPage.value !== 1) {
      currentPage.value = 1
      return
    }
    scheduleListReload()
  })

  watch(currentPage, () => {
    clearSelection()
    scheduleListReload()
  })

  watch(pageCount, (count) => {
    if (currentPage.value > count) currentPage.value = count
    if (currentPage.value < 1) currentPage.value = 1
  })

  onMounted(async () => {
    const storedViewMode = getStringPreference(preferenceKeys.accountsViewMode)
    if (storedViewMode === 'list' || storedViewMode === 'cards') {
      viewMode.value = storedViewMode
    }
    pageSize.value = getNumberPreference(preferenceKeys.accountsPageSize, DEFAULT_PAGE_SIZE, {
      allowed: ACCOUNT_PAGE_SIZE_OPTIONS,
    })
    await Promise.all([
      loadData({ silentErrorToast: true }),
      loadAccountGroups({ silentErrorToast: true }),
    ])
    listWatchReady = true
  })

  onActivated(() => {
    if (!lastLoadedAt.value || Date.now() - lastLoadedAt.value > 30000) {
      void loadData({ silentErrorToast: true })
      void loadAccountGroups({ silentErrorToast: true })
    }
  })

  return {
    loading,
    saving,
    showModal,
    keyword,
    statusFilter,
    groupFilter,
    statusFilterOptions,
    groupFilterOptions,
    editingId,
    accounts,
    accountListTotal,
    accountAllTotal,
    selectedIds,
    selectedCount,
    abnormalAccountCount,
    allVisibleSelected,
    currentPage,
    pageSize,
    pageSizeOptions: ACCOUNT_PAGE_SIZE_OPTIONS,
    pageCount,
    batchBusy,
    batchActionLabel,
    viewMode,
    refreshingAccountId,
    resettingAccountId,
    importBusy,
    exportBusy,
    showImportModal,
    importMode,
    importModeOptions,
    manualTokenText,
    sessionJsonText,
    remoteCPAPools,
    remoteCPAFiles,
    selectedCPAPoolId,
    selectedCPAFileNames,
    cpaImportJob,
    sub2apiServers,
    sub2apiAccounts,
    selectedSub2APIServerId,
    selectedSub2APIAccountIds,
    sub2apiImportJob,
    accountGroups,
    proxyGroups,
    accountGroupsLoading,
    showAccountGroupsModal,
    accountGroupSaving,
    editingAccountGroupId,
    accountGroupForm,
    accountGroupOptions,
    accountGroupProxyOptions,
    bindAccountGroupOptions,
    selectedBindGroupId,
    proxyTesting,
    proxyMode,
    accountGroupProxyMode,
    accountProxyModeOptions,
    proxyGroupOptions,
    selectedProxyGroupId,
    customProxyInput,
    selectedAccountGroupProxyGroupId,
    accountGroupCustomProxyInput,
    accountProxyPreview,
    accountGroupProxyPreview,
    showRefreshProgress,
    refreshProgressTitle,
    refreshProgress,
    refreshProgressPercent,
    refreshProgressMetricLabel,
    refreshProgressMetricValue,
    refreshProgressStatusText,
    canStopRefreshProgress,
    bulkStopRequested,
    cpaPoolOptions,
    sub2apiServerOptions,
    accountStatusOptions,
    form,
    filteredAccounts,
    pagedAccounts,
    setViewMode,
    isSelected,
    toggleSelect,
    clearSelection,
    toggleSelectAllVisible,
    setImportMode,
    openImportModal,
    closeImportModal,
    loadAccountGroups,
    openAccountGroupsModal,
    closeAccountGroupsModal,
    resetAccountGroupForm,
    editAccountGroup,
    saveAccountGroup,
    deleteAccountGroup,
    testAccountProxy,
    setProxyMode,
    selectProxyGroup,
    setCustomProxyInput,
    setAccountGroupProxyMode,
    selectAccountGroupProxyGroup,
    setAccountGroupCustomProxyInput,
    importManualTokenText,
    importTokenTextFile,
    importSessionJson,
    importLocalCPAFiles,
    loadCPAPools,
    loadCPAFiles,
    toggleCPAFile,
    startRemoteCPAImport,
    loadSub2APIServers,
    loadSub2APIAccounts,
    toggleSub2APIAccount,
    startSub2APIImport,
    refreshAllAccounts,
    refreshSelectedAccounts,
    requestStopRefreshProgress,
    closeRefreshProgress,
    loadData,
    copyAccountToken,
    openCreateModal,
    openEditModal,
    closeModal,
    saveAccount,
    toggleEnabled,
    refreshToken,
    resetAccountState,
    removeAccount,
    runBulkAction,
    bindSelectedAccountsToGroup,
    exportAccounts,
  }
}
