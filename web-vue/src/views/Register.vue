<template>
  <div class="register-page">
    <PagePanel class="space-y-4">
      <PanelHeader title="注册账号" align="start">
        <template #actions>
          <StateBadge :tone="registerConfig?.enabled ? 'success' : 'muted'" shape="rounded" size="sm">
            {{ registerConfig?.enabled ? '运行中' : '已停止' }}
          </StateBadge>
          <Button
            size="sm"
            variant="primary"
            :disabled="legacySaving || !registerConfig || registerConfig.enabled"
            @click="saveLegacyConfig"
          >
            保存配置
          </Button>
        </template>
      </PanelHeader>

      <PageLoadingState
        v-if="legacyLoading && !registerConfig"
        title="正在加载注册配置"
        description="读取邮箱来源、任务参数和运行状态。"
      />

      <div v-else-if="registerConfig" class="register-layout">
        <div class="register-config-column">
          <FormSection title="任务参数" density="roomy">
            <div class="register-form-grid">
              <label class="register-field">
                <span class="register-label">任务模式</span>
                <GroupedSelectMenu
                  v-model="registerConfig.mode"
                  :groups="registerModeGroups"
                  selected-indicator="none"
                  :disabled="registerConfig.enabled"
                  block
                />
              </label>

              <label v-if="registerConfig.mode === 'total'" class="register-field">
                <span class="register-label">注册总数</span>
                <Input
                  v-model.number="registerConfig.total"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled || registerConfig.mode !== 'total'"
                />
              </label>

              <label v-else-if="registerConfig.mode === 'quota'" class="register-field">
                <span class="register-label">目标剩余额度</span>
                <Input
                  v-model.number="registerConfig.target_quota"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label v-else class="register-field">
                <span class="register-label">目标可用账号</span>
                <Input
                  v-model.number="registerConfig.target_available"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label class="register-field">
                <span class="register-label">线程数</span>
                <Input
                  v-model.number="registerConfig.threads"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label v-if="registerConfig.mode !== 'total'" class="register-field">
                <span class="register-label">检查间隔（秒）</span>
                <Input
                  v-model.number="registerConfig.check_interval"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label class="register-field">
                <span class="register-label">自动注册</span>
                <Checkbox
                  :model-value="!!registerConfig.auto_refill"
                  :disabled="registerConfig.enabled"
                  @update:model-value="registerConfig.auto_refill = !!$event"
                />
              </label>

              <label class="register-field">
                <span class="register-label">自动间隔（秒）</span>
                <Input
                  v-model.number="registerConfig.auto_refill_interval"
                  type="number"
                  min="30"
                  max="3600"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label class="register-field">
                <span class="register-label">注册代理</span>
                <GroupedSelectMenu
                  :model-value="registerProxyMode"
                  :groups="registerProxyModeGroups"
                  selected-indicator="none"
                  :disabled="registerConfig.enabled"
                  block
                  @update:model-value="setRegisterProxyMode"
                />
              </label>

              <label v-if="registerProxyMode === 'group'" class="register-field">
                <span class="register-label">代理组</span>
                <GroupedSelectMenu
                  :model-value="selectedRegisterProxyGroupId"
                  :groups="registerProxyGroupGroups"
                  selected-indicator="none"
                  :disabled="registerConfig.enabled"
                  block
                  @update:model-value="selectRegisterProxyGroup"
                />
              </label>

              <label v-else-if="registerProxyMode === 'custom' || registerProxyMode === 'warp'" class="register-field">
                <span class="register-label">自定义代理</span>
                <Input
                  :model-value="customRegisterProxyInput"
                  block
                  root-class="font-mono"
                  placeholder="http://127.0.0.1:7890"
                  :disabled="registerConfig.enabled"
                  @update:model-value="setCustomRegisterProxyInput"
                />
              </label>

              <p class="register-proxy-hint register-field--full">
                {{ registerProxyHint }}
              </p>
            </div>
          </FormSection>

          <FormSection title="邮箱请求" density="roomy">
            <div class="register-form-grid register-form-grid--mail">
              <label class="register-field">
                <span class="register-label">请求超时（秒）</span>
                <Input
                  v-model.number="registerConfig.mail.request_timeout"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label class="register-field">
                <span class="register-label">验证码等待（秒）</span>
                <Input
                  v-model.number="registerConfig.mail.wait_timeout"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label class="register-field">
                <span class="register-label">轮询间隔（秒）</span>
                <Input
                  v-model.number="registerConfig.mail.wait_interval"
                  type="number"
                  min="1"
                  step="0.2"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label class="register-field register-field--full">
                <span class="register-label">请求 User-Agent</span>
                <Input
                  v-model.trim="registerConfig.mail.user_agent"
                  block
                  root-class="font-mono"
                  placeholder="默认浏览器 UA"
                  :disabled="registerConfig.enabled"
                />
              </label>
            </div>
          </FormSection>

          <FormSection title="邮箱来源" density="roomy">
            <template #actions>
              <MetaChip v-if="enabledProviderIssueCount" size="xs" tone="danger">
                缺 {{ enabledProviderIssueCount }}
              </MetaChip>
              <MetaChip size="xs" tone="muted">已启用 {{ enabledProviderCount }} / {{ registerProviders.length }}</MetaChip>
              <Button
                size="sm"
                variant="outline"
                :disabled="registerConfig.enabled"
                @click="addProvider"
              >
                添加来源
              </Button>
            </template>

            <div class="register-provider-list">
              <FormSection
                v-for="(provider, index) in registerProviders"
                :key="providerKey(provider, index)"
                class="register-provider-card"
                surface="background"
                density="normal"
              >
                <div class="register-provider-head">
                  <div class="min-w-0">
                    <div class="register-provider-title">
                      <span>{{ providerTitle(provider, index) }}</span>
                      <MetaChip size="xs" tone="muted">{{ providerTypeLabel(providerType(provider)) }}</MetaChip>
                      <MetaChip v-if="provider.enable === false" size="xs" tone="warning">未启用</MetaChip>
                      <MetaChip v-else-if="providerRequirementMessages(provider).length" size="xs" tone="danger">
                        缺 {{ providerRequirementMessages(provider).length }} 项
                      </MetaChip>
                      <MetaChip v-else size="xs" tone="success">可启动</MetaChip>
                    </div>
                  </div>
                  <div class="register-provider-actions">
                    <Checkbox v-model="provider.enable" :disabled="registerConfig.enabled">
                      启用
                    </Checkbox>
                    <Button
                      size="sm"
                      variant="ghost"
                      :disabled="registerConfig.enabled || registerProviders.length <= 1"
                      @click="deleteProvider(index)"
                    >
                      删除
                    </Button>
                  </div>
                </div>

                <SurfaceBox
                  v-if="provider.enable !== false && providerRequirementMessages(provider).length"
                  class="register-provider-message"
                  tone="danger"
                  density="compact"
                >
                  缺少：{{ providerRequirementMessages(provider).join('、') }}
                </SurfaceBox>

                <div class="register-provider-section">
                  <div class="register-provider-section-title">基础配置</div>
                  <div class="register-form-grid register-form-grid--two">
                    <label class="register-field">
                      <span class="register-label">类型</span>
                      <GroupedSelectMenu
                        :model-value="provider.type || 'cloudmail_gen'"
                        :groups="providerTypeGroups"
                        selected-indicator="none"
                        :disabled="registerConfig.enabled"
                        block
                        @update:model-value="value => updateProviderType(index, String(value))"
                      />
                    </label>

                    <label v-if="providerUsesApiBase(provider)" class="register-field">
                      <span class="register-label">{{ apiBaseLabel(provider) }}</span>
                      <Input
                        v-model.trim="provider.api_base"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        :placeholder="apiBasePlaceholder(provider)"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'cloudmail_gen'" class="register-field">
                      <span class="register-label">管理员邮箱</span>
                      <Input v-model.trim="provider.admin_email" block :disabled="registerConfig.enabled" />
                    </label>

                    <label v-if="providerUsesAdminPassword(provider)" class="register-field">
                      <span class="register-label">{{ providerType(provider) === 'ddg_mail' ? 'CF Admin Password' : 'Admin Password' }}</span>
                      <Input
                        v-model.trim="provider.admin_password"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                      />
                    </label>

                    <label v-if="providerUsesApiKey(provider)" class="register-field">
                      <span class="register-label">API Key</span>
                      <Input
                        v-model.trim="provider.api_key"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                      />
                    </label>

                    <!-- 迈巢邮箱：内联测试按钮 -->
                    <div v-if="providerType(provider) === 'mailnest'" class="register-field register-field--full">
                      <div class="register-provider-actions">
                        <Button
                          size="sm"
                          variant="ghost"
                          :disabled="registerConfig.enabled || testingProviderIndex === index"
                          @click="testProviderInline(index, provider)"
                        >
                          {{ testingProviderIndex === index ? '测试中…' : '测试连通' }}
                        </Button>
                        <span v-if="providerTestResults[index]" class="register-provider-test-result" :class="{ 'is-ok': providerTestResults[index]?.ok }">
                          {{ providerTestResults[index]?.ok ? '✓' : '✗' }} {{ providerTestResults[index]?.message }}<span v-if="providerTestResults[index]?.detail"> · {{ providerTestResults[index]?.detail }}</span>
                        </span>
                      </div>
                    </div>

                    <label v-if="providerUsesDefaultDomain(provider)" class="register-field">
                      <span class="register-label">默认域名</span>
                      <Input
                        v-model.trim="provider.default_domain"
                        block
                        :placeholder="providerType(provider) === 'duckmail' ? 'duckmail.sbs' : ''"
                        :disabled="registerConfig.enabled"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'cloudmail_gen'" class="register-field">
                      <span class="register-label">邮箱前缀</span>
                      <Input
                        v-model.trim="provider.email_prefix"
                        block
                        :disabled="registerConfig.enabled"
                        placeholder="可选"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'moemail'" class="register-field">
                      <span class="register-label">过期时间</span>
                      <Input
                        v-model.number="provider.expiry_time"
                        type="number"
                        min="0"
                        block
                        :disabled="registerConfig.enabled"
                        placeholder="0 表示服务默认"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'ddg_mail'" class="register-field">
                      <span class="register-label">DDG Token</span>
                      <Input
                        v-model.trim="provider.ddg_token"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="DuckDuckGo Email Protection Bearer Token"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'ddg_mail'" class="register-field">
                      <span class="register-label">CF Inbox JWT</span>
                      <Input
                        v-model.trim="provider.cf_inbox_jwt"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="固定收件箱 JWT"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'ddg_mail'" class="register-field">
                      <span class="register-label">CF API Key</span>
                      <Input
                        v-model.trim="provider.cf_api_key"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="可选"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'ddg_mail'" class="register-field">
                      <span class="register-label">CF 鉴权方式</span>
                      <GroupedSelectMenu
                        v-model="provider.cf_auth_mode"
                        :groups="cfAuthModeGroups"
                        selected-indicator="none"
                        :disabled="registerConfig.enabled"
                        block
                      />
                    </label>

                    <label v-if="providerType(provider) === 'ddg_mail'" class="register-field">
                      <span class="register-label">创建路径</span>
                      <Input
                        v-model.trim="provider.cf_create_path"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="/api/new_address"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'ddg_mail'" class="register-field">
                      <span class="register-label">邮件列表路径</span>
                      <Input
                        v-model.trim="provider.cf_messages_path"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="/api/mails"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'yyds_mail'" class="register-field">
                      <span class="register-label">Subdomain</span>
                      <Input
                        :model-value="stringValue(provider.subdomain)"
                        block
                        :disabled="registerConfig.enabled"
                        @update:model-value="value => updateProviderField(index, 'subdomain', String(value || ''))"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'inbucket'" class="register-checkbox-field">
                      <Checkbox v-model="provider.random_subdomain" :disabled="registerConfig.enabled">
                        随机子域名
                      </Checkbox>
                    </label>

                    <label v-if="providerType(provider) === 'yyds_mail'" class="register-checkbox-field">
                      <Checkbox v-model="provider.wildcard" :disabled="registerConfig.enabled">
                        Wildcard
                      </Checkbox>
                    </label>
                  </div>
                </div>

                <div
                  v-if="providerUsesDomainList(provider) || providerType(provider) === 'cloudmail_gen'"
                  class="register-provider-section"
                >
                  <div class="register-provider-section-title">域名配置</div>
                  <div class="register-provider-stack">
                    <label v-if="providerUsesDomainList(provider)" class="register-field">
                      <span class="register-label">{{ domainLabel(provider) }}</span>
                      <textarea
                        class="register-textarea"
                        :disabled="registerConfig.enabled"
                        :placeholder="domainPlaceholder(provider)"
                        :value="arrayText(provider.domain)"
                        @input="updateProviderArray(index, 'domain', $event)"
                      ></textarea>
                    </label>

                    <label v-if="providerType(provider) === 'cloudmail_gen'" class="register-field">
                      <span class="register-label">子域名前缀</span>
                      <textarea
                        class="register-textarea"
                        :disabled="registerConfig.enabled"
                        placeholder="每行一个子域名前缀，留空则直接使用主域名"
                        :value="arrayText(provider.subdomain)"
                        @input="updateProviderArray(index, 'subdomain', $event)"
                      ></textarea>
                    </label>
                  </div>
                </div>

                <div v-if="providerType(provider) === 'outlook_token'" class="register-provider-section register-provider-section--soft">
                  <div class="register-provider-section-title">Outlook 邮箱池</div>

                  <div class="register-form-grid register-form-grid--three">
                    <label class="register-field">
                      <span class="register-label">读取方式</span>
                      <GroupedSelectMenu
                        v-model="provider.mode"
                        :groups="outlookModeGroups"
                        selected-indicator="none"
                        :disabled="registerConfig.enabled"
                        block
                      />
                    </label>

                    <label v-if="provider.mode !== 'graph'" class="register-field">
                      <span class="register-label">IMAP Host</span>
                      <Input
                        v-model.trim="provider.imap_host"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="outlook.office365.com"
                      />
                    </label>

                    <label class="register-field">
                      <span class="register-label">读取邮件数</span>
                      <Input
                        v-model.number="provider.message_limit"
                        type="number"
                        min="1"
                        block
                        :disabled="registerConfig.enabled"
                      />
                    </label>
                  </div>

                  <label class="register-field">
                    <span class="register-label">邮箱池导入</span>
                    <textarea
                      class="register-textarea register-textarea--tall"
                      :disabled="registerConfig.enabled"
                      :value="String(provider.mailboxes || '')"
                      placeholder="每行一个：邮箱----密码----client_id----refresh_token"
                      @input="updateProviderField(index, 'mailboxes', ($event.target as HTMLTextAreaElement).value)"
                    ></textarea>
                  </label>

                  <div class="register-outlook-toolbar">
                    <div class="register-outlook-summary">
                      <MetaChip size="xs" tone="success">可用 {{ outlookPoolSummary(provider).available }}</MetaChip>
                      <MetaChip size="xs" tone="muted">已用 {{ outlookPoolSummary(provider).used }}</MetaChip>
                      <MetaChip size="xs" :tone="outlookPoolSummary(provider).abnormal ? 'warning' : 'success'">
                        异常 {{ outlookPoolSummary(provider).abnormal }}
                      </MetaChip>
                      <MetaChip v-if="outlookPoolSummary(provider).pending" size="xs" tone="info">
                        待保存 {{ outlookPoolSummary(provider).pending }}
                      </MetaChip>
                    </div>

                    <FloatingActionMenu
                      label="更多维护"
                      :items="outlookPoolActionItems"
                      :disabled="registerConfig.enabled || legacySaving"
                      align="right"
                      placement="auto"
                      :trigger-min-width="96"
                      @select="handleOutlookPoolAction"
                    />
                  </div>

                  <p class="register-preview-line">{{ outlookPoolHint(provider) }}</p>
                  <div v-if="outlookImportStats(provider)" class="register-outlook-import-report">
                    <div class="register-outlook-import-title">
                      {{ outlookImportSummaryText(provider) }}
                    </div>
                    <div v-if="outlookImportIssues(provider).length" class="register-outlook-import-issues">
                      <span v-for="issue in outlookImportIssues(provider)" :key="`${issue.line}-${issue.reason}-${issue.email || ''}`">
                        第 {{ issue.line || '-' }} 行：{{ issue.reason || '未识别' }}<template v-if="issue.email">（{{ issue.email }}）</template>
                      </span>
                    </div>
                  </div>

                  <details class="register-outlook-details">
                    <summary>邮箱池详情</summary>
                    <div class="register-outlook-detail-chips">
                      <MetaChip size="xs" tone="muted">已保存 {{ outlookPoolSummary(provider).saved }}</MetaChip>
                      <MetaChip size="xs" tone="info">待保存 {{ outlookPoolSummary(provider).pending }}</MetaChip>
                      <MetaChip size="xs" tone="muted">占用 {{ outlookPoolSummary(provider).inUse }}</MetaChip>
                      <MetaChip size="xs" tone="warning">需登录 {{ outlookPoolSummary(provider).loginRequired }}</MetaChip>
                      <MetaChip size="xs" tone="warning">失效 {{ outlookPoolSummary(provider).tokenInvalid }}</MetaChip>
                      <MetaChip size="xs" tone="danger">失败 {{ outlookPoolSummary(provider).failed }}</MetaChip>
                    </div>
                  </details>
                </div>
              </FormSection>

          <FormSection title="代理配置" density="roomy">
            <p class="register-provider-config-hint">
              注册任务使用的代理 provider（当前=Warp 代理）。测试会经代理访问公网返回出口 IP 与延迟。
            </p>
            <div class="register-form-grid register-form-grid--two">
              <label class="register-field">
                <span class="register-label">代理类型</span>
                <GroupedSelectMenu
                  :model-value="proxyProviderKey"
                  :groups="proxyProviderGroups"
                  selected-indicator="none"
                  :disabled="registerConfig?.enabled || proxySaving || proxyTesting"
                  block
                  @update:model-value="onProxyProviderChange"
                />
              </label>
            </div>
            <div v-if="proxyCurrentDef" class="register-form-grid register-form-grid--two">
              <label v-for="field in proxyCurrentDef.fields" :key="field.name" class="register-field">
                <span class="register-label">
                  {{ field.label || field.name }}{{ field.required ? ' *' : '' }}
                </span>
                <Input
                  v-model.trim="proxyConfig[field.name]"
                  block
                  root-class="font-mono"
                  :type="field.input_type === 'secret' ? 'text' : 'text'"
                  :placeholder="field.placeholder || ''"
                  :disabled="registerConfig?.enabled || proxySaving || proxyTesting"
                />
              </label>
            </div>
            <div v-else-if="!proxyLoading" class="register-provider-empty">
              该 provider 无字段配置。
            </div>
            <div class="register-provider-actions">
              <Button
                size="sm"
                variant="ghost"
                :disabled="!proxyCurrentDef || proxyTesting || proxySaving || registerConfig?.enabled"
                @click="testProxyProvider"
              >
                {{ proxyTesting ? '测试中…' : '测试' }}
              </Button>
              <Button
                size="sm"
                variant="primary"
                :disabled="!proxyCurrentDef || proxySaving || proxyTesting || registerConfig?.enabled"
                @click="saveProxyProvider"
              >
                {{ proxySaving ? '保存中…' : '保存' }}
              </Button>
            </div>
            <p v-if="proxyTestResult" class="register-provider-test-result" :class="{ 'is-ok': proxyTestResult.ok }">
              {{ proxyTestResult.ok ? '✓' : '✗' }} {{ proxyTestResult.message }}<span v-if="proxyTestResult.detail"> · {{ proxyTestResult.detail }}</span>
            </p>
          </FormSection>
            </div>
          </FormSection>
        </div>

        <aside class="register-runtime-column">
          <FormSection title="执行控制" density="roomy" class="register-runtime-section">
            <MetricStrip
              :items="registerMetricItems"
              columns-class="grid-cols-2 md:grid-cols-4"
              density="compact"
            />

            <div class="register-runtime-actions">
              <Button
                block
                variant="primary"
                :disabled="registerActionDisabled"
                @click="toggleLegacyTask"
              >
                {{ registerConfig.enabled ? '停止' : '启动' }}
              </Button>
              <Button
                block
                variant="outline"
                :disabled="legacySaving || !registerConfig || registerConfig.enabled"
                @click="resetLegacyStats"
              >
                重置
              </Button>
            </div>

            <SurfaceBox tone="muted" density="compact">
              {{ registerRuntimeHint }}
            </SurfaceBox>

            <SurfaceBox tone="muted" density="compact" class="register-runtime-tips">
              <p>Cloudflare 拦截：可在系统设置启用 FlareSolverr 清障，并确认相关容器已启动。</p>
              <p>HTTP 400 等注册错误通常与邮箱域名风控有关，建议更换新的域名邮箱后重试。</p>
            </SurfaceBox>
          </FormSection>

          <RuntimeLogPanel
            class="register-runtime-log"
            title="实时日志"
            :lines="runtimeLogLines"
            :empty-title="'暂无日志'"
            min-height="20rem"
            max-height="min(58vh, 38rem)"
          />
        </aside>
      </div>
    </PagePanel>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Button, Checkbox, Input } from 'nanocat-ui'
