import { describe, expect, it } from 'vitest';
import { ApiError } from '../api/http';
import { getPlatformBindingErrorMessage } from './platformBindingErrors';

describe('platform binding errors', () => {
  it('reads the detail code returned by registry routes and preserves the request ID', () => {
    const cause = new ApiError(409, 'Device device-1 platform binding is immutable after first assignment',
      { code: 'PLATFORM_BINDING_LOCKED' }, 'binding-request-1');
    const message = getPlatformBindingErrorMessage(cause, 'zh');
    expect(message).toContain('刷新设备列表');
    expect(message).toContain('管理员账号');
    expect(message).toContain('Request ID: binding-request-1');
    expect(message).not.toContain('device-1');
  });

  it.each(['zh', 'en'])('explains force and version override permission failures in %s', (language) => {
    for (const code of ['PLATFORM_BIND_FORCE_FORBIDDEN', 'PLATFORM_VERSION_OVERRIDE_FORBIDDEN']) {
      const cause = new ApiError(403, 'Device or platform is outside the current resource scope', undefined, undefined, code);
      expect(getPlatformBindingErrorMessage(cause, language)).toContain('Administrator');
    }
  });

  it('recognizes older immutable error messages without a structured code', () => {
    expect(getPlatformBindingErrorMessage(new Error('Device platform binding is immutable after first assignment'), 'en'))
      .toContain('Refresh the device list');
  });

  it('preserves unrelated compatibility, scope and network errors', () => {
    for (const code of ['PLATFORM_VERSION_MISMATCH', 'PLATFORM_SCOPE_DENIED', 'PLATFORM_VENDOR_MISMATCH']) {
      const cause = new ApiError(409, 'Specific backend explanation (Request ID: original)', { code });
      expect(getPlatformBindingErrorMessage(cause, 'zh')).toBe(cause.message);
    }
    expect(getPlatformBindingErrorMessage(new Error('Network unavailable'), 'en')).toBe('Network unavailable');
    expect(getPlatformBindingErrorMessage(null, 'zh')).toBe('平台绑定操作失败');
  });
});
