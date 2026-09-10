import { defineStore } from 'pinia'
import { ref } from 'vue'
import { prepareSettingsForEdit, settingsApi } from '@/api'
import type { Settings, SettingsUpdateResponse } from '@/types/api'

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<Settings | null>(null)
  const isLoading = ref(false)

  async function loadSettings() {
    isLoading.value = true
    try {
      settings.value = await settingsApi.get()
    } finally {
      isLoading.value = false
    }
  }

  async function updateSettings(newSettings: Settings): Promise<SettingsUpdateResponse> {
    const response = await settingsApi.update(newSettings)
    settings.value = prepareSettingsForEdit(response.config || newSettings)
    return response
  }

  return {
    settings,
    isLoading,
    loadSettings,
    updateSettings,
  }
})