import type { ActionMenuItem } from 'nanocat-ui'
import { proxyApi, providerApi } from '@/api'
import { getAuthToken } from '@/api/client'
import { parseProxyReference, serializeProxyReference, type ProxyGroup } from '@/api/proxy'
import { registerApi, type LegacyRegisterConfig, type OutlookMailboxParseStats, type RegisterProvider } from '@/api/register'
import { type ProviderDef, type ProviderFieldDef, type ProviderSetting, type ProviderTestResult } from '@/api/provider'
import { FloatingActionMenu, FormSection, MetaChip, MetricStrip, PageLoadingState, PagePanel, PanelHeader, RuntimeLogPanel, StateBadge, StateBlock, SurfaceBox, type RuntimeLogPanelLine } from '@/components/ai'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'

type RegisterMode = 'total' | 'quota' | 'available'
type OutlookResetScope = 'all' | 'failed' | 'unused'
type RegisterProxyMode = 'global' | 'direct' | 'group' | 'custom' | 'warp'

const toast = useToast()
const confirmDialog = useConfirmDialog()

const legacyLoading = ref(false)
const legacySaving = ref(false)
const pollTimer = ref<number | null>(null)
const eventSource = ref<EventSource | null>(null)
const proxyGroups = ref<ProxyGroup[]>([])
const registerProxyMode = ref<RegisterProxyMode>('global')
const selectedRegisterProxyGroupId = ref('')
const customRegisterProxyInput = ref('')

