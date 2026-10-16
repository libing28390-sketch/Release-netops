import { describe, expect, it } from 'vitest';
import { isCliCredentialType, shouldShowEnablePasswordField } from './credentialFormPolicy';

describe('credential Enable password visibility', () => {
  it('keeps the Cisco-only field hidden by default when creating generic SSH credentials', () => {
    expect(isCliCredentialType('ssh_password')).toBe(true);
    expect(shouldShowEnablePasswordField('ssh_password', false)).toBe(false);
  });

  it('shows it only after explicit Cisco opt-in for SSH credentials', () => {
    expect(shouldShowEnablePasswordField('ssh_password', true)).toBe(true);
    expect(shouldShowEnablePasswordField('ssh_key', true)).toBe(true);
    expect(shouldShowEnablePasswordField('snmpv2', true)).toBe(false);
    expect(shouldShowEnablePasswordField('api_token', true)).toBe(false);
  });

  it('keeps an existing Cisco enable secret editable when the stored credential supports it', () => {
    expect(shouldShowEnablePasswordField('ssh_password', false, { enable_password_supported: true })).toBe(true);
    expect(shouldShowEnablePasswordField('ssh_password', false, { has_enable_password: true })).toBe(true);
    expect(shouldShowEnablePasswordField('ssh_password', false, { enable_password_supported: false })).toBe(false);
  });
});
