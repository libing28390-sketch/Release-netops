/** Explain binding failures without retrying or escalating the operation. */
export function getPlatformBindingErrorMessage(cause: unknown, language: string): string {
  const zh = language === 'zh';
  const error = cause && typeof cause === 'object'
    ? cause as { code?: unknown; detail?: unknown; message?: unknown; requestId?: unknown }
    : undefined;
  const detail = error?.detail && typeof error.detail === 'object'
    ? error.detail as { code?: unknown }
    : undefined;
  const code = typeof error?.code === 'string' ? error.code
    : typeof detail?.code === 'string' ? detail.code : '';
  const original = typeof error?.message === 'string' ? error.message : '';
  const messages: Record<string, string> = {
    PLATFORM_BINDING_LOCKED: zh
      ? '设备已有平台绑定。请刷新设备列表确认当前绑定；如需修改或解除，请使用管理员账号的“修改绑定”或“解除绑定”操作。'
      : 'The device already has a platform binding. Refresh the device list to check it, then use an Administrator account to modify or remove the binding.',
    PLATFORM_BIND_FORCE_FORBIDDEN: zh
      ? '仅管理员（Administrator）可以修改或解除已有平台绑定。请使用管理员账号操作。'
      : 'Only an Administrator can modify or remove an existing platform binding. Use an Administrator account.',
    PLATFORM_VERSION_OVERRIDE_FORBIDDEN: zh
      ? '仅管理员（Administrator）可以明确覆盖设备软件版本与平台适配版本不一致的限制。'
      : 'Only an Administrator can explicitly override a device software/platform adaptation version mismatch.',
  };
  const mapped = messages[code] || (
    /platform binding is immutable after first assignment/i.test(original)
      ? messages.PLATFORM_BINDING_LOCKED : undefined
  );
  if (!mapped) return original || (zh ? '平台绑定操作失败' : 'Platform binding operation failed');
  const requestId = typeof error?.requestId === 'string' ? error.requestId : '';
  return requestId ? `${mapped} (Request ID: ${requestId})` : mapped;
}