// ===== 邮箱/代理 provider 配置框（迈巢 + warp，可扩展）=====
const mailboxDefs = ref<ProviderDef[]>([])
const proxyProviderDefs = ref<ProviderDef[]>([])
const mailboxProviderKey = ref('mailnest')
const proxyProviderKey = ref('warp')
const mailboxConfig = ref<Record<string, string>>({})
const proxyConfig = ref<Record<string, string>>({})
const mailboxLoading = ref(false)
const proxyLoading = ref(false)
const mailboxSaving = ref(false)
const proxySaving = ref(false)
const mailboxTesting = ref(false)
const proxyTesting = ref(false)
const mailboxTestResult = ref<ProviderTestResult | null>(null)
const proxyTestResult = ref<ProviderTestResult | null>(null)

// 内联测试：在邮箱来源卡片内测试 provider 连通
const testingProviderIndex = ref<number | null>(null)
const providerTestResults = ref<Record<number, ProviderTestResult | null>>({})

const mailboxProviderGroups = computed(() => [{
  options: mailboxDefs.value.map((d) => ({ value: d.key, label: d.label || d.key })),
}])
const proxyProviderGroups = computed(() => [{
  options: proxyProviderDefs.value.map((d) => ({ value: d.key, label: d.label || d.key })),
}])
const mailboxCurrentDef = computed(() => mailboxDefs.value.find((d) => d.key === mailboxProviderKey.value) || null)
const proxyCurrentDef = computed(() => proxyProviderDefs.value.find((d) => d.key === proxyProviderKey.value) || null)

function applyProviderFields(def: ProviderDef | null, target: Record<string, string>) {
  if (!def || !Array.isArray(def.fields)) return
  for (const field of def.fields) {
    if (!(field.name in target)) target[field.name] = ''
  }
}

function buildConfigFromFields(def: ProviderDef | null, source: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (!def || !Array.isArray(def.fields)) return out
  for (const field of def.fields) {
    const raw = String(source[field.name] ?? '').trim()
    out[field.name] = raw
  }
  return out
}

function fillConfigFromSetting(setting: ProviderSetting | undefined, def: ProviderDef | null, target: Record<string, string>) {
  const cfg = (setting?.config || {}) as Record<string, unknown>
  if (!def || !Array.isArray(def.fields)) return
  for (const field of def.fields) {
    target[field.name] = String(cfg[field.name] ?? field.default ?? '')
  }
}

function onMailboxProviderChange(value: string) {
  mailboxProviderKey.value = value
  mailboxTestResult.value = null
  applyProviderFields(mailboxCurrentDef.value, mailboxConfig.value)
  void loadMailboxSetting()
}

function onProxyProviderChange(value: string) {
  proxyProviderKey.value = value
  proxyTestResult.value = null
  applyProviderFields(proxyCurrentDef.value, proxyConfig.value)
  void loadProxySetting()
}

