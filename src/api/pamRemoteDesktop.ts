import { apiRequest } from './http';
import type {
  RemoteDesktopProfile,
  RemoteDesktopProtocol,
} from '../pages/AssetManagement/types';

export type RemoteDesktopAccessLevel = 'normal' | 'admin';

export type RemoteDesktopProfileInput = Omit<RemoteDesktopProfile, 'id' | 'asset_id' | 'protocol' | 'rdp_domain'> & {
  rdp_domain?: string;
};

export interface PamRemoteDesktopSession {
  session_id: string;
  session_token: string;
  expires_at: string;
  protocol: RemoteDesktopProtocol;
  connect: {
    ws_url: string;
  };
}

interface ApiEnvelope<T> {
  success?: boolean;
  data?: T;
  error?: string | { message?: string };
  detail?: string;
}

function unwrapData<T>(payload: ApiEnvelope<T> | T): T {
  if (payload && typeof payload === 'object' && 'success' in payload) {
    const envelope = payload as ApiEnvelope<T>;
    if (envelope.success === false) {
      const message = typeof envelope.error === 'string'
        ? envelope.error
        : envelope.error?.message || envelope.detail || 'Request failed';
      throw new Error(message);
    }
    if ('data' in envelope) return envelope.data as T;
  }
  return payload as T;
}

export async function listRemoteDesktopProfiles(assetId: string, signal?: AbortSignal): Promise<RemoteDesktopProfile[]> {
  const payload = await apiRequest<ApiEnvelope<RemoteDesktopProfile[]> | RemoteDesktopProfile[]>(
    `/api/assets/${encodeURIComponent(assetId)}/remote-desktop-profiles`,
    { signal, cache: 'no-store' },
  );
  const data = unwrapData(payload);
  if (!Array.isArray(data)) throw new Error('Invalid remote desktop profile response');
  return data;
}

export async function saveRemoteDesktopProfile(
  assetId: string,
  protocol: RemoteDesktopProtocol,
  profile: RemoteDesktopProfileInput,
): Promise<RemoteDesktopProfile> {
  const payload = await apiRequest<ApiEnvelope<RemoteDesktopProfile> | RemoteDesktopProfile>(
    `/api/assets/${encodeURIComponent(assetId)}/remote-desktop-profiles/${protocol}`,
    { method: 'PUT', body: JSON.stringify(profile) },
  );
  return unwrapData(payload);
}

/** Fetch profiles in batches of at most 200 asset IDs, as required by the API. */
export async function listRemoteDesktopProfilesBatch(
  assetIds: string[],
  signal?: AbortSignal,
): Promise<RemoteDesktopProfile[]> {
  const uniqueIds = Array.from(new Set(assetIds.map(id => String(id).trim()).filter(Boolean)));
  const batches: string[][] = [];
  for (let index = 0; index < uniqueIds.length; index += 200) {
    batches.push(uniqueIds.slice(index, index + 200));
  }

  const results = await Promise.all(batches.map(async (batch) => {
    const params = new URLSearchParams({ asset_ids: batch.join(',') });
    const payload = await apiRequest<ApiEnvelope<RemoteDesktopProfile[]> | RemoteDesktopProfile[]>(
      `/api/pam/remote-desktop-profiles?${params.toString()}`,
      { signal, cache: 'no-store' },
    );
    const data = unwrapData(payload);
    if (!Array.isArray(data)) throw new Error('Invalid remote desktop profile response');
    return data;
  }));

  return results.flat();
}

export interface CreatePamRemoteDesktopSessionInput {
  assetId: string;
  protocol: RemoteDesktopProtocol;
  accessLevel: RemoteDesktopAccessLevel;
  reason: string;
  fixedPin?: string;
  mfaCode?: string;
}

export async function createPamRemoteDesktopSession(
  input: CreatePamRemoteDesktopSessionInput,
): Promise<PamRemoteDesktopSession> {
  const payload = await apiRequest<ApiEnvelope<PamRemoteDesktopSession> | PamRemoteDesktopSession>(
    '/api/pam/remote-desktop-sessions',
    {
      method: 'POST',
      body: JSON.stringify({
        asset_id: input.assetId,
        protocol: input.protocol,
        access_level: input.accessLevel,
        reason: input.reason.trim(),
        ...(input.accessLevel === 'admin' ? {
          fixed_pin: input.fixedPin,
          mfa_code: input.mfaCode,
        } : {}),
      }),
    },
  );
  const session = unwrapData(payload);
  if (!session?.session_id || !session.connect?.ws_url || !session.session_token) {
    throw new Error('Invalid remote desktop session response');
  }
  return session;
}
