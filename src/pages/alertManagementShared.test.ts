import { describe, expect, it } from 'vitest';
import {
  alertRuleScopeSummary,
  buildEmptyRule,
  normalizeAlertRuleNotificationChannels,
  parseAlertCompositeScope,
  parseAlertScopeDeviceIds,
  parseAlertScopeIpValues,
  serializeAlertCompositeScope,
  serializeAlertScopeDeviceIds,
  toggleAlertNotificationChannel,
} from './alertManagementShared';

describe('toggleAlertNotificationChannel', () => {
  it('drops legacy personal preference when an explicit channel is selected', () => {
    expect(toggleAlertNotificationChannel(['workspace'], 'email')).toEqual(['email']);
  });

  it('allows multiple explicit channels to be selected together', () => {
    expect(toggleAlertNotificationChannel(['email'], 'feishu')).toEqual(['email', 'feishu']);
  });

  it('allows clearing the last explicit channel so the form can require a choice', () => {
    expect(toggleAlertNotificationChannel(['email'], 'email')).toEqual([]);
  });

  it('does not reintroduce a personal preference channel', () => {
    expect(toggleAlertNotificationChannel(['email', 'feishu'], 'workspace')).toEqual(['email', 'feishu']);
  });

  it('keeps an empty selection empty until the user chooses a method', () => {
    expect(toggleAlertNotificationChannel([], 'email')).toEqual(['email']);
    expect(toggleAlertNotificationChannel(undefined, 'workspace')).toEqual([]);
  });
});

describe('normalizeAlertRuleNotificationChannels', () => {
  it('maps legacy workspace rules to the supported Webhook and email methods', () => {
    expect(normalizeAlertRuleNotificationChannels(['workspace'])).toEqual(['feishu', 'email']);
  });

  it('keeps supported methods and removes unsupported legacy channels', () => {
    expect(normalizeAlertRuleNotificationChannels(['email', 'dingtalk'])).toEqual(['email']);
    expect(normalizeAlertRuleNotificationChannels(['dingtalk'])).toEqual(['feishu', 'email']);
  });

  it('preserves the internal marker for host health thresholds', () => {
    expect(normalizeAlertRuleNotificationChannels(['workspace'], true)).toEqual(['workspace']);
  });
});

describe('alert rule scope helpers', () => {
  it('round-trips scheduled-job style composite asset filters', () => {
    const value = serializeAlertCompositeScope({ site: 'HQ', role: 'core', category: '', platform: 'cisco_ios', interface: 'Gi0/1' });
    expect(parseAlertCompositeScope(value)).toEqual({ site: 'HQ', role: 'core', category: '', platform: 'cisco_ios', interface: 'Gi0/1' });
  });

  it('splits selected IP scope values on commas, semicolons, and whitespace', () => {
    expect(parseAlertScopeIpValues('192.0.2.1, 192.0.2.2;\n192.0.2.1')).toEqual(['192.0.2.1', '192.0.2.2']);
  });

  it('round-trips confirmed CMDB device IDs without duplicates', () => {
    const value = serializeAlertScopeDeviceIds(['device-1', 'device-2', 'device-1']);
    expect(value).toBe('["device-1","device-2"]');
    expect(parseAlertScopeDeviceIds(value)).toEqual(['device-1', 'device-2']);
    expect(parseAlertScopeDeviceIds('{"device_ids":["device-1"]}')).toEqual([]);
  });

  it('summarizes confirmed execution machines by count', () => {
    expect(alertRuleScopeSummary('devices', '["device-1","device-2"]', 'exact', 'zh')).toBe('2 台执行机器');
  });

  it('shows a concise readable summary instead of raw scope JSON', () => {
    expect(alertRuleScopeSummary('composite', '{"site":"HQ","role":"core","platform":"ios"}', 'contains', 'zh'))
      .toBe('站点: HQ · 角色: core · 平台: ios · 模糊');
  });

  it('creates new rules without a personal preference notification channel', () => {
    expect(buildEmptyRule('admin').notification_channels).toEqual([]);
  });
});