async function loadProviderDefinitions() {
  mailboxLoading.value = true
  proxyLoading.value = true
  try {
    const res = await providerApi.listDefinitions()
    const data = res?.data || {}
    mailboxDefs.value = Array.isArray(data.mailbox) ? data.mailbox.filter((d) => d && String(d.key || '').trim()) : []
    proxyProviderDefs.value = Array.isArray(data.proxy) ? data.proxy.filter((d) => d && String(d.key || '').trim()) : []
    if (!mailboxDefs.value.some((d) => d.key === mailboxProviderKey.value) && mailboxDefs.value[0]) {
      mailboxProviderKey.value = mailboxDefs.value[0].key
    }
    if (!proxyProviderDefs.value.some((d) => d.key === proxyProviderKey.value) && proxyProviderDefs.value[0]) {
      proxyProviderKey.value = proxyProviderDefs.value[0].key
    }
    applyProviderFields(mailboxCurrentDef.value, mailboxConfig.value)
    applyProviderFields(proxyCurrentDef.value, proxyConfig.value)
  } catch (error: any) {
    toast.error(error?.message || '加载 provider 定义失败')
  } finally {
    mailboxLoading.value = false
    proxyLoading.value = false
  }
}

async function loadProviderSettings() {
  try {
    const res = await providerApi.listSettings()
    const data = res?.data || {}
    const mailboxList = Array.isArray(data.mailbox) ? data.mailbox : []
    const proxyList = Array.isArray(data.proxy) ? data.proxy : []

    // 回填到独立配置框 ref（代理配置框仍用）
    const mailboxSetting = mailboxList.find((s) => s && s.key === mailboxProviderKey.value)
    fillConfigFromSetting(mailboxSetting, mailboxCurrentDef.value, mailboxConfig.value)
    const proxySetting = proxyList.find((s) => s && s.key === proxyProviderKey.value)
    fillConfigFromSetting(proxySetting, proxyCurrentDef.value, proxyConfig.value)

    // 首次使用（provider_settings 为空）时给 warp 预填默认值
    if (!proxySetting && proxyProviderKey.value === 'warp') {
      if (!proxyConfig.value.url) proxyConfig.value.url = 'socks5://192.6.121.16:11010'
    }

    // 回填到邮箱来源 providers 列表：用已保存的 provider_settings 覆盖 api_base/api_key
    if (registerConfig.value?.mail?.providers) {
      for (const provider of registerConfig.value.mail.providers) {
        const ptype = provider.type || ''
        if (!ptype) continue
        const saved = mailboxList.find((s) => s && s.key === ptype)
        if (saved?.config) {
          const cfg = saved.config as Record<string, unknown>
          if (cfg.url) provider.api_base = String(cfg.url)
          if (cfg.api_key) provider.api_key = String(cfg.api_key)
        }
      }
    }
  } catch {
    // 安静失败：无保存配置时用空字段
  }
}

async function loadMailboxSetting() {
  try {
    const res = await providerApi.listSettings()
    const data = res?.data || {}
    const list = Array.isArray(data.mailbox) ? data.mailbox : []
    const setting = list.find((s) => s && s.key === mailboxProviderKey.value)
    fillConfigFromSetting(setting, mailboxCurrentDef.value, mailboxConfig.value)
  } catch {
    // ignore
  }
}

async function loadProxySetting() {
  try {
    const res = await providerApi.listSettings()
    const data = res?.data || {}
    const list = Array.isArray(data.proxy) ? data.proxy : []
    const setting = list.find((s) => s && s.key === proxyProviderKey.value)
    fillConfigFromSetting(setting, proxyCurrentDef.value, proxyConfig.value)
  } catch {
    // ignore
  }
}

async function saveMailboxProvider() {
  const def = mailboxCurrentDef.value
  if (!def) return
  mailboxSaving.value = true
  mailboxTestResult.value = null
  try {
    const config = buildConfigFromFields(def, mailboxConfig.value)
    await providerApi.upsertSetting('mailbox', def.key, { type: 'mailbox', key: def.key, enabled: true, config })
    toast.success('邮箱配置已保存')
  } catch (error: any) {
    toast.error(error?.message || '保存邮箱配置失败')
  } finally {
    mailboxSaving.value = false
  }
}

async function saveProxyProvider() {
  const def = proxyCurrentDef.value
  if (!def) return
  proxySaving.value = true
  proxyTestResult.value = null
  try {
    const config = buildConfigFromFields(def, proxyConfig.value)
    await providerApi.upsertSetting('proxy', def.key, { type: 'proxy', key: def.key, enabled: true, config })
    toast.success('代理配置已保存')
  } catch (error: any) {
    toast.error(error?.message || '保存代理配置失败')
  } finally {
    proxySaving.value = false
  }
}

async function testMailboxProvider() {
  const def = mailboxCurrentDef.value
  if (!def) return
  mailboxTesting.value = true
  mailboxTestResult.value = null
  try {
    const config = buildConfigFromFields(def, mailboxConfig.value)
    const res = await providerApi.testSetting('mailbox', def.key, config)
    mailboxTestResult.value = res || { ok: false, message: '无返回' }
  } catch (error: any) {
    mailboxTestResult.value = { ok: false, message: error?.message || '测试请求失败' }
  } finally {
    mailboxTesting.value = false
  }
}

// 内联测试：在邮箱来源卡片内测试选中的 provider 连通
async function testProviderInline(index: number, provider: RegisterProvider) {
  const type = providerType(provider)
  if (!type) return
  testingProviderIndex.value = index
  providerTestResults.value[index] = null
  try {
    // 构建 config：从 provider 对象提取 api_base / api_key 等字段
    const config: Record<string, string> = {}
    if (provider.api_base) config.url = provider.api_base
    if (provider.api_key) config.api_key = provider.api_key
    const res = await providerApi.testSetting('mailbox', type, config)
    providerTestResults.value[index] = res || { ok: false, message: '无返回' }
  } catch (error: any) {
    providerTestResults.value[index] = { ok: false, message: error?.message || '测试请求失败' }
  } finally {
    testingProviderIndex.value = null
  }
}

async function testProxyProvider() {
  const def = proxyCurrentDef.value
  if (!def) return
  proxyTesting.value = true
  proxyTestResult.value = null
  try {
    const config = buildConfigFromFields(def, proxyConfig.value)
    const res = await providerApi.testSetting('proxy', def.key, config)
    proxyTestResult.value = res || { ok: false, message: '无返回' }
  } catch (error: any) {
    proxyTestResult.value = { ok: false, message: error?.message || '测试请求失败' }
  } finally {
    proxyTesting.value = false
  }
}

const defaultRegisterConfig: LegacyRegisterConfig = {
  mail: {
    request_timeout: 30,
    wait_timeout: 30,
    wait_interval: 2,
    user_agent: '',
    providers: [],
  },
  proxy: '',
  total: 10,
  threads: 3,
  mode: 'total',
  target_quota: 100,
  target_available: 10,
  check_interval: 5,
  auto_refill: false,
  auto_refill_interval: 300,
  enabled: false,
  stats: {
    success: 0,
    fail: 0,
    done: 0,
    running: 0,
    threads: 3,
    elapsed_seconds: 0,
    avg_seconds: 0,
    success_rate: 0,
    current_quota: 0,
    current_available: 0,
  },
  logs: [],
}

const registerConfig = ref<LegacyRegisterConfig | null>(null)

const registerModeOptions = [
  { value: 'total', label: '按数量注册' },
  { value: 'quota', label: '达到额度停止' },
  { value: 'available', label: '达到账号数停止' },
]
const registerModeGroups = [{ options: registerModeOptions }]
const registerProxyModeOptions = [
  { value: 'global', label: '使用全局代理' },
  { value: 'direct', label: '直连' },
  { value: 'group', label: '代理组' },
  { value: 'custom', label: '自定义代理' },
  { value: 'warp', label: 'Warp 代理' },
]
const registerProxyModeGroups = [{ options: registerProxyModeOptions }]

const providerTypeOptions = [
  { value: 'cloudmail_gen', label: 'CloudMail Gen' },
  { value: 'cloudflare_temp_email', label: 'Cloudflare Temp Email' },
  { value: 'tempmail_lol', label: 'TempMail.lol' },
  { value: 'moemail', label: 'MoEmail' },
  { value: 'inbucket', label: 'Inbucket' },
  { value: 'duckmail', label: 'DuckMail' },
  { value: 'gptmail', label: 'GPTMail' },
  { value: 'mailnest', label: '迈巢邮箱' },
  { value: 'yyds_mail', label: 'YYDS Mail' },
  { value: 'ddg_mail', label: 'DDG + CF 收件箱' },
  { value: 'outlook_token', label: 'Microsoft 邮箱凭据池' },
]
const providerTypeGroups = [{ options: providerTypeOptions }]

