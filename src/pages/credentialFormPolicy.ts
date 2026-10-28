export const isCliCredentialType = (value: unknown): boolean =>
  ['ssh_password', 'ssh_key'].includes(String(value || '').trim().toLowerCase());

export const shouldShowEnablePasswordField = (
  credentialType: unknown,
  explicitlyEnabled: boolean,
  editing?: { enable_password_supported?: boolean; has_enable_password?: boolean } | null,
): boolean => isCliCredentialType(credentialType) && (
  explicitlyEnabled
  || editing?.enable_password_supported === true
  || editing?.has_enable_password === true
);
