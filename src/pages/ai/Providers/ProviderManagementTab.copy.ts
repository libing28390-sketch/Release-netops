/**
 * Page-local copy for the Provider page additions (review items L6-c / L6-d):
 * egress allowlist, key invalidation and key history.
 * Shared strings stay in src/i18n/aiAdmin.ts; only new labels live here.
 */
const zh = {
  // Egress allowlist (approved_endpoint_patterns)
  allowlistLabel: '外发白名单',
  allowlistInfoLabel: '外发白名单说明',
  allowlistHelp: '每行一个 HTTPS 地址，可用 * 通配，例如 https://api.deepseek.com/*。Base URL 必须被其中一条覆盖；留空时只允许当前 Base URL。这里只能在服务器配置的部署级白名单（AI_PROVIDER_ENDPOINT_ALLOWLIST）范围内收窄，不能新增范围外的地址或更宽的通配；服务器未配置部署级白名单时，只能填写当前 Base URL 本身。部署级白名单只有能修改服务器配置的人才能调整。',
  allowlistEmpty: '仅当前 Base URL',
  allowlistListAria: '已批准的外发地址',
  allowlistFieldHelp: '只能在服务器配置的部署级白名单范围内收窄；需要放行新地址时，请先由服务器管理员在 AI_PROVIDER_ENDPOINT_ALLOWLIST 中添加。留空则只允许当前 Base URL。',
  allowlistLocal: '本地 Provider 不经过外发白名单',
  allowlistInvalid: (line: string) => `白名单第 ${line} 行不是 HTTPS 地址`,
  allowlistExceedsDeployment: (patterns: string) => `外发白名单超出了服务器配置的部署级白名单范围${patterns ? `：${patterns}` : ''}。这里只能在部署级白名单范围内收窄；如需放行新的地址，请先由服务器管理员在服务器配置 AI_PROVIDER_ENDPOINT_ALLOWLIST 中添加。`,
  allowlistExceedsNoDeployment: (patterns: string) => `服务器未配置部署级白名单，外发白名单只能填写当前 Base URL 本身，不能使用通配或其他地址${patterns ? `：${patterns}` : ''}。如需放行更多地址，请先在服务器配置 AI_PROVIDER_ENDPOINT_ALLOWLIST 中添加。`,

  // Clearing fields on edit
  clearHint: '清空后保存即可删除原有值',

  // Key actions
  keyHistoryAction: '密钥历史',
  keyHistoryActionAria: (name: string) => `查看 ${name} 的密钥历史`,
  invalidateAction: '作废密钥',
  invalidateActionAria: (name: string) => `作废 ${name} 的密钥`,

  // Invalidate dialog
  invalidateTitle: '作废 API Key',
  invalidateBody: (name: string) => `作废后，“${name}”的当前密钥会立刻从数据库删除，Provider 停止调用，直到写入新密钥。此操作不能撤销。`,
  invalidateReason: '作废原因',
  invalidateReasonPlaceholder: '例如：密钥疑似泄露',
  invalidateReasonHelp: '最多 80 个字符，会写入审计记录。不填则记为“手动作废”。',
  invalidateReasonTooLong: '原因不能超过 80 个字符，也不能换行',
  invalidateConfirmCheck: '我了解作废后该 Provider 会立即停止调用',
  invalidateConfirm: '确认作废',
  invalidating: '正在作废…',
  invalidateCancel: '取消',
  invalidateDone: (name: string) => `已作废“${name}”的密钥`,
  invalidateFailed: '作废密钥失败',

  // Key history drawer
  historyTitle: (name: string) => `${name} · 密钥历史`,
  historyBody: (days: number) => `只显示版本、时间、操作人和状态，不显示任何密钥内容。被替换的旧密钥密文保留 ${days} 天后删除，作废的密钥密文立即删除。`,
  historyClose: '关闭',
  historyLoading: '正在加载密钥历史…',
  historyFailed: '加载密钥历史失败',
  historyRetry: '重试',
  historyVersions: '密钥版本',
  historyAudit: '操作记录',
  historyEmpty: '还没有密钥记录',
  historyEmptyBody: '写入第一个密钥后，这里会记录每个版本。',
  historyAuditEmpty: '暂无操作记录',
  colVersion: '版本',
  colStatus: '状态',
  colCreated: '写入时间',
  colCreatedBy: '操作人',
  colEnded: '停用时间',
  colCiphertext: '密文',
  colTime: '时间',
  colAction: '操作',
  colActor: '操作人',
  colReason: '原因',
  ciphertextRetained: '保留中',
  ciphertextDeleted: '已删除',
  statusActive: '使用中',
  statusRetired: '已替换',
  statusInvalidated: '已作废',
  actionRotate: '写入新密钥',
  actionInvalidate: '作废',
  reasons: {
    provider_created: '新建时写入',
    provider_updated: '编辑时更换',
    manual_rotation: '手动轮换',
    endpoint_changed: '端点变更，旧密钥已清除',
    endpoint_changed_key_replaced: '端点变更并更换密钥',
    cleared_in_edit: '编辑时清空',
    manual_invalidation: '手动作废',
  } as Record<string, string>,
};