const cfAuthModeOptions = [
  { value: 'none', label: '不附加' },
  { value: 'bearer', label: 'Bearer' },
  { value: 'x-api-key', label: 'X-API-Key' },
  { value: 'query-key', label: 'Query key' },
]
const cfAuthModeGroups = [{ options: cfAuthModeOptions }]

const outlookModeOptions = [
  { value: 'graph', label: 'Graph API' },
  { value: 'imap', label: 'IMAP' },
  { value: 'auto', label: '自动兜底' },
]
const outlookModeGroups = [{ options: outlookModeOptions }]
const outlookPoolActionItems: ActionMenuItem[] = [
  { key: 'retry_failed', label: '重试异常邮箱' },
  { key: 'failed', label: '仅释放异常状态' },
  { key: 'unused', label: '删除未使用材料', danger: true, dividerBefore: true },
  { key: 'all', label: '重置邮箱池状态', danger: true },
]
const providerCommonKeys = ['enable', 'type', 'label'] as const
const providerTypeKeys: Record<string, string[]> = {
  cloudmail_gen: ['api_base', 'admin_email', 'admin_password', 'domain', 'subdomain', 'email_prefix'],
  cloudflare_temp_email: ['api_base', 'admin_password', 'domain'],
  tempmail_lol: ['api_key', 'domain'],
  moemail: ['api_base', 'api_key', 'domain', 'expiry_time'],
  inbucket: ['api_base', 'domain', 'random_subdomain'],
  duckmail: ['api_key', 'default_domain'],
  gptmail: ['api_key', 'default_domain'],
  mailnest: ['api_base', 'api_key'],
  yyds_mail: ['api_base', 'api_key', 'domain', 'subdomain', 'wildcard'],
  ddg_mail: ['api_base', 'ddg_token', 'cf_inbox_jwt', 'admin_password', 'cf_api_key', 'cf_auth_mode', 'cf_create_path', 'cf_messages_path'],
  outlook_token: ['mailboxes', 'mode', 'imap_host', 'message_limit'],
}
const providerLocalOnlyKeys: Record<string, string[]> = {
  outlook_token: ['mailboxes_count', 'mailboxes_preview', 'mailboxes_stats', 'mailboxes_parse_stats', 'mailboxes_import_stats'],
}

const registerProviders = computed(() => registerConfig.value?.mail.providers || [])
const registerProxyGroupOptions = computed(() => {
  const rows = proxyGroups.value.map((group) => ({
    label: `${group.enabled === false ? '停用 · ' : ''}${group.name || group.id}${Array.isArray(group.nodes) ? ` · ${group.nodes.length} 个节点` : ''}`,
    value: group.id,
  }))
  const selectedId = selectedRegisterProxyGroupId.value
  if (selectedId && !rows.some((item) => item.value === selectedId)) {
    rows.unshift({ label: `未知代理组 · ${selectedId}`, value: selectedId })
  }
  return [
    { label: '选择代理组', value: '' },
    ...rows,
  ]
})
const registerProxyGroupGroups = computed(() => [{ options: registerProxyGroupOptions.value }])
const registerProxyHint = computed(() => {
  if (registerProxyMode.value === 'direct') return '本次注册任务强制直连，不读取全局代理。'
  if (registerProxyMode.value === 'group') return '注册任务会使用所选代理组；代理组为空时不会偷偷回退到全局代理。'
  if (registerProxyMode.value === 'custom') return '仅本注册任务使用该代理地址。'
  return '默认使用系统设置里的全局代理；全局未配置时直连。'
})
const enabledProviderCount = computed(() => registerProviders.value.filter(provider => provider.enable !== false).length)
const enabledProviderIssueCount = computed(() =>
  registerProviders.value
    .filter(provider => provider.enable !== false)
    .reduce((total, provider) => total + providerRequirementMessages(provider).length, 0),
)
const registerActionDisabled = computed(() => {
  if (legacySaving.value || !registerConfig.value) return true
  if (registerConfig.value.enabled) return false
  return enabledProviderCount.value === 0 || enabledProviderIssueCount.value > 0
})
const legacyStats = computed(() => ({ ...defaultRegisterConfig.stats, ...(registerConfig.value?.stats || {}) }))
const legacyLogs = computed(() => [...(registerConfig.value?.logs || [])])
const registerRuntimeHint = computed(() => {
  if (enabledProviderCount.value === 0) return '至少启用一个邮箱来源。'
  if (enabledProviderIssueCount.value > 0) return `还有 ${enabledProviderIssueCount.value} 项必填配置未完成。`
  if (registerConfig.value?.enabled) return '任务运行中，配置已锁定。'
  return '启动前会自动保存当前配置。'
})

const registerMetricItems = computed(() => {
  const stats = legacyStats.value
  return [
    { key: 'success', label: '成功', value: stats.success || 0, meta: `成功率 ${stats.success_rate || 0}%` },
    { key: 'fail', label: '失败', value: stats.fail || 0 },
    { key: 'done', label: '完成', value: stats.done || 0 },
    { key: 'running', label: '运行 / 线程', value: `${stats.running || 0} / ${stats.threads || registerConfig.value?.threads || 0}` },
    { key: 'elapsed', label: '运行时间', value: `${stats.elapsed_seconds || 0}s` },
    { key: 'avg', label: '平均耗时', value: `${stats.avg_seconds || 0}s` },
    { key: 'quota', label: '当前额度', value: stats.current_quota || 0 },
    { key: 'available', label: '正常账号', value: stats.current_available || 0 },
  ]
})

const runtimeLogLines = computed<RuntimeLogPanelLine[]>(() => legacyLogs.value.slice().reverse().map((item, index) => ({
  key: `${item.time || 'log'}-${index}`,
  time: formatClock(item.time),
  text: item.text || '-',
  level: normalizeLogLevel(item.level),
})))

function normalizeRegisterConfig(raw: LegacyRegisterConfig): LegacyRegisterConfig {
  const mail = {
    ...defaultRegisterConfig.mail,
    ...(raw.mail || {}),
    providers: Array.isArray(raw.mail?.providers) ? raw.mail.providers.map(item => normalizeProvider(item)) : [],
  }
  if (!mail.providers.length) {
    mail.providers = [defaultProvider()]
  }
  return {
    ...defaultRegisterConfig,
    ...raw,
    auto_refill: !!raw.auto_refill,
    auto_refill_interval: Math.min(3600, Math.max(30, Number(raw.auto_refill_interval) || 300)),
    mail,
    stats: { ...defaultRegisterConfig.stats, ...(raw.stats || {}) },
    logs: Array.isArray(raw.logs) ? raw.logs : [],
  }
}

function normalizeProvider(provider: RegisterProvider): RegisterProvider {
  const type = providerType(provider)
  return {
    ...defaultProvider(type),
    ...provider,
    type,
    enable: provider.enable !== false,
  }
}

function defaultProvider(type = 'cloudmail_gen'): RegisterProvider {
  const base = { enable: true, type }
  switch (type) {
    case 'cloudmail_gen':
      return { ...base, api_base: '', admin_email: '', admin_password: '', domain: [], subdomain: [], email_prefix: '' }
    case 'cloudflare_temp_email':
      return { ...base, api_base: '', admin_password: '', domain: [] }
    case 'tempmail_lol':
      return { ...base, api_key: '', domain: [] }
    case 'moemail':
      return { ...base, api_base: '', api_key: '', domain: [], expiry_time: 0 }
    case 'inbucket':
      return { ...base, api_base: '', domain: [], random_subdomain: true }
    case 'duckmail':
      return { ...base, api_key: '', default_domain: 'duckmail.sbs' }
    case 'gptmail':
      return { ...base, api_key: '', default_domain: '' }
    case 'yyds_mail':
      return { ...base, api_base: 'https://maliapi.215.im/v1', api_key: '', domain: [], subdomain: '', wildcard: false }
    case 'ddg_mail':
      return {
        ...base,
        api_base: '',
        ddg_token: '',
        cf_inbox_jwt: '',
        admin_password: '',
        cf_api_key: '',
        cf_auth_mode: 'none',
        cf_create_path: '/api/new_address',
        cf_messages_path: '/api/mails',
      }
    case 'outlook_token':
      return {
        ...base,
        mailboxes: '',
        mode: 'auto',
        imap_host: 'outlook.office365.com',
        message_limit: 10,
      }
    default:
      return base
  }
}

