import type { WebAccessProfile } from '../pages/AssetManagement/types';

export type WebAccessLevel = 'normal' | 'admin';

function agentBaseUrl() {
  return (localStorage.getItem('terminal_agent_url') || 'http://127.0.0.1:17890').replace(/\/$/, '');
}

export async function ensurePamWebAgent() {
  const response = await fetch(`${agentBaseUrl()}/health`, { cache: 'no-store' });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload?.success) throw new Error(payload?.error || `HTTP ${response.status}`);
  const capabilities = Array.isArray(payload?.capabilities) ? payload.capabilities : [];
  if (!capabilities.includes('web_access')) {
    throw new Error('WEB_AGENT_UPGRADE_REQUIRED');
  }
  return payload;
}

interface CreateWebSessionInput {
  assetId: string;
  profileId: string;
  accessLevel: WebAccessLevel;
  reason: string;
}

export async function createPamWebSession(input: CreateWebSessionInput) {
  const token = localStorage.getItem('netops_token') || '';
  const response = await fetch('/api/pam/web-sessions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      asset_id: input.assetId,
      web_profile_id: input.profileId,
      access_level: input.accessLevel,
      reason: input.reason,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.detail || payload?.error || `HTTP ${response.status}`);
  return payload as { session_id: string; session_token: string; expires_at: string };
}

export async function launchPamWebSession(sessionToken: string) {
  const response = await fetch(`${agentBaseUrl()}/v1/web/launch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      backend_url: window.location.origin,
      session_token: sessionToken,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload?.success) throw new Error(payload?.error || `HTTP ${response.status}`);
  return payload as { success: true; session_id?: string };
}

export function enabledWebProfiles(profiles: WebAccessProfile[] | undefined) {
  return (profiles || []).filter(profile => profile.enabled !== false && Boolean(profile.id));
}