type ProviderPageCopyShape = typeof zh;

const en: ProviderPageCopyShape = {
  allowlistLabel: 'Egress allowlist',
  allowlistInfoLabel: 'About the egress allowlist',
  allowlistHelp: 'One HTTPS URL per line; * is a wildcard, e.g. https://api.deepseek.com/*. The Base URL must match one entry; leave empty to allow only the current Base URL. This list can only narrow the deployment allowlist configured on the server (AI_PROVIDER_ENDPOINT_ALLOWLIST): it cannot add addresses outside it or wider wildcards. Without a deployment allowlist only the current Base URL itself is accepted. Only people who can change the server configuration can change the deployment allowlist.',
  allowlistEmpty: 'Current Base URL only',
  allowlistListAria: 'Approved egress endpoints',
  allowlistFieldHelp: 'Can only narrow the deployment allowlist configured on the server; to allow a new address, a server administrator must first add it to AI_PROVIDER_ENDPOINT_ALLOWLIST. Leave empty to allow only the current Base URL.',
  allowlistLocal: 'Local providers bypass the egress allowlist',
  allowlistInvalid: (line: string) => `Allowlist line ${line} is not an HTTPS URL`,
  allowlistExceedsDeployment: (patterns: string) => `The egress allowlist goes beyond the deployment allowlist configured on the server${patterns ? `: ${patterns}` : ''}. It can only narrow the deployment allowlist; to allow a new address, a server administrator must first add it to AI_PROVIDER_ENDPOINT_ALLOWLIST.`,
  allowlistExceedsNoDeployment: (patterns: string) => `No deployment allowlist is configured on the server, so the egress allowlist may only contain the current Base URL itself, without wildcards or other addresses${patterns ? `: ${patterns}` : ''}. To allow more addresses, add them to AI_PROVIDER_ENDPOINT_ALLOWLIST in the server configuration first.`,

  clearHint: 'Clear the field and save to remove the value',

  keyHistoryAction: 'Key history',
  keyHistoryActionAria: (name: string) => `View key history of ${name}`,
  invalidateAction: 'Invalidate key',
  invalidateActionAria: (name: string) => `Invalidate the key of ${name}`,

  invalidateTitle: 'Invalidate API key',
  invalidateBody: (name: string) => `The current key of "${name}" is deleted from the database immediately and the Provider stops serving requests until a new key is written. This cannot be undone.`,
  invalidateReason: 'Reason',
  invalidateReasonPlaceholder: 'e.g. key may have leaked',
  invalidateReasonHelp: 'Up to 80 characters, stored in the audit trail. Defaults to "manual invalidation".',
  invalidateReasonTooLong: 'The reason must be at most 80 characters on one line',
  invalidateConfirmCheck: 'I understand this Provider stops serving requests immediately',
  invalidateConfirm: 'Invalidate',
  invalidating: 'Invalidating…',
  invalidateCancel: 'Cancel',
  invalidateDone: (name: string) => `Key of "${name}" invalidated`,
  invalidateFailed: 'Failed to invalidate the key',

  historyTitle: (name: string) => `${name} · Key history`,
  historyBody: (days: number) => `Shows versions, times, actors and status only, never key material. Ciphertexts of replaced keys are deleted after ${days} days; invalidated keys are deleted immediately.`,
  historyClose: 'Close',
  historyLoading: 'Loading key history…',
  historyFailed: 'Failed to load key history',
  historyRetry: 'Retry',
  historyVersions: 'Key versions',
  historyAudit: 'Activity',
  historyEmpty: 'No keys yet',
  historyEmptyBody: 'Each key version is recorded here once a key is written.',
  historyAuditEmpty: 'No activity yet',
  colVersion: 'Version',
  colStatus: 'Status',
  colCreated: 'Written',
  colCreatedBy: 'By',
  colEnded: 'Ended',
  colCiphertext: 'Ciphertext',
  colTime: 'Time',
  colAction: 'Action',
  colActor: 'Actor',
  colReason: 'Reason',
  ciphertextRetained: 'Retained',
  ciphertextDeleted: 'Deleted',
  statusActive: 'Active',
  statusRetired: 'Replaced',
  statusInvalidated: 'Invalidated',
  actionRotate: 'New key written',
  actionInvalidate: 'Invalidated',
  reasons: {
    provider_created: 'Written at creation',
    provider_updated: 'Replaced while editing',
    manual_rotation: 'Manual rotation',
    endpoint_changed: 'Endpoint changed, old key cleared',
    endpoint_changed_key_replaced: 'Endpoint changed, key replaced',
    cleared_in_edit: 'Cleared while editing',
    manual_invalidation: 'Manual invalidation',
  },
};

export const providerPageCopy = { zh, en };

export type ProviderPageCopy = ProviderPageCopyShape;

export const getProviderPageCopy = (language?: string): ProviderPageCopy => (language === 'en' ? en : zh);