function providerType(provider: RegisterProvider) {
  return String(provider.type || 'cloudmail_gen')
}

function providerKey(provider: RegisterProvider, index: number) {
  return `${providerType(provider)}-${index}`
}

function providerTitle(provider: RegisterProvider, index: number) {
  return `邮箱来源 ${index + 1}`
}

function providerTypeLabel(type: string) {
  return providerTypeOptions.find(item => item.value === type)?.label || type
}

function providerKeysForType(type: string, includeLocalOnly = false) {
  return [
    ...providerCommonKeys,
    ...(providerTypeKeys[type] || []),
    ...(includeLocalOnly ? providerLocalOnlyKeys[type] || [] : []),
  ]
}

function providerHasKnownType(type: string) {
  return Object.prototype.hasOwnProperty.call(providerTypeKeys, type)
}

function listFromDraft(value: unknown) {
  if (Array.isArray(value)) return value.map(String).map(item => item.trim()).filter(Boolean)
  return String(value || '')
    .split(/[\n,]/)
    .map(item => item.trim())
    .filter(Boolean)
}

function providerDraftValue(type: string, key: string, value: unknown) {
  if (key === 'domain') return listFromDraft(value)
  if (key === 'subdomain') {
    if (type === 'cloudmail_gen') return listFromDraft(value)
    if (type === 'yyds_mail') return Array.isArray(value) ? value.join('\n') : String(value || '')
  }
  return value
}

function providerWithTypeDraft(current: RegisterProvider, type: string): RegisterProvider {
  const defaults = defaultProvider(type)
  const next: RegisterProvider = {
    ...current,
    ...defaults,
    type,
    enable: current.enable !== false,
  }

  for (const key of providerKeysForType(type, true)) {
    if (key === 'type' || key === 'enable') continue
    if (current[key] !== undefined) {
      next[key] = providerDraftValue(type, key, current[key])
    }
  }

  next.type = type
  next.enable = current.enable !== false

  return next
}

function isFilled(value: unknown) {
  return String(value ?? '').trim().length > 0
}

function listHasValue(value: unknown) {
  if (Array.isArray(value)) return value.some(item => isFilled(item))
  return isFilled(value)
}

function providerRequirementMessages(provider: RegisterProvider) {
  const type = providerType(provider)
  const missing: string[] = []
  const requireValue = (value: unknown, label: string) => {
    if (!isFilled(value)) missing.push(label)
  }
  const requireList = (value: unknown, label: string) => {
    if (!listHasValue(value)) missing.push(label)
  }

  switch (type) {
    case 'cloudmail_gen':
      requireValue(provider.api_base, 'CloudMail URL')
      requireValue(provider.admin_email, '管理员邮箱')
      requireValue(provider.admin_password, 'Admin Password')
      requireList(provider.domain, '邮箱域名')
      break
    case 'cloudflare_temp_email':
      requireValue(provider.api_base, 'API Base')
      requireValue(provider.admin_password, 'Admin Password')
      requireList(provider.domain, '域名')
      break
    case 'moemail':
      requireValue(provider.api_base, 'API Base')
      requireValue(provider.api_key, 'API Key')
      requireList(provider.domain, '域名')
      break
    case 'inbucket':
      requireValue(provider.api_base, 'API Base')
      requireList(provider.domain, '基础域名')
      break
    case 'duckmail':
      requireValue(provider.api_key, 'API Key')
      break
    case 'gptmail':
      requireValue(provider.api_key, 'API Key')
      break
    case 'yyds_mail':
      requireValue(provider.api_key, 'API Key')
      break
    case 'ddg_mail':
      requireValue(provider.api_base, 'CF API Base')
      requireValue(provider.ddg_token, 'DDG Token')
      requireValue(provider.cf_inbox_jwt, 'CF Inbox JWT')
      break
    case 'outlook_token': {
      const savedCount = Number(provider.mailboxes_count || 0)
      if (savedCount <= 0 && pendingOutlookCount(provider) <= 0) missing.push('Microsoft 邮箱凭据池')
      break
    }
    default:
      break
  }

  return missing
}

function updateProviderType(index: number, type: string) {
  if (!registerConfig.value) return
  const providers = [...registerProviders.value]
  const current = providers[index] || {}
  providers[index] = providerWithTypeDraft(current, type)
  registerConfig.value.mail.providers = providers
}

function updateProviderField(index: number, key: string, value: unknown) {
  const provider = registerProviders.value[index]
  if (!provider) return
  provider[key] = value
}

function providerUsesApiBase(provider: RegisterProvider) {
  return ['cloudmail_gen', 'cloudflare_temp_email', 'moemail', 'inbucket', 'yyds_mail', 'ddg_mail', 'mailnest'].includes(providerType(provider))
}

function providerUsesApiKey(provider: RegisterProvider) {
  return ['tempmail_lol', 'moemail', 'duckmail', 'gptmail', 'yyds_mail', 'mailnest'].includes(providerType(provider))
}

function providerUsesAdminPassword(provider: RegisterProvider) {
  return ['cloudmail_gen', 'cloudflare_temp_email', 'ddg_mail'].includes(providerType(provider))
}

function providerUsesDefaultDomain(provider: RegisterProvider) {
  return ['duckmail', 'gptmail'].includes(providerType(provider))
}

function providerUsesDomainList(provider: RegisterProvider) {
  return ['cloudmail_gen', 'tempmail_lol', 'cloudflare_temp_email', 'moemail', 'inbucket', 'yyds_mail'].includes(providerType(provider))
}

function apiBaseLabel(provider: RegisterProvider) {
  const type = providerType(provider)
  if (type === 'cloudmail_gen') return 'CloudMail URL'
  if (type === 'ddg_mail') return 'CF API Base'
  if (type === 'mailnest') return '迈巢 API Base'
  return 'API Base'
}

function apiBasePlaceholder(provider: RegisterProvider) {
  const type = providerType(provider)
  if (type === 'yyds_mail') return 'https://maliapi.215.im/v1'
  if (type === 'mailnest') return 'http://mailnest:8787'
  return ''
}

function domainLabel(provider: RegisterProvider) {
  const type = providerType(provider)
  if (type === 'inbucket') return '基础域名'
  if (type === 'cloudmail_gen') return '邮箱域名'
  return '域名'
}

function domainPlaceholder(provider: RegisterProvider) {
  const type = providerType(provider)
  if (type === 'inbucket') return '每行一个基础域名，可配合随机子域名'
  if (type === 'cloudmail_gen') return '每行一个邮箱域名'
  if (type === 'cloudflare_temp_email') return '每行一个域名'
  if (type === 'moemail') return '每行一个域名'
  if (type === 'tempmail_lol') return '每行一个域名，可留空使用服务默认'
  if (type === 'yyds_mail') return '每行一个域名，可留空'
  return '每行一个域名'
}

function outlookPoolStats(provider: RegisterProvider) {
  return provider.mailboxes_stats || {}
}

function numeric(value: unknown) {
  return Number(value || 0) || 0
}

