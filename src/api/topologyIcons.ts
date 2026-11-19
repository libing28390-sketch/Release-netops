import { apiRequest, authHeaders } from './http';
import type { TopologyIconType } from '../domain/topologyDeviceIcons';

export interface TopologyIcon {
  id: string;
  device_type: TopologyIconType;
  name: string;
  content_url: string;
}

export interface TopologyDeviceIconOverride {
  icon_id: string;
  device_type: TopologyIconType;
}

export interface TopologyIconCatalog {
  icons: TopologyIcon[];
  type_defaults: Partial<Record<TopologyIconType, string | null>>;
  device_overrides: Record<string, TopologyDeviceIconOverride>;
  can_manage: boolean;
}

export interface TopologyIconUpload {
  deviceType: TopologyIconType;
  name: string;
  file: File;
}

const ICONS_ENDPOINT = '/api/topology/icons';
const iconDataUrls = new Map<string, Promise<string>>();

export const getTopologyIconCatalog = (): Promise<TopologyIconCatalog> => (
  apiRequest<TopologyIconCatalog>(ICONS_ENDPOINT)
);

export const uploadTopologyIcon = ({ deviceType, name, file }: TopologyIconUpload): Promise<TopologyIcon> => {
  const body = new FormData();
  body.append('device_type', deviceType);
  body.append('name', name.trim());
  body.append('file', file, file.name);
  return apiRequest<TopologyIcon>(ICONS_ENDPOINT, { method: 'POST', body });
};

export const setTopologyIconTypeDefault = (
  deviceType: TopologyIconType,
  iconId: string | null,
): Promise<{ success: boolean }> => (
  apiRequest(`${ICONS_ENDPOINT}/defaults/${encodeURIComponent(deviceType)}`, {
    method: 'PUT',
    body: JSON.stringify({ icon_id: iconId }),
  })
);

export const setTopologyDeviceIcon = (
  deviceId: string,
  deviceType: TopologyIconType,
  iconId: string | null,
): Promise<{ success: boolean }> => (
  apiRequest(`${ICONS_ENDPOINT}/devices/${encodeURIComponent(deviceId)}`, {
    method: 'PUT',
    body: JSON.stringify({ device_type: deviceType, icon_id: iconId }),
  })
);

const blobToDataUrl = async (blob: Blob): Promise<string> => {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = '';
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return `data:${blob.type || 'application/octet-stream'};base64,${btoa(binary)}`;
};

const resolveIconUrl = (contentUrl: string): URL => {
  const url = new URL(contentUrl, window.location.origin);
  if (url.origin !== window.location.origin || !url.pathname.startsWith(`${ICONS_ENDPOINT}/`)) {
    throw new Error('Icon URLs must use the same-origin topology icon endpoint.');
  }
  return url;
};

/** Fetch protected same-origin icon content so both the canvas and SVG export can embed it. */
export const getTopologyIconDataUrl = (icon: TopologyIcon): Promise<string> => {
  const cached = iconDataUrls.get(icon.id);
  if (cached) return cached;

  const request = (async () => {
    const url = resolveIconUrl(icon.content_url);
    const response = await fetch(url, {
      headers: authHeaders(),
      credentials: 'same-origin',
    });
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new Event('netops:auth-expired'));
      throw new Error(`Icon request failed with status ${response.status}.`);
    }
    const blob = await response.blob();
    if (blob.size === 0) throw new Error('The icon file is empty.');
    if (blob.type !== 'image/png' && blob.type !== 'image/svg+xml') throw new Error('The icon response is not PNG or SVG.');
    return blobToDataUrl(blob);
  })();

  iconDataUrls.set(icon.id, request);
  void request.catch(() => {
    if (iconDataUrls.get(icon.id) === request) iconDataUrls.delete(icon.id);
  });
  return request;
};
