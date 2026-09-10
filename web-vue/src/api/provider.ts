import apiClient from './client'

export type ProviderFieldDef = {
  name: string
  label: string
  input_type?: 'url' | 'secret' | 'text' | 'number' | string
  required?: boolean
  placeholder?: string
  description?: string
  default?: string
  options?: Array<{ value: string; label: string }>
  [key: string]: unknown
}

export type ProviderDef = {
  key: string
  label: string
  description?: string
  driver_type?: string
  category?: string
  enabled?: boolean
  is_builtin?: boolean
  fields?: ProviderFieldDef[]
  [key: string]: unknown
}

export type ProviderDefinitionsResponse = {
  data: Record<string, ProviderDef[]>
}

export type ProviderSetting = {
  type: string
  key: string
  enabled?: boolean
  config?: Record<string, unknown>
  meta?: Record<string, unknown>
  [key: string]: unknown
}

export type ProviderSettingsResponse = {
  data: Record<string, ProviderSetting[]>
}

export type ProviderTestResult = {
  ok: boolean
  message: string
  detail?: unknown
  [key: string]: unknown
}

function unwrap<T>(p: Promise<T>): Promise<T> {
  return p
}

export const providerApi = {
  listDefinitions() {
    return unwrap(apiClient.get<any, ProviderDefinitionsResponse>('/api/provider_definitions'))
  },
  listSettings() {
    return unwrap(apiClient.get<any, ProviderSettingsResponse>('/api/provider_settings'))
  },
  upsertSetting(type: string, key: string, payload: Partial<ProviderSetting>) {
    return unwrap(apiClient.put<any, ProviderSetting>(`/api/provider_settings/${type}/${key}`, payload))
  },
  testSetting(type: string, key: string, config: Record<string, unknown>) {
    return unwrap(apiClient.post<any, ProviderTestResult>(`/api/provider_settings/${type}/${key}/test`, config))
  },
}