function pendingOutlookCount(provider: RegisterProvider) {
  return String(provider.mailboxes || '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(line => line && line.split('----').length >= 4)
    .length
}

function outlookPoolSummary(provider: RegisterProvider) {
  const stats = outlookPoolStats(provider)
  const inUse = numeric(stats.in_use)
  const loginRequired = numeric(stats.login_required)
  const tokenInvalid = numeric(stats.token_invalid)
  const failed = numeric(stats.failed)

  return {
    saved: numeric(provider.mailboxes_count),
    pending: pendingOutlookCount(provider),
    available: numeric(stats.unused),
    used: numeric(stats.used),
    inUse,
    loginRequired,
    tokenInvalid,
    failed,
    abnormal: inUse + loginRequired + tokenInvalid + failed,
  }
}

function outlookPoolHint(provider: RegisterProvider) {
  const summary = outlookPoolSummary(provider)
  if (summary.pending > 0) return `有 ${summary.pending} 个待保存，保存配置后进入 Microsoft 邮箱池。`
  if (summary.saved <= 0) return '还没有保存 Microsoft 邮箱材料。'
  if (summary.available <= 0 && summary.abnormal <= 0) return '库存已用完，请导入新的 Microsoft 邮箱材料。'
  if (summary.abnormal > 0) return `有 ${summary.abnormal} 个异常状态，可在更多维护里释放或重试。`
  return `已保存 ${summary.saved} 个 Microsoft 邮箱材料。`
}

function outlookImportStats(provider: RegisterProvider): OutlookMailboxParseStats | null {
  const stats = provider.mailboxes_import_stats
  if (!stats || typeof stats !== 'object') return null
  return stats
}

function outlookImportIssues(provider: RegisterProvider) {
  const issues = outlookImportStats(provider)?.issues
  return Array.isArray(issues) ? issues : []
}

function outlookImportSummaryText(provider: RegisterProvider) {
  const stats = outlookImportStats(provider)
  if (!stats) return ''
  const input = numeric(stats.non_empty ?? stats.raw_lines)
  const valid = numeric(stats.valid)
  const duplicates = numeric(stats.duplicates)
  const invalid = numeric(stats.invalid)
  const saved = numeric(stats.saved_total)
  return `上次导入：输入 ${input}，有效 ${valid}，重复 ${duplicates}，无效 ${invalid}，已保存 ${saved}`
}

function handleOutlookPoolAction(key: string) {
  if (key === 'retry_failed') {
    void retryFailedOutlookPool()
    return
  }
  if (key === 'failed' || key === 'unused' || key === 'all') {
    void resetOutlookPool(key)
  }
}

function addProvider() {
  if (!registerConfig.value) return
  registerConfig.value.mail.providers = [...registerProviders.value, defaultProvider()]
}

async function deleteProvider(index: number) {
  if (!registerConfig.value || registerProviders.value.length <= 1) return
  const ok = await confirmDialog.ask({
    title: '删除邮箱来源',
    message: `确认删除邮箱来源 ${index + 1} 吗？`,
    confirmText: '删除',
  })
  if (!ok) return
  registerConfig.value.mail.providers = registerProviders.value.filter((_, itemIndex) => itemIndex !== index)
}

function arrayText(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join('\n')
  return String(value || '')
}

function stringValue(value: unknown) {
  if (Array.isArray(value)) return value.join('\n')
  return String(value || '')
}

function applyRegisterConfig(config: LegacyRegisterConfig) {
  registerConfig.value = normalizeRegisterConfig(config)
  syncRegisterProxyControlsFromValue(registerConfig.value.proxy)
}

function syncRegisterProxyControlsFromValue(value: unknown) {
  const reference = parseProxyReference(value)
  customRegisterProxyInput.value = ''
  selectedRegisterProxyGroupId.value = ''
  if (reference.mode === 'group') {
    registerProxyMode.value = 'group'
    selectedRegisterProxyGroupId.value = reference.value
    return
  }
  if (reference.mode === 'direct') {
    registerProxyMode.value = 'direct'
    return
  }
  if (reference.mode === 'custom' || reference.mode === 'profile') {
    registerProxyMode.value = 'custom'
    customRegisterProxyInput.value = reference.mode === 'profile' ? String(value || '').trim() : reference.value
    return
  }
  registerProxyMode.value = 'global'
}

function setRegisterProxyMode(mode: string) {
  if (mode === 'warp') {
    customRegisterProxyInput.value = 'socks5://192.6.121.16:11010'
    registerProxyMode.value = 'warp'
    if (registerConfig.value) {
      registerConfig.value.proxy = serializeProxyReference('custom', customRegisterProxyInput.value)
    }
    return
  }
  const nextMode = ['global', 'direct', 'group', 'custom'].includes(mode)
    ? mode as RegisterProxyMode
    : 'global'
  registerProxyMode.value = nextMode
  if (!registerConfig.value) return
  if (nextMode === 'global') {
    registerConfig.value.proxy = serializeProxyReference('global')
  } else if (nextMode === 'direct') {
    registerConfig.value.proxy = serializeProxyReference('direct')
  } else if (nextMode === 'group') {
    registerConfig.value.proxy = serializeProxyReference('group', selectedRegisterProxyGroupId.value)
  } else {
    registerConfig.value.proxy = serializeProxyReference('custom', customRegisterProxyInput.value)
  }
}

function selectRegisterProxyGroup(groupId: string) {
  selectedRegisterProxyGroupId.value = String(groupId || '').trim()
  registerProxyMode.value = 'group'
  if (registerConfig.value) {
    registerConfig.value.proxy = serializeProxyReference('group', selectedRegisterProxyGroupId.value)
  }
}

function setCustomRegisterProxyInput(value: string) {
  customRegisterProxyInput.value = String(value || '').trim()
  registerProxyMode.value = 'custom'
  if (registerConfig.value) {
    registerConfig.value.proxy = serializeProxyReference('custom', customRegisterProxyInput.value)
  }
}

function updateProviderArray(index: number, key: 'domain' | 'subdomain', event: Event) {
  const provider = registerProviders.value[index]
  if (!provider) return
  const value = (event.target as HTMLTextAreaElement).value
  provider[key] = value.split(/[\n,]/).map(item => item.trim()).filter(Boolean)
}

function sanitizeProvider(provider: RegisterProvider): RegisterProvider {
  const type = providerType(provider)
  const output: RegisterProvider = {}

  if (providerHasKnownType(type)) {
    for (const key of providerKeysForType(type)) {
      if (provider[key] !== undefined) {
        output[key] = providerDraftValue(type, key, provider[key])
      }
    }
  } else {
    Object.assign(output, provider)
  }

  delete output.mailboxes_count
  delete output.mailboxes_preview
  delete output.mailboxes_stats
  delete output.mailboxes_parse_stats
  delete output.mailboxes_import_stats
  delete output.provider_ref
  return output
}

function legacyPayload(): Partial<LegacyRegisterConfig> {
  if (!registerConfig.value) return {}
  return {
    mail: {
      ...registerConfig.value.mail,
      providers: registerProviders.value.map(sanitizeProvider),
    },
    proxy: String(registerConfig.value.proxy || '').trim(),
    total: Math.max(1, Number(registerConfig.value.total) || 1),
    threads: Math.max(1, Number(registerConfig.value.threads) || 1),
    mode: (registerConfig.value.mode || 'total') as RegisterMode,
    target_quota: Math.max(1, Number(registerConfig.value.target_quota) || 1),
    target_available: Math.max(1, Number(registerConfig.value.target_available) || 1),
    check_interval: Math.max(1, Number(registerConfig.value.check_interval) || 5),
    auto_refill: !!registerConfig.value.auto_refill,
    auto_refill_interval: Math.min(3600, Math.max(30, Number(registerConfig.value.auto_refill_interval) || 300)),
  }
}

async function loadRegisterConfig(silent = false) {
  if (!silent) legacyLoading.value = true
  try {
    const response = await registerApi.getConfig()
    applyRegisterConfig(response.register)
  } catch (error: any) {
    if (!silent) toast.error(error?.message || '加载注册配置失败')
  } finally {
    if (!silent) legacyLoading.value = false
  }
}

async function loadProxyGroups() {
  try {
    const response = await proxyApi.listGroups()
    proxyGroups.value = Array.isArray(response.groups)
      ? response.groups.filter((group) => String(group?.id || '').trim())
      : []
  } catch {
    proxyGroups.value = []
  }
}

async function saveLegacyConfig() {
  if (!registerConfig.value) return
  legacySaving.value = true
  try {
    const response = await registerApi.updateConfig(legacyPayload())
    applyRegisterConfig(response.register)
    toast.success('注册配置已保存')
  } catch (error: any) {
    toast.error(error?.message || '保存注册配置失败')
  } finally {
    legacySaving.value = false
  }
}

async function toggleLegacyTask() {
  if (!registerConfig.value) return
  const starting = !registerConfig.value.enabled
  const ok = await confirmDialog.ask({
    title: starting ? '启动注册任务' : '停止注册任务',
    message: starting ? '启动前会先保存当前注册配置。确认启动吗？' : '确认请求停止当前注册任务吗？',
    confirmText: starting ? '启动' : '停止',
  })
  if (!ok) return
  legacySaving.value = true
  try {
    if (starting) {
      await registerApi.updateConfig(legacyPayload())
    }
    const response = starting ? await registerApi.startLegacy() : await registerApi.stopLegacy()
    applyRegisterConfig(response.register)
    toast.success(starting ? '注册任务已启动' : '已请求停止注册任务')
    if (starting) startLiveUpdates()
  } catch (error: any) {
    toast.error(error?.message || '切换注册任务失败')
  } finally {
    legacySaving.value = false
  }
}

async function resetLegacyStats() {
  const ok = await confirmDialog.ask({
    title: '重置注册统计',
    message: '确认清空当前注册统计和实时日志吗？',
    confirmText: '重置',
  })
  if (!ok) return
  legacySaving.value = true
  try {
    const response = await registerApi.resetLegacy()
    applyRegisterConfig(response.register)
    toast.success('注册统计已重置')
  } catch (error: any) {
    toast.error(error?.message || '重置注册统计失败')
  } finally {
    legacySaving.value = false
  }
}

async function resetOutlookPool(scope: OutlookResetScope) {
  const copy: Record<OutlookResetScope, { title: string; message: string; confirmText: string }> = {
    failed: {
      title: '释放异常状态',
      message: '清除 failed、token_invalid、login_required 和 in_use 状态，已成功使用的邮箱不会释放。',
      confirmText: '释放',
    },
    unused: {
      title: '清空未使用邮箱',
      message: '从已保存 Outlook 邮箱池中移除还没有状态记录的邮箱凭据。',
      confirmText: '清空',
    },
    all: {
      title: '重置全部邮箱状态',
      message: '清空 Outlook 邮箱池状态记录，所有已保存邮箱会重新变成可领取状态。',
      confirmText: '重置',
    },
  }
  const ok = await confirmDialog.ask(copy[scope])
  if (!ok) return
  legacySaving.value = true
  try {
    const response = await registerApi.resetOutlookPool(scope)
    applyRegisterConfig(response.register)
    toast.success('邮箱池状态已更新')
  } catch (error: any) {
    toast.error(error?.message || '更新邮箱池状态失败')
  } finally {
    legacySaving.value = false
  }
}

async function retryFailedOutlookPool() {
  const ok = await confirmDialog.ask({
    title: '重试异常邮箱',
    message: '会先释放 failed、token_invalid、login_required 和 in_use 状态，然后按当前注册任务配置启动，已成功使用的邮箱不会释放。',
    confirmText: '重试',
  })
  if (!ok) return
  legacySaving.value = true
  try {
    const resetResponse = await registerApi.resetOutlookPool('failed')
    applyRegisterConfig(resetResponse.register)
    const startResponse = await registerApi.startLegacy()
    applyRegisterConfig(startResponse.register)
    toast.success('已释放异常邮箱并启动注册任务')
  } catch (error: any) {
    toast.error(error?.message || '重试异常邮箱失败')
  } finally {
    legacySaving.value = false
  }
}

function startLiveUpdates() {
  stopLiveUpdates()
  const token = getAuthToken()
  if (!token) {
    startPolling()
    return
  }
  try {
    const baseUrl = String(import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
    const source = new EventSource(`${baseUrl}/api/register/events?token=${encodeURIComponent(token)}`)
    source.onmessage = (event) => {
      try {
        applyRegisterConfig(JSON.parse(event.data) as LegacyRegisterConfig)
      } catch {
        // ignore malformed event payload
      }
    }
    source.onerror = () => {
      stopLiveUpdates()
      startPolling()
    }
    eventSource.value = source
  } catch {
    startPolling()
  }
}

function stopLiveUpdates() {
  if (eventSource.value) {
    eventSource.value.close()
    eventSource.value = null
  }
}

function startPolling() {
  stopPolling()
  pollTimer.value = window.setInterval(async () => {
    await loadRegisterConfig(true)
    if (!registerConfig.value?.enabled) {
      stopPolling()
    }
  }, 2000)
}

function stopPolling() {
  if (pollTimer.value) {
    window.clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

function formatClock(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString()
}

function normalizeLogLevel(level?: string) {
  if (level === 'red' || level === 'error') return 'error'
  if (level === 'green' || level === 'success') return 'success'
  if (level === 'yellow' || level === 'warning') return 'warning'
  return 'info'
}

onMounted(async () => {
  await Promise.all([
    loadRegisterConfig(),
    loadProxyGroups(),
    (async () => {
      await loadProviderDefinitions()
      // 等 registerConfig 加载完再回填 provider_settings 到 providers 列表
      // loadRegisterConfig 是并行跑的，这里等它完成
    })(),
  ])
  // 此时 registerConfig 已加载，安全回填 provider_settings
  await loadProviderSettings()
  startLiveUpdates()
})

onBeforeUnmount(() => {
  stopLiveUpdates()
  stopPolling()
})
</script>

<style scoped>
.register-layout {
  display: grid;
  gap: 18px;
}

@media (min-width: 1280px) {
  .register-layout {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
  }
}

.register-config-column,
.register-runtime-column {
  min-width: 0;
}

.register-config-column {
  display: grid;
  gap: 16px;
}

.register-runtime-column {
  display: grid;
  gap: 16px;
  position: sticky;
  top: 16px;
}

.register-runtime-section {
  display: grid;
  gap: 12px;
}

.register-runtime-log {
  min-width: 0;
}

.register-runtime-tips {
  display: grid;
  gap: 4px;
  color: hsl(var(--muted-foreground));
  line-height: 1.6;
}

.register-runtime-tips p {
  margin: 0;
}

.register-form-grid {
  display: grid;
  gap: 12px;
}

@media (min-width: 720px) {
  .register-form-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .register-field--full {
    grid-column: 1 / -1;
  }

  .register-form-grid--two {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .register-form-grid--mail {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.register-form-grid--three {
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
}

.register-field {
  display: grid;
  min-width: 0;
  gap: 7px;
}

.register-label {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.register-proxy-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: hsl(var(--muted-foreground));
}

.register-checkbox-field {
  display: flex;
  min-height: 62px;
  align-items: end;
  padding-bottom: 8px;
}

.register-provider-list {
  display: grid;
  gap: 14px;
}

.register-provider-card {
  display: grid;
  gap: 14px;
}

.register-provider-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.register-provider-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 650;
  color: hsl(var(--foreground));
}

.register-provider-message {
  margin-top: -2px;
}

.register-provider-section {
  display: grid;
  gap: 10px;
}

.register-provider-section--soft {
  border: 1px solid hsl(var(--border) / 0.82);
  border-radius: 12px;
  background: hsl(var(--muted) / 0.16);
  padding: 12px;
}

.register-provider-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  line-height: 1.25;
}

.register-provider-section-title::after {
  content: "";
  height: 1px;
  min-width: 24px;
  flex: 1;
  background: hsl(var(--border) / 0.72);
}

.register-provider-stack {
  display: grid;
  gap: 12px;
}

.register-preview-line {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.45;
  color: hsl(var(--muted-foreground));
}

.register-outlook-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.register-provider-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.register-provider-actions--left {
  justify-content: flex-start;
}

.register-textarea {
  min-height: 80px;
  width: 100%;
  resize: vertical;
  border: 1px solid hsl(var(--border));
  border-radius: 12px;
  background: hsl(var(--card));
  padding: 10px 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  line-height: 1.55;
  color: hsl(var(--foreground));
  outline: none;
}

.register-textarea--tall {
  min-height: 124px;
}

.register-textarea:focus {
  border-color: hsl(var(--ring));
  box-shadow: 0 0 0 2px hsl(var(--ring) / 0.14);
}

.register-textarea:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.register-outlook-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.register-outlook-details {
  border-top: 1px solid hsl(var(--border) / 0.68);
  padding-top: 8px;
}

.register-outlook-import-report {
  display: grid;
  gap: 6px;
  border: 1px solid hsl(var(--border) / 0.72);
  border-radius: 10px;
  background: hsl(var(--muted) / 0.28);
  padding: 9px 10px;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
  line-height: 1.55;
}

.register-outlook-import-title {
  color: hsl(var(--foreground));
  font-weight: 600;
}

.register-outlook-import-issues {
  display: grid;
  gap: 3px;
}

.register-outlook-details summary {
  cursor: pointer;
  width: fit-content;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
  line-height: 1.4;
}

.register-outlook-details summary:hover {
  color: hsl(var(--foreground));
}

.register-outlook-detail-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 8px;
}

.register-runtime-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

@media (max-width: 1279px) {
  .register-runtime-column {
    position: static;
  }
}

@media (max-width: 640px) {
  .register-provider-head {
    display: grid;
    align-items: start;
  }

  .register-provider-actions,
  .register-outlook-toolbar,
  .register-runtime-actions {
    grid-template-columns: 1fr;
    justify-content: flex-start;
  }

  .register-outlook-toolbar {
    display: grid;
  }

  .register-runtime-actions {
    display: grid;
  }
}

.register-provider-config-hint {
  font-size: 0.8125rem;
  color: var(--color-text-muted, #6b7280);
  margin: 0 0 0.5rem;
}
.register-provider-empty {
  font-size: 0.8125rem;
  color: var(--color-text-muted, #9ca3af);
  padding: 0.5rem 0;
}
.register-provider-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.75rem;
}
.register-provider-test-result {
  margin-top: 0.5rem;
  font-size: 0.8125rem;
  color: var(--color-danger, #dc2626);
}
.register-provider-test-result.is-ok {
  color: var(--color-success, #16a34a);
}
</style>
